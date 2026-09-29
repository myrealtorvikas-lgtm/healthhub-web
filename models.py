from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    """One row per person with their own account. Self-serve signup with an
    email + password — nobody needs to be invited or connect a wearable just
    to create an account. (Earlier version of this app used "Continue with
    Whoop" as the login itself; that's gone now that Whoop/Oura data comes in
    as a manually-uploaded export instead of a live account connection, same
    as every other data type here.)"""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    # Kept only so old rows created back when Whoop login WAS the account
    # system still load; nothing new writes to this column.
    whoop_user_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login_at = db.Column(db.DateTime, default=utcnow)

    manual_entries = db.relationship("ManualEntry", backref="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class ManualEntry(db.Model):
    """The stuff Whoop doesn't provide: blood work, body basics, and the
    daily-routine/supplement reference content is static so it needs no
    storage. One row per user, updated in place — mirrors the same fields
    as the standalone Health Snapshot artifact, so a person's data is
    consistent whichever entry point they used."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    sex = db.Column(db.String(20))
    height_cm = db.Column(db.Float)
    weight_kg = db.Column(db.Float)
    # Blood markers stored as a small JSON blob rather than one column each —
    # keeps this table from needing a migration every time a marker is added.
    blood_markers = db.Column(db.JSON, default=dict)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class UploadedFile(db.Model):
    """Generic landing spot for exports that don't have a trustworthy parser
    yet: apple_health, whoop_export, oura_export. The file is saved and the
    row records that it exists, so nothing is silently lost while a real
    parser gets built and tested against an actual sample of that file —
    same caution report_builder.py already used for Apple Health: don't
    guess a health-data file format blind."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(30))  # 'apple_health' | 'whoop_export' | 'oura_export'
    original_filename = db.Column(db.String(255))
    storage_path = db.Column(db.String(500))
    parsed = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=utcnow)


# ---------------------------------------------------------------------
# CGM (Lingo/LibreView) — parsed by importers/libreview_csv.py, same
# format Vikas's own local Health Hub reads. Readings import straight
# through (no review step — a CGM export is thousands of rows, not a
# handful of lab values); events (meals/insulin/notes) alongside them.
# ---------------------------------------------------------------------
class CgmReading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    timestamp = db.Column(db.String(40), nullable=False)  # ISO string, as the parser emits it
    glucose_mgdl = db.Column(db.Float, nullable=False)
    record_type = db.Column(db.String(20))
    source = db.Column(db.String(20), default="libreview")
    __table_args__ = (db.UniqueConstraint("user_id", "timestamp", "source", name="uq_cgm_reading"),)


class CgmEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    timestamp = db.Column(db.String(40), nullable=False)
    event_type = db.Column(db.String(20))
    description = db.Column(db.String(255))
    carbs_g = db.Column(db.Float)
    insulin_units = db.Column(db.Float)
    source = db.Column(db.String(20), default="libreview")


# ---------------------------------------------------------------------
# Quest (or any lab) blood panel — parsed by importers/quest_pdf.py.
# Rows go through a review screen before saving (see /api/import/labs and
# /api/labs/save in app.py), same as Vikas's local app, since PDF layouts
# vary and a human check is the real safety net here.
# ---------------------------------------------------------------------
class LabPanel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    collected_date = db.Column(db.String(20))
    source_file = db.Column(db.String(255))
    notes = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=utcnow)
    results = db.relationship("LabResult", backref="panel", cascade="all, delete-orphan")


class LabResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    panel_id = db.Column(db.Integer, db.ForeignKey("lab_panel.id"), nullable=False, index=True)
    analyte = db.Column(db.String(120))
    value = db.Column(db.Float)
    value_text = db.Column(db.String(120))
    unit = db.Column(db.String(30))
    ref_low = db.Column(db.Float)
    ref_high = db.Column(db.Float)
    flag = db.Column(db.String(10))


# ---------------------------------------------------------------------
# DEXA scan — parsed by importers/dexa_pdf.py. Same review-before-save
# pattern as labs.
# ---------------------------------------------------------------------
class DexaScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    scan_date = db.Column(db.String(20))
    source_file = db.Column(db.String(255))
    notes = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=utcnow)
    results = db.relationship("DexaResult", backref="scan", cascade="all, delete-orphan")


class DexaResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey("dexa_scan.id"), nullable=False, index=True)
    metric = db.Column(db.String(120))
    value = db.Column(db.Float)
    unit = db.Column(db.String(30))
