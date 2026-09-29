"""
Shared PDF text extraction + a generic "label ... number ... unit" line
parser used by both the Quest labs importer and the DEXA importer.

Lab and DEXA reports vary a lot between providers, so rather than hard-code
one provider's exact layout, this pulls every line that looks like
"Some Label   123.4   unit   (ref range)" and lets the review screen in the
app show them all for a human to confirm/edit/delete before saving. That
review step is the safety net for real health data with no API to validate
values against.
"""
import re

try:
    import pdfplumber
    HAVE_PDFPLUMBER = True
except ImportError:
    HAVE_PDFPLUMBER = False


def extract_text(file_bytes):
    if not HAVE_PDFPLUMBER:
        raise RuntimeError(
            "pdfplumber isn't installed. Run: pip install pdfplumber --break-system-packages"
        )
    import io
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


# Matches lines like:
#   Glucose                 95        mg/dL      65-99
#   Total Cholesterol       185 mg/dL             <200
#   HDL Cholesterol          52       mg/dL        >40          L
#   Vitamin D, 25-Hydroxy    38.2     ng/mL       30.0-100.0
LINE_PATTERN = re.compile(
    r"""^
    (?P<label>[A-Za-z][A-Za-z0-9\s,\/\-\(\)%\.]{2,60}?)      # label
    \s{1,}
    (?P<value>-?\d+\.?\d*)                                    # numeric value
    \s*
    (?P<unit>%|mg/dL|g/dL|ng/mL|pg/mL|mIU/L|IU/L|mmol/L|
       mEq/L|U/L|K/uL|M/uL|fL|pg|umol/L|mL/min/1\.73|ratio|
       x10E3/uL|x10E6/uL)?
    \s*
    (?P<range>[\d\.]+\s*-\s*[\d\.]+|[<>]\s*[\d\.]+)?          # optional reference range
    \s*
    (?P<flag>\bHigh\b|\bLow\b|\bH\b|\bL\b|\bAbnormal\b)?      # optional flag
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Lines that are clearly headers/footers/noise, skip these
SKIP_PATTERNS = re.compile(
    r"(page \d+|specimen|patient|dob|date of birth|fasting|physician|"
    r"lab director|collected|reported|report status|account|phone|fax)",
    re.IGNORECASE,
)


def extract_candidate_rows(text):
    """Returns a list of {label, value, unit, ref_low, ref_high, flag, raw_line}
    for every line in the PDF text that looks like a lab/measurement row.
    This is intentionally generous — the review UI is where a human filters
    out anything that isn't actually a useful value."""
    rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 4:
            continue
        if SKIP_PATTERNS.search(line):
            continue
        m = LINE_PATTERN.match(line)
        if not m:
            continue
        label = m.group("label").strip(" .:-")
        if len(label) < 2:
            continue
        value = m.group("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        unit = (m.group("unit") or "").strip()
        ref_low, ref_high = None, None
        rng = m.group("range")
        if rng:
            rng = rng.strip()
            if "-" in rng and not rng.startswith("<") and not rng.startswith(">"):
                parts = rng.split("-")
                try:
                    ref_low = float(parts[0].strip())
                    ref_high = float(parts[1].strip())
                except (ValueError, IndexError):
                    pass
            elif rng.startswith("<"):
                ref_high = float(rng[1:].strip()) if rng[1:].strip().replace(".", "", 1).isdigit() else None
            elif rng.startswith(">"):
                ref_low = float(rng[1:].strip()) if rng[1:].strip().replace(".", "", 1).isdigit() else None
        flag = (m.group("flag") or "").strip() or None
        rows.append({
            "label": label,
            "value": value,
            "unit": unit or None,
            "ref_low": ref_low,
            "ref_high": ref_high,
            "flag": flag,
            "raw_line": line,
        })
    return rows
