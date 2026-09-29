"""
End-to-end smoke test. Exercises every Flask route through the test
client: signup, login/logout, dashboard, manual entry, report rendering,
CGM import + dedupe, labs import + save, DEXA import + save, the raw
Quest-PDF regex extraction, and the generic export-file upload endpoint
(Whoop/Oura/Apple Health exports, saved but not parsed yet).
"""
import os
import sys
import io
import json as _json
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet

os.environ["FLASK_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()  # unused now, harmless if set

sys.path.insert(0, os.path.dirname(__file__))

import app as app_module  # noqa: E402
from models import db, User, ManualEntry  # noqa: E402
from importers import quest_pdf as quest_pdf_module  # noqa: E402

flask_app = app_module.app


def run():
    with flask_app.app_context():
        db.drop_all()
        db.create_all()

    client = flask_app.test_client()

    # ---- login page (unauthenticated) ----
    r = client.get("/")
    assert r.status_code in (302, 200)
    r = client.get("/login")
    assert r.status_code == 200 and b"Sign in" in r.data, "login page failed to render"
    print("PASS: login page renders")

    # ---- signup ----
    r = client.post("/signup", data={
        "first_name": "Priya", "email": "priya@example.com", "password": "correct-horse-battery",
    }, follow_redirects=True)
    assert r.status_code == 200, r.data
    with flask_app.app_context():
        user = User.query.filter_by(email="priya@example.com").first()
        assert user is not None, "signup did not create a user"
        user_id = user.id
    print("PASS: signup creates an account and logs the user in")

    # signing up again with the same email should be rejected
    r = client.post("/signup", data={
        "first_name": "Priya", "email": "priya@example.com", "password": "another-password",
    }, follow_redirects=True)
    assert b"already exists" in r.data
    print("PASS: duplicate signup email is rejected")

    # ---- logout + login round trip ----
    client.get("/logout")
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302, "dashboard should redirect to login when signed out"
    r = client.post("/login", data={"email": "priya@example.com", "password": "wrong-password"})
    assert b"match an account" in r.data
    print("PASS: wrong password is rejected")
    r = client.post("/login", data={"email": "priya@example.com", "password": "correct-horse-battery"},
                     follow_redirects=True)
    assert r.status_code == 200
    print("PASS: correct password logs back in")

    with flask_app.app_context():
        manual = ManualEntry(
            user_id=user_id, sex="female", height_cm=165, weight_kg=82,
            blood_markers={"glucose": 108, "hdl": 38, "vitd": 18, "hgb": 13.9},
        )
        db.session.add(manual)
        db.session.commit()

    r = client.get("/dashboard")
    assert r.status_code == 200, f"dashboard failed: {r.status_code}"
    assert b"Hi Priya" in r.data
    assert b"108" in r.data or b"value=\"108" in r.data  # saved glucose value round-trips into the form
    print("PASS: dashboard renders with account name and saved manual entry")

    # ---- manual entry form submission ----
    r = client.post("/manual-entry", data={
        "sex": "female", "height_cm": "165", "weight_kg": "80",
        "marker_glucose": "95", "marker_a1c": "5.2",
    }, follow_redirects=True)
    assert r.status_code == 200
    with flask_app.app_context():
        updated = db.session.get(User, user_id).manual_entries
        assert updated.weight_kg == 80, "manual entry did not persist the new weight"
        assert updated.blood_markers.get("glucose") == 95.0
    print("PASS: manual entry form saves and persists")

    # ---- the report page (no live Whoop/Oura connection — built from
    # manual entry + whatever's been imported) ----
    r = client.get("/report")
    assert r.status_code == 200, f"report page failed: {r.status_code}\n{r.data[:2000]}"
    body = r.data.decode()
    assert "Sign in" not in body
    assert "rx-warning" in body or "Also worth knowing about" in body
    print("PASS: report page renders without a live Whoop connection")

    out_path = os.path.join(os.path.dirname(__file__), "rendered_report_for_playwright.html")
    local_body = body.replace('href="/static/style.css"', 'href="style.css"')
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(local_body)
    import shutil
    shutil.copy(os.path.join(os.path.dirname(__file__), "static", "style.css"),
                os.path.join(os.path.dirname(__file__), "style.css"))
    print(f"Wrote rendered report HTML to {out_path} for a Playwright pass")

    # ---- CGM import (Lingo phone-app CSV format) ----
    lingo_csv = "Time of Glucose Reading (mm/dd/yyyy),Measurement(mg/dL)\n"
    base = datetime.now(timezone.utc)
    for i in range(200):
        ts = (base - timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M") + "-07:00"
        glucose = 90 + (i % 40)
        lingo_csv += f"{ts},{glucose}\n"
    r = client.post("/api/import/cgm", data={"file": (io.BytesIO(lingo_csv.encode()), "lingo.csv")},
                     content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    cgm_result = r.get_json()
    assert cgm_result["ok"] and cgm_result["readings_imported"] == 200, cgm_result
    print(f"PASS: CGM import parsed and saved {cgm_result['readings_imported']} readings")

    # re-importing the same file should import zero new readings (dedupe)
    r = client.post("/api/import/cgm", data={"file": (io.BytesIO(lingo_csv.encode()), "lingo.csv")},
                     content_type="multipart/form-data")
    assert r.get_json()["readings_imported"] == 0, "re-uploading the same CGM file should not create duplicates"
    print("PASS: re-importing the same CGM file is deduped")

    # ---- labs import + save (skip real PDF text extraction, test the save endpoint directly) ----
    r = client.post("/api/labs/save", json={
        "collected_date": "2026-09-01",
        "filename": "quest_test.pdf",
        "rows": [
            {"label": "Glucose", "value": 91, "unit": "mg/dL", "ref_low": 65, "ref_high": 99, "flag": None},
            {"label": "HDL Cholesterol", "value": 52, "unit": "mg/dL", "ref_low": 40, "ref_high": None, "flag": None},
        ],
    })
    assert r.status_code == 200 and r.get_json()["ok"], r.data
    print("PASS: labs save endpoint persists a reviewed panel")

    # ---- dexa import + save ----
    r = client.post("/api/dexa/save", json={
        "scan_date": "2026-08-15",
        "filename": "dexa_test.pdf",
        "rows": [
            {"label": "Total body fat %", "value": 22.4, "unit": "%"},
            {"label": "Lean mass", "value": 61.2, "unit": "kg"},
        ],
    })
    assert r.status_code == 200 and r.get_json()["ok"], r.data
    print("PASS: dexa save endpoint persists a reviewed scan")

    # ---- real PDF-text parsing sanity check (Quest-style layout regex) ----
    quest_sample_text = (
        "Patient: TEST PATIENT DOB: 01/01/1980\n"
        "CHOLESTEROL, TOTAL 172 Reference Range: <200 mg/dL\n"
        "HDL CHOLESTEROL 32 L Reference Range: > OR = 40 mg/dL\n"
        "LDL-CHOLESTEROL 137 H mg/dL (calc)\n"
        "Reference Range <100\n"
    )
    candidate_rows = quest_pdf_module.extract_candidate_rows(quest_sample_text)
    labels = [r["label"] for r in candidate_rows]
    assert "CHOLESTEROL, TOTAL" in labels and "LDL-CHOLESTEROL" in labels, candidate_rows
    print(f"PASS: quest_pdf regex extraction found {len(candidate_rows)} candidate rows from sample lab text")

    # ---- generic export-file upload (Whoop / Oura / Apple Health — saved, not parsed) ----
    r = client.post("/api/import/export-file", data={
        "kind": "whoop_export", "file": (io.BytesIO(b"fake whoop export contents"), "whoop_export.zip"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["ok"], r.data
    assert "doesn't have an automatic parser" in r.get_json()["note"]
    print("PASS: whoop export file upload saved (not parsed yet, as expected)")

    r = client.post("/api/import/export-file", data={
        "kind": "not_a_real_kind", "file": (io.BytesIO(b"x"), "x.csv"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400
    print("PASS: unknown export kind is rejected")

    # ---- report now includes glucose / imported labs / dexa sections ----
    r = client.get("/report")
    assert r.status_code == 200
    report_body = r.data.decode()
    start_marker = '<script id="report-data" type="application/json">'
    end_marker = '</script>'
    start_i = report_body.index(start_marker) + len(start_marker)
    end_i = report_body.index(end_marker, start_i)
    report_data = _json.loads(report_body[start_i:end_i])
    assert report_data["glucose"]["has_data"] is True and report_data["glucose"]["total_readings"] == 200
    assert report_data["imported_labs"]["has_data"] is True and report_data["imported_labs"]["collected_date"] == "2026-09-01"
    assert report_data["dexa"]["has_data"] is True and report_data["dexa"]["scan_date"] == "2026-08-15"
    assert report_data["recovery"]["has_data"] is False, "no live Whoop connection — recovery should have no data"
    print("PASS: report DATA now includes real glucose trend, imported labs, and DEXA sections")

    out_path2 = os.path.join(os.path.dirname(__file__), "rendered_report_full_for_playwright.html")
    local_body2 = report_body.replace('href="/static/style.css"', 'href="style.css"')
    with open(out_path2, "w", encoding="utf-8") as f:
        f.write(local_body2)
    print(f"Wrote full rendered report HTML to {out_path2}")

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    run()
