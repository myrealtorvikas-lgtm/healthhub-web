"""
Turns raw Whoop API records into the same shape of trend series (series +
recent_avg + recent_n + delta, computed as a 30-night average vs. the 30
nights before that) used by the existing personal report's charts — so the
same range-toggle / stat-strip JS patterns can be reused as-is on this page.

V1 scope, deliberately: recovery, HRV, sleep, and strain/workouts, because
those are what Whoop's API actually hands back. Steps, body weight, CGM,
Quest blood work, and DEXA are NOT in this file on purpose — Whoop doesn't
provide them, and building parsers for those file formats blind (without a
real sample file from Vikas) would likely be wrong. Blood work / body basics
instead come from the same manual-entry fields as the standalone Health
Snapshot artifact (see ManualEntry in models.py) and get merged in
separately by app.py.
"""
from datetime import datetime, timedelta, timezone
from markers import classify_marker, classify_bmi, MARKER_NAMES, MARKER_UNITS


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _split_recent_prior(series, key, n=30):
    recent = series[-n:]
    prior = series[-(2 * n):-n]
    recent_avg = _avg([p[key] for p in recent])
    delta = None
    if prior and recent_avg is not None:
        prior_avg = _avg([p[key] for p in prior])
        if prior_avg is not None:
            delta = round(recent_avg - prior_avg, 1)
    return recent_avg, len(recent), delta


def build_recovery_and_hrv(recoveries: list):
    """recoveries: raw Whoop /v2/recovery records, oldest-first is not
    guaranteed by the API, so we sort here."""
    rows = []
    for r in recoveries:
        score = r.get("score") or {}
        if score.get("recovery_score") is None:
            continue
        rows.append({
            "date": (r.get("created_at") or "")[:10],
            "recovery": score.get("recovery_score"),
            "hrv": round(score["hrv_rmssd_milli"], 1) if score.get("hrv_rmssd_milli") is not None else None,
            "rhr": score.get("resting_heart_rate"),
        })
    rows.sort(key=lambda r: r["date"])

    if not rows:
        return {"has_data": False}, {"has_data": False}

    recovery_series = [{"date": r["date"], "recovery": r["recovery"]} for r in rows if r["recovery"] is not None]
    hrv_series = [{"date": r["date"], "hrv": r["hrv"]} for r in rows if r["hrv"] is not None]

    rec_avg, rec_n, rec_delta = _split_recent_prior(recovery_series, "recovery")
    hrv_avg, hrv_n, hrv_delta = _split_recent_prior(hrv_series, "hrv")

    recovery_trend = {"has_data": bool(recovery_series), "series": recovery_series,
                       "recent_avg": rec_avg, "recent_n": rec_n, "delta": rec_delta}
    hrv_trend = {"has_data": bool(hrv_series), "series": hrv_series,
                 "recent_avg": hrv_avg, "recent_n": hrv_n, "delta": hrv_delta}
    return recovery_trend, hrv_trend


def build_sleep_trend(sleeps: list):
    rows = []
    for s in sleeps:
        if s.get("nap"):
            continue  # naps would skew a nightly-average trend
        score = s.get("score") or {}
        stage = score.get("stage_summary") or {}
        needed = score.get("sleep_needed") or {}
        if score.get("sleep_performance_percentage") is None:
            continue
        rows.append({
            "date": (s.get("start") or "")[:10],
            "perf": score.get("sleep_performance_percentage"),
            "resp": score.get("respiratory_rate"),
            "consistency": score.get("sleep_consistency_percentage"),
            "efficiency": score.get("sleep_efficiency_percentage"),
            "debt_ms": needed.get("need_from_sleep_debt_milli"),
            "rem_ms": stage.get("total_rem_sleep_time_milli"),
            "sws_ms": stage.get("total_slow_wave_sleep_time_milli"),
            "light_ms": stage.get("total_light_sleep_time_milli"),
            "awake_ms": stage.get("total_awake_time_milli"),
        })
    rows.sort(key=lambda r: r["date"])

    if not rows:
        return {"has_data": False}

    recent_rows = rows[-30:]
    prior_rows = rows[-60:-30]

    recent_avg_perf = _avg([r["perf"] for r in recent_rows])
    prior_avg_perf = _avg([r["perf"] for r in prior_rows]) if prior_rows else None
    delta = round(recent_avg_perf - prior_avg_perf, 1) if (recent_avg_perf is not None and prior_avg_perf is not None) else None

    stage_rows = [r for r in rows[-90:] if r["light_ms"] is not None]

    def avg_min(key):
        vals = [r[key] for r in stage_rows if r.get(key) is not None]
        return round(sum(vals) / len(vals) / 60000) if vals else 0

    stages = None
    if stage_rows:
        stages = {"rem": avg_min("rem_ms"), "sws": avg_min("sws_ms"),
                  "light": avg_min("light_ms"), "awake": avg_min("awake_ms")}

    debt_vals = [r["debt_ms"] for r in recent_rows if r.get("debt_ms") is not None]
    avg_debt_hrs = round(sum(debt_vals) / len(debt_vals) / 3600000, 1) if debt_vals else None

    return {
        "has_data": True,
        "series": rows,
        "recent_avg": recent_avg_perf,
        "recent_n": len(recent_rows),
        "delta": delta,
        "respiratory_rate": _avg([r["resp"] for r in recent_rows]),
        "consistency": _avg([r["consistency"] for r in recent_rows]),
        "efficiency": _avg([r["efficiency"] for r in recent_rows]),
        "avg_debt_hrs": avg_debt_hrs,
        "stages": stages,
    }


def build_strain_and_workouts(cycles: list, workouts: list):
    strain_rows = []
    for c in cycles:
        score = c.get("score") or {}
        if score.get("strain") is None:
            continue
        strain_rows.append({
            "date": (c.get("start") or "")[:10],
            "strain": round(score["strain"], 1),
            "avg_hr": score.get("average_heart_rate"),
            "kilojoule": score.get("kilojoule"),
        })
    strain_rows.sort(key=lambda r: r["date"])
    strain_avg, strain_n, strain_delta = _split_recent_prior(strain_rows, "strain") if strain_rows else (None, 0, None)
    strain_trend = {"has_data": bool(strain_rows), "series": strain_rows,
                     "recent_avg": strain_avg, "recent_n": strain_n, "delta": strain_delta}

    recent_workouts = []
    zone_totals = {"zone_zero_milli": 0, "zone_one_milli": 0, "zone_two_milli": 0,
                    "zone_three_milli": 0, "zone_four_milli": 0, "zone_five_milli": 0}
    for w in sorted(workouts, key=lambda w: w.get("start") or "", reverse=True)[:20]:
        score = w.get("score") or {}
        zones = score.get("zone_durations") or {}
        for k in zone_totals:
            if zones.get(k):
                zone_totals[k] += zones[k]
        recent_workouts.append({
            "date": (w.get("start") or "")[:10],
            "sport": w.get("sport_name", "Workout"),
            "strain": round(score["strain"], 1) if score.get("strain") is not None else None,
            "avg_hr": score.get("average_heart_rate"),
            "minutes": round(_duration_ms(w) / 60000) if _duration_ms(w) else None,
        })

    workouts_out = {
        "has_data": bool(recent_workouts),
        "recent": recent_workouts,
        "zone_minutes": {k.replace("_milli", ""): round(v / 60000) for k, v in zone_totals.items()},
    }
    return strain_trend, workouts_out


def _duration_ms(record):
    try:
        start = datetime.fromisoformat(record["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(record["end"].replace("Z", "+00:00"))
        return (end - start).total_seconds() * 1000
    except Exception:
        return None


def build_glucose_trend(cgm_readings: list, window_days=90):
    """cgm_readings: CgmReading rows (or anything with .timestamp/.glucose_mgdl).
    Collapses the dense raw readings (every ~15 min) down to one avg-per-day
    point, same shape as the recovery/HRV/sleep series, so the exact same
    range-toggle chart component on the report page can draw it unchanged."""
    if not cgm_readings:
        return {"has_data": False}

    by_date = {}
    in_range = 0
    total = 0
    for r in cgm_readings:
        date = r.timestamp[:10]
        by_date.setdefault(date, []).append(r.glucose_mgdl)
        total += 1
        if 70 <= r.glucose_mgdl <= 180:
            in_range += 1

    series = [{"date": d, "glucose": round(sum(vals) / len(vals), 1)} for d, vals in sorted(by_date.items())]
    avg, n, delta = _split_recent_prior(series, "glucose")
    time_in_range_pct = round(100 * in_range / total, 1) if total else None

    return {"has_data": True, "series": series, "recent_avg": avg, "recent_n": n,
            "delta": delta, "time_in_range_pct": time_in_range_pct, "total_readings": total}


def build_report_data(whoop_client=None, manual_entry=None, first_name=None, window_days=90,
                       cgm_readings=None, latest_lab_panel=None, latest_dexa_scan=None):
    """The single entry point app.py calls: returns the full DATA dict the
    report template consumes.

    whoop_client is optional — this app no longer keeps a live Whoop
    connection (accounts are plain email/password, and Whoop/Oura data comes
    in as a manually-uploaded export like everything else). It's still
    accepted here, unused for now, so a future importer that DOES produce a
    whoop_client-shaped object (recoveries()/sleeps()/cycles()/workouts())
    from a parsed export file can plug in without changing this function's
    shape again."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    if whoop_client is not None:
        recoveries = whoop_client.recoveries(start_iso, end_iso)
        sleeps = whoop_client.sleeps(start_iso, end_iso)
        cycles = whoop_client.cycles(start_iso, end_iso)
        workouts = whoop_client.workouts(start_iso, end_iso)
    else:
        recoveries, sleeps, cycles, workouts = [], [], [], []

    recovery_trend, hrv_trend = build_recovery_and_hrv(recoveries)
    sleep_trend = build_sleep_trend(sleeps)
    strain_trend, workouts_out = build_strain_and_workouts(cycles, workouts)

    watch = []
    body = {"has_data": False}
    if manual_entry:
        sex = manual_entry.sex or ""
        if manual_entry.height_cm and manual_entry.weight_kg:
            bmi = manual_entry.weight_kg / ((manual_entry.height_cm / 100) ** 2)
            bmi = round(bmi, 1)
            body = {"has_data": True, "height_cm": manual_entry.height_cm,
                    "weight_kg": manual_entry.weight_kg, "bmi": bmi,
                    **classify_bmi(bmi)}
        if manual_entry.blood_markers:
            for marker_id, value in manual_entry.blood_markers.items():
                if value in (None, "") or marker_id not in MARKER_NAMES:
                    continue
                classified = classify_marker(marker_id, float(value), sex=sex)
                watch.append({
                    "id": marker_id,
                    "name": MARKER_NAMES[marker_id],
                    "unit": MARKER_UNITS[marker_id],
                    "value": value,
                    **classified,
                })

    glucose_trend = build_glucose_trend(cgm_readings or [], window_days=window_days)

    imported_labs = {"has_data": False}
    if latest_lab_panel is not None:
        imported_labs = {
            "has_data": True,
            "collected_date": latest_lab_panel.collected_date,
            "results": [{"analyte": r.analyte, "value": r.value, "value_text": r.value_text,
                         "unit": r.unit, "ref_low": r.ref_low, "ref_high": r.ref_high, "flag": r.flag}
                        for r in latest_lab_panel.results],
        }

    dexa = {"has_data": False}
    if latest_dexa_scan is not None:
        dexa = {
            "has_data": True,
            "scan_date": latest_dexa_scan.scan_date,
            "results": [{"metric": r.metric, "value": r.value, "unit": r.unit}
                        for r in latest_dexa_scan.results],
        }

    return {
        "generated_at": end.isoformat(),
        "first_name": first_name,
        "window_days": window_days,
        "recovery": recovery_trend,
        "hrv": hrv_trend,
        "sleep": sleep_trend,
        "strain": strain_trend,
        "workouts": workouts_out,
        "body": body,
        "watch": watch,
        "glucose": glucose_trend,
        "imported_labs": imported_labs,
        "dexa": dexa,
        # Not available in V1 — Whoop doesn't provide steps, and there's no
        # Apple Health parser yet (see models.py's UploadedFile note).
        "steps": {"has_data": False, "reason": "not_available_v1"},
    }
