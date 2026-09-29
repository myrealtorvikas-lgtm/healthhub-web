import os
import re
import json
import uuid
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Flask, redirect, url_for, session, request, render_template, abort, flash, jsonify

from config import Config
from models import db, User, ManualEntry, utcnow, CgmReading, CgmEvent, LabPanel, LabResult, DexaScan, DexaResult, UploadedFile
from report_builder import build_report_data
from markers import MARKER_DEFS
from importers import libreview_csv, quest_pdf, dexa_pdf

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

    # ---------------------------------------------------------------
    # Auth helpers
    # ---------------------------------------------------------------
    def current_user():
        uid = session.get("user_id")
        if not uid:
            return None
        return db.session.get(User, uid)

    def login_required(view):
        from functools import wraps

        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user():
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    # ---------------------------------------------------------------
    # Public pages
    # ---------------------------------------------------------------
    @app.route("/")
    def index():
        if current_user():
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    # ---------------------------------------------------------------
    # Accounts — plain email + password, self-serve. No wearable
    # connection is required to create an account; Whoop/Oura data (once
    # a parser exists for it) comes in as a manual export upload like
    # everything else on the dashboard.
    # ---------------------------------------------------------------
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "GET":
            return render_template("signup.html")

        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        first_name = (request.form.get("first_name") or "").strip()

        if not EMAIL_RE.match(email):
            flash("Please enter a valid email address.")
            return render_template("signup.html", email=email, first_name=first_name)
        if len(password) < 8:
            flash("Password needs to be at least 8 characters.")
            return render_template("signup.html", email=email, first_name=first_name)
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists — try signing in instead.")
            return redirect(url_for("login"))

        user = User(email=email, first_name=first_name or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        return redirect(url_for("dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html")

        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("That email/password combination doesn't match an account.")
            return render_template("login.html", email=email)

        user.last_login_at = utcnow()
        db.session.commit()
        session["user_id"] = user.id
        return redirect(url_for("dashboard"))

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------------------------------------------------------------
    # Dashboard + manual entry
    # ---------------------------------------------------------------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = current_user()
        uploads = (UploadedFile.query.filter_by(user_id=user.id)
                   .order_by(UploadedFile.uploaded_at.desc()).all())
        latest_by_kind = {}
        for u in uploads:
            latest_by_kind.setdefault(u.kind, u)
        return render_template(
            "dashboard.html",
            user=user,
            marker_defs=MARKER_DEFS,
            manual=user.manual_entries,
            latest_by_kind=latest_by_kind,
        )

    @app.route("/manual-entry", methods=["POST"])
    @login_required
    def manual_entry():
        user = current_user()
        entry = user.manual_entries or ManualEntry(user_id=user.id)

        def to_float(name):
            raw = request.form.get(name, "").strip()
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        entry.sex = request.form.get("sex") or None
        entry.height_cm = to_float("height_cm")
        entry.weight_kg = to_float("weight_kg")

        markers = dict(entry.blood_markers or {})
        for marker_id, _label, _unit in MARKER_DEFS:
            val = to_float(f"marker_{marker_id}")
            if val is not None:
                markers[marker_id] = val
        entry.blood_markers = markers

        db.session.add(entry)
        db.session.commit()
        flash("Saved.")
        return redirect(url_for("dashboard"))

    # ---------------------------------------------------------------
    # The report itself
    # ---------------------------------------------------------------
    @app.route("/report")
    @login_required
    def report():
        user = current_user()

        window_start = (utcnow() - timedelta(days=Config.REPORT_WINDOW_DAYS)).isoformat()
        cgm_readings = (CgmReading.query.filter_by(user_id=user.id)
                         .filter(CgmReading.timestamp >= window_start).all())
        latest_lab_panel = (LabPanel.query.filter_by(user_id=user.id)
                            .order_by(LabPanel.collected_date.desc()).first())
        latest_dexa_scan = (DexaScan.query.filter_by(user_id=user.id)
                           .order_by(DexaScan.scan_date.desc()).first())

        try:
            data = build_report_data(
                whoop_client=None,  # no live Whoop/Oura connection — see report_builder.py
                manual_entry=user.manual_entries,
                first_name=user.first_name,
                window_days=Config.REPORT_WINDOW_DAYS,
                cgm_readings=cgm_readings,
                latest_lab_panel=latest_lab_panel,
                latest_dexa_scan=latest_dexa_scan,
            )
        except Exception:
            app.logger.exception("Failed to build report for user %s", user.id)
            flash("Couldn't build your report just now — please try again in a moment.")
            return redirect(url_for("dashboard"))

        return render_template("report.html", data_json=json.dumps(data), marker_defs=MARKER_DEFS)

    # ---------------------------------------------------------------
    # Whoop / Oura / Apple Health exports — saved and recorded, not
    # parsed yet. Real health data formats aren't guessed at blind here
    # (same rule report_builder.py already followed for Apple Health) —
    # a real sample export is needed to build and test each parser
    # before it touches anyone's data.
    # ---------------------------------------------------------------
    ALLOWED_EXPORT_KINDS = {"whoop_export", "oura_export", "apple_health"}

    @app.route("/api/import/export-file", methods=["POST"])
    @login_required
    def api_import_export_file():
        kind = request.form.get("kind", "")
        if kind not in ALLOWED_EXPORT_KINDS:
            return jsonify({"ok": False, "error": "Unknown export kind"}), 400
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"ok": False, "error": "No file uploaded"}), 400

        user = current_user()
        user_dir = os.path.join(Config.UPLOAD_FOLDER, str(user.id))
        os.makedirs(user_dir, exist_ok=True)
        safe_name = secure_filename(file.filename)
        stored_name = f"{kind}-{uuid.uuid4().hex[:8]}-{safe_name}"
        storage_path = os.path.join(user_dir, stored_name)
        file.save(storage_path)

        record = UploadedFile(user_id=user.id, kind=kind, original_filename=file.filename,
                               storage_path=storage_path, parsed=False)
        db.session.add(record)
        db.session.commit()

        return jsonify({"ok": True, "filename": file.filename,
                         "note": "Saved. This file type doesn't have an automatic parser built yet, "
                                 "so nothing from it is in your report until that's built and tested."})

    # ---------------------------------------------------------------
    # CGM (Lingo/LibreView) — imports straight through, no review step.
    # Uses the same parser as Vikas's own local Health Hub.
    # ---------------------------------------------------------------
    @app.route("/import/cgm")
    @login_required
    def import_cgm_page():
        recent_count = CgmReading.query.filter_by(user_id=current_user().id).count()
        return render_template("import_cgm.html", recent_count=recent_count)

    @app.route("/api/import/cgm", methods=["POST"])
    @login_required
    def api_import_cgm():
        file = request.files.get("file")
        if not file:
            return jsonify({"ok": False, "error": "No file uploaded"}), 400
        try:
            parsed = libreview_csv.parse(file.read())
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        user_id = current_user().id
        inserted_readings, inserted_events = 0, 0
        for r in parsed["readings"]:
            exists = CgmReading.query.filter_by(user_id=user_id, timestamp=r["timestamp"], source="libreview").first()
            if exists:
                continue
            db.session.add(CgmReading(user_id=user_id, timestamp=r["timestamp"],
                                       glucose_mgdl=r["glucose_mgdl"], record_type=r["record_type"]))
            inserted_readings += 1
        for e in parsed["events"]:
            db.session.add(CgmEvent(user_id=user_id, timestamp=e["timestamp"], event_type=e["event_type"],
                                     description=e["description"], carbs_g=e["carbs_g"], insulin_units=e["insulin_units"]))
            inserted_events += 1
        db.session.commit()

        return jsonify({"ok": True, "readings_imported": inserted_readings,
                         "events_imported": inserted_events, "rows_skipped": parsed["skipped"]})

    # ---------------------------------------------------------------
    # Quest (or any lab) blood panel — parse, human reviews/edits the
    # extracted rows, then confirms the save. Same two-step pattern as
    # the local app, since PDF layouts vary and a human check is the
    # real safety net for real health numbers.
    # ---------------------------------------------------------------
    @app.route("/import/labs")
    @login_required
    def import_labs_page():
        panels = LabPanel.query.filter_by(user_id=current_user().id).order_by(LabPanel.collected_date.desc()).all()
        return render_template("import_labs.html", panels=panels)

    @app.route("/api/import/labs", methods=["POST"])
    @login_required
    def api_import_labs():
        file = request.files.get("file")
        if not file:
            return jsonify({"ok": False, "error": "No file uploaded"}), 400
        file_bytes = file.read()
        try:
            parsed = quest_pdf.parse(file_bytes)
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "rows": parsed["rows"], "filename": file.filename})

    @app.route("/api/labs/save", methods=["POST"])
    @login_required
    def api_save_labs():
        data = request.get_json()
        collected_date = data.get("collected_date")
        rows = data.get("rows", [])
        if not collected_date or not rows:
            return jsonify({"ok": False, "error": "Missing date or rows"}), 400
        panel = LabPanel(user_id=current_user().id, collected_date=collected_date,
                          source_file=data.get("filename", ""), notes=data.get("notes", ""))
        db.session.add(panel)
        db.session.flush()
        for row in rows:
            db.session.add(LabResult(
                panel_id=panel.id, analyte=row.get("label"), value=row.get("value"),
                value_text=row.get("value_text"), unit=row.get("unit"),
                ref_low=row.get("ref_low"), ref_high=row.get("ref_high"), flag=row.get("flag"),
            ))
        db.session.commit()
        return jsonify({"ok": True, "panel_id": panel.id})

    # ---------------------------------------------------------------
    # DEXA scan — same review-before-save pattern as labs.
    # ---------------------------------------------------------------
    @app.route("/import/dexa")
    @login_required
    def import_dexa_page():
        scans = DexaScan.query.filter_by(user_id=current_user().id).order_by(DexaScan.scan_date.desc()).all()
        return render_template("import_dexa.html", scans=scans)

    @app.route("/api/import/dexa", methods=["POST"])
    @login_required
    def api_import_dexa():
        file = request.files.get("file")
        if not file:
            return jsonify({"ok": False, "error": "No file uploaded"}), 400
        file_bytes = file.read()
        try:
            parsed = dexa_pdf.parse(file_bytes)
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "rows": parsed["rows"], "filename": file.filename})

    @app.route("/api/dexa/save", methods=["POST"])
    @login_required
    def api_save_dexa():
        data = request.get_json()
        scan_date = data.get("scan_date")
        rows = data.get("rows", [])
        if not scan_date or not rows:
            return jsonify({"ok": False, "error": "Missing date or rows"}), 400
        scan = DexaScan(user_id=current_user().id, scan_date=scan_date,
                         source_file=data.get("filename", ""), notes=data.get("notes", ""))
        db.session.add(scan)
        db.session.flush()
        for row in rows:
            db.session.add(DexaResult(scan_id=scan.id, metric=row.get("label"),
                                       value=row.get("value"), unit=row.get("unit")))
        db.session.commit()
        return jsonify({"ok": True, "scan_id": scan.id})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
