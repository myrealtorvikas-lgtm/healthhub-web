"""
Single source of truth for the blood-work markers this app understands —
same definitions and same plain-English reference ranges as the standalone
Health Snapshot artifact, ported to Python so classification happens once,
server-side, instead of being duplicated in every template's JS.
"""

MARKER_DEFS = [
    ("glucose", "Fasting glucose", "mg/dL"),
    ("a1c", "HbA1c", "%"),
    ("tc", "Total cholesterol", "mg/dL"),
    ("ldl", "LDL cholesterol", "mg/dL"),
    ("hdl", "HDL cholesterol", "mg/dL"),
    ("trig", "Triglycerides", "mg/dL"),
    ("vitd", "Vitamin D (25-OH)", "ng/mL"),
    ("tsh", "TSH", "mIU/L"),
    ("hgb", "Hemoglobin", "g/dL"),
    ("ferritin", "Ferritin", "ng/mL"),
]
MARKER_UNITS = {m[0]: m[2] for m in MARKER_DEFS}
MARKER_NAMES = {m[0]: m[1] for m in MARKER_DEFS}


def classify_marker(marker_id: str, value: float, sex: str = "") -> dict:
    """Returns {status, label, note}. status is one of good/warning/serious/critical."""
    if marker_id == "glucose":
        if value < 70:
            return {"status": "warning", "label": "Low",
                    "note": "Below the typical fasting range. If this wasn’t drawn fasting it may not mean much on its own, but a genuinely low fasting glucose is worth mentioning to a doctor."}
        if value <= 99:
            return {"status": "good", "label": "Normal", "note": "Within the standard fasting range (70–99 mg/dL)."}
        if value <= 125:
            return {"status": "warning", "label": "Prediabetes range",
                    "note": "Fasting glucose of 100–125 mg/dL is generally flagged as prediabetic — worth a repeat test and a conversation with a doctor."}
        return {"status": "critical", "label": "Diabetes range",
                "note": "126 mg/dL or higher, if confirmed on a repeat test, is in the diagnostic range for diabetes — please talk to a doctor."}

    if marker_id == "a1c":
        if value < 5.7:
            return {"status": "good", "label": "Normal", "note": "Below 5.7% is the typical non-diabetic range, reflecting average blood sugar over the last ~3 months."}
        if value <= 6.4:
            return {"status": "warning", "label": "Prediabetes range", "note": "5.7–6.4% is generally flagged as prediabetic — worth discussing with a doctor."}
        return {"status": "critical", "label": "Diabetes range", "note": "6.5% or higher, if confirmed, is in the diagnostic range for diabetes — please talk to a doctor."}

    if marker_id == "tc":
        if value < 200:
            return {"status": "good", "label": "Desirable", "note": "Under 200 mg/dL is the generally desirable range."}
        if value <= 239:
            return {"status": "warning", "label": "Borderline high", "note": "200–239 mg/dL is borderline — the LDL/HDL breakdown matters more than this total number alone."}
        return {"status": "serious", "label": "High", "note": "240 mg/dL or above is flagged as high — worth a full lipid panel discussion with a doctor."}

    if marker_id == "ldl":
        if value < 130:
            return {"status": "good", "label": "Optimal" if value < 100 else "Near optimal",
                    "note": "Under 100 mg/dL is optimal; 100–129 is near optimal for most people without other risk factors."}
        if value <= 159:
            return {"status": "warning", "label": "Borderline high", "note": "130–159 mg/dL is borderline high — worth watching alongside diet and activity."}
        if value <= 189:
            return {"status": "serious", "label": "High", "note": "160–189 mg/dL is flagged as high — worth a doctor’s read on overall cardiovascular risk."}
        return {"status": "critical", "label": "Very high", "note": "190 mg/dL or above is flagged as very high — please discuss with a doctor."}

    if marker_id == "hdl":
        if value < 40:
            return {"status": "warning", "label": "Low", "note": "HDL below 40 mg/dL is linked to higher cardiovascular risk — higher is generally better for this one."}
        if value < 60:
            return {"status": "good", "label": "Acceptable", "note": "40–59 mg/dL is an acceptable range."}
        return {"status": "good", "label": "Protective", "note": "60 mg/dL or above is associated with lower cardiovascular risk."}

    if marker_id == "trig":
        if value < 150:
            return {"status": "good", "label": "Normal", "note": "Under 150 mg/dL is the normal range (ideally measured fasting)."}
        if value <= 199:
            return {"status": "warning", "label": "Borderline high", "note": "150–199 mg/dL is borderline high."}
        if value <= 499:
            return {"status": "serious", "label": "High", "note": "200–499 mg/dL is flagged as high — worth discussing with a doctor, especially alongside LDL and HDL."}
        return {"status": "critical", "label": "Very high", "note": "500 mg/dL or above raises pancreatitis risk — please talk to a doctor promptly."}

    if marker_id == "vitd":
        if value < 20:
            return {"status": "serious", "label": "Deficient", "note": "Under 20 ng/mL is generally considered deficient — worth discussing supplementation with a doctor."}
        if value < 30:
            return {"status": "warning", "label": "Insufficient", "note": "20–29 ng/mL is considered insufficient by most labs."}
        if value <= 100:
            return {"status": "good", "label": "Sufficient", "note": "30–100 ng/mL is the typical sufficient range."}
        return {"status": "warning", "label": "Higher than typical", "note": "Above 100 ng/mL is unusually high — worth a recheck, since high-dose supplementation can occasionally push this too far."}

    if marker_id == "tsh":
        if value < 0.4:
            return {"status": "warning", "label": "Low", "note": "Below 0.4 mIU/L can suggest an overactive thyroid — worth discussing with a doctor."}
        if value <= 4.0:
            return {"status": "good", "label": "Normal", "note": "The typical lab reference range is about 0.4–4.0 mIU/L."}
        if value <= 10:
            return {"status": "warning", "label": "High", "note": "Above 4.0 mIU/L can suggest an underactive thyroid — worth discussing with a doctor."}
        return {"status": "serious", "label": "High", "note": "Well above the typical range — worth a prompt conversation with a doctor."}

    if marker_id == "hgb":
        lo, hi, note = 12.0, 17.5, "Ranges differ by sex — add yours in your profile for a tighter comparison."
        if sex == "female":
            lo, hi, note = 12.0, 15.5, "Typical adult female range is about 12.0–15.5 g/dL."
        elif sex == "male":
            lo, hi, note = 13.5, 17.5, "Typical adult male range is about 13.5–17.5 g/dL."
        if value < lo:
            return {"status": "warning", "label": "Low", "note": "Below the typical range — can reflect anemia among other things. " + note}
        if value > hi:
            return {"status": "warning", "label": "High", "note": "Above the typical range. " + note}
        return {"status": "good", "label": "Normal", "note": note}

    if marker_id == "ferritin":
        if value < 15:
            return {"status": "serious", "label": "Low", "note": "Under 15 ng/mL often reflects low iron stores — worth discussing with a doctor."}
        if value < 30:
            return {"status": "warning", "label": "Low-normal", "note": "15–29 ng/mL is low-normal — worth watching, especially if you feel fatigued."}
        if value <= 300:
            return {"status": "good", "label": "Normal range", "note": "Ferritin ranges vary a lot by lab and sex — this sits in a commonly used adult range."}
        return {"status": "warning", "label": "High", "note": "Above 300 ng/mL can reflect inflammation or iron overload — worth a doctor’s read, especially alongside iron/transferrin saturation."}

    return {"status": "neutral", "label": "", "note": ""}


def classify_bmi(bmi: float) -> dict:
    if bmi < 18.5:
        return {"status": "warning", "label": "Underweight", "note": "By this rough measure — BMI doesn’t account for muscle vs. fat, so read it loosely."}
    if bmi < 25:
        return {"status": "good", "label": "In typical range", "note": "By this rough measure — BMI doesn’t distinguish muscle from fat, so treat it as a starting point, not a verdict."}
    if bmi < 30:
        return {"status": "warning", "label": "Above typical range", "note": "By this rough measure. A body-composition scan (like DEXA) gives a much fuller picture than BMI alone."}
    return {"status": "serious", "label": "Well above typical range", "note": "By this rough measure — worth a fuller conversation with a doctor rather than BMI alone."}
