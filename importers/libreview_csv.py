"""
Import glucose data from a CGM CSV export. Handles two different formats
that both end up called "the LibreView export" in conversation:

1. The Lingo phone app's own export ("Time of Glucose Reading [...],
   Measurement(mg/dL)") — two columns, one reading per row, ISO timestamps
   with an embedded UTC offset like "2026-09-21T15:49-07:00". This is what
   you get by exporting straight from the Lingo app on your phone. No
   meal/insulin/note data in this format — just glucose readings.

2. The libreview.com web portal's "Download Report" export ("Device
   Timestamp", "Record Type", ...) — the fuller clinical export, which
   also carries food/insulin/note events if you log those in the app.
   Has a variable number of banner rows before the real header, so we
   scan for it rather than assuming row 2.

Either file can be uploaded here — the parser detects which one it is.
"""
import csv
import io
from datetime import datetime

HEADER_MARKER = "Device Timestamp"
LINGO_APP_MARKER = "Time of Glucose Reading"

# Record Type values used by LibreView exports.
RECORD_TYPE_HISTORIC = "0"   # automatic sensor reading
RECORD_TYPE_SCAN = "1"       # user-initiated scan
RECORD_TYPE_INSULIN = "2"
RECORD_TYPE_FOOD = "5"
RECORD_TYPE_NOTE = "6"


def _parse_timestamp(raw):
    raw = raw.strip()
    for fmt in ("%m-%d-%Y %I:%M %p", "%d-%m-%Y %I:%M %p", "%m/%d/%Y %I:%M %p",
                "%m-%d-%Y %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_lingo_app_timestamp(raw):
    """Handles the Lingo app's own export format:
    "2026-09-21T15:49-07:00" (ISO 8601, no seconds, offset attached)."""
    raw = (raw or "").strip()
    try:
        return datetime.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _parse_lingo_app_export(lines, header_idx):
    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    next(reader, None)  # header row
    readings = []
    skipped = 0
    for row in reader:
        if len(row) < 2:
            if row:
                skipped += 1
            continue
        ts = _parse_lingo_app_timestamp(row[0])
        glucose = _to_float(row[1])
        if ts is None or glucose is None:
            skipped += 1
            continue
        readings.append({"timestamp": ts, "glucose_mgdl": glucose, "record_type": "historic"})
    return {"readings": readings, "events": [], "skipped": skipped}


def parse(file_bytes):
    """Returns {"readings": [...], "events": [...], "skipped": int}"""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Check for the Lingo phone app's simpler export format first.
    for i, line in enumerate(lines[:5]):
        if LINGO_APP_MARKER in line:
            return _parse_lingo_app_export(lines, i)

    header_idx = None
    for i, line in enumerate(lines):
        if HEADER_MARKER in line:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            "This doesn't look like a CGM export I recognize — couldn't find "
            "a 'Time of Glucose Reading' or 'Device Timestamp' column. Make "
            "sure you exported straight from the Lingo app, or downloaded "
            "the CSV report from libreview.com."
        )

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    readings = []
    events = []
    skipped = 0

    for row in reader:
        ts_raw = row.get("Device Timestamp", "")
        ts = _parse_timestamp(ts_raw)
        if not ts:
            skipped += 1
            continue
        record_type = (row.get("Record Type") or "").strip()

        historic = _to_float(row.get("Historic Glucose mg/dL"))
        scan = _to_float(row.get("Scan Glucose mg/dL"))
        strip = _to_float(row.get("Strip Glucose mg/dL"))
        glucose = historic if historic is not None else (scan if scan is not None else strip)

        if glucose is not None:
            readings.append({
                "timestamp": ts,
                "glucose_mgdl": glucose,
                "record_type": "scan" if record_type == RECORD_TYPE_SCAN else "historic",
            })

        carbs = _to_float(row.get("Carbohydrates (grams)"))
        food_note = (row.get("Non-numeric Food") or "").strip()
        if carbs is not None or food_note:
            events.append({
                "timestamp": ts,
                "event_type": "meal",
                "description": food_note or "Food logged",
                "carbs_g": carbs,
                "insulin_units": None,
            })

        rapid_units = _to_float(row.get("Rapid-Acting Insulin (units)"))
        long_units = _to_float(row.get("Long-Acting Insulin (units)"))
        if rapid_units is not None or long_units is not None:
            events.append({
                "timestamp": ts,
                "event_type": "insulin",
                "description": "Rapid-acting" if rapid_units is not None else "Long-acting",
                "carbs_g": None,
                "insulin_units": rapid_units if rapid_units is not None else long_units,
            })

        notes = (row.get("Notes") or "").strip()
        if notes:
            events.append({
                "timestamp": ts,
                "event_type": "note",
                "description": notes,
                "carbs_g": None,
                "insulin_units": None,
            })

    return {"readings": readings, "events": events, "skipped": skipped}
