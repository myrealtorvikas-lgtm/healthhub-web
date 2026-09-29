"""
Quest Diagnostics blood-panel PDF import.

Tuned against real Quest report text (the standard "ANALYTE  VALUE  [FLAG]
Reference Range: <range> <unit>" layout Quest actually uses, including the
variant where the unit sits on the value's own line and the reference
range follows on the next line). Every extracted row still goes through a
manual review screen before saving — this parser is generous on purpose
and lets a human filter it, rather than trying to be perfect.
"""
import re
from . import pdf_common

extract_text = pdf_common.extract_text

# Lines to ignore outright — demographic header, page footers, section
# labels, boilerplate.
NOISE_PATTERNS = re.compile(
    r"^(DOB:|Sex:|Phone:|Patient ID:|PATIENT MUST BE FASTING|FASTING:|"
    r"Analyte\s+Value$|Performing Sites|Key$|Priority Out of Range|"
    r"These results have been sent|Quest, Quest Diagnostics|"
    r"third party marks|COMMENT$|Note \d|For (additional|someone|ages)|"
    r".*\(\d+\s*/\s*\d+\)\s*\d{1,2}/\d{1,2}/\d{2}$|"  # "NAME (SPECIMEN) 1 / 7 9/10/25" footer
    r"^[A-Z ,]+\(TM\)|^\(Note\)|^MDF$|^med fusion$)",
    re.IGNORECASE,
)

UNIT_TOKEN = (
    r"mg/dL|mg/L|g/dL|ng/mL|pg/mL|mIU/L|mIU/mL|IU/L|mmol/L|mEq/L|U/L|K/uL|M/uL|"
    r"fL|pg|umol/L|ng/dL|nmol/L|cells/uL|Thousand/uL|Million/uL|mcg/dL|"
    r"mL/min/1\.73m2|SD|%"
)

LABEL = r"(?P<label>[A-Za-z][A-Za-z0-9 ,/\-\.\(\)]{1,60}?)"
VALUE = r"(?P<value>-?\d+\.?\d*|SEE NOTE:)"
FLAG = r"(?P<flag>H|L)?"

# "CHOLESTEROL, TOTAL 172 Reference Range: <200 mg/dL"
# "HDL CHOLESTEROL 32 L Reference Range: > OR = 40 mg/dL"
PATTERN_INLINE_RANGE = re.compile(
    rf"^{LABEL}\s+{VALUE}\s*{FLAG}\s*Reference [Rr]ange:?\s*(?P<range>.+)$"
)

# "LDL-CHOLESTEROL 137 H mg/dL (calc)"  /  "NEUTROPHILS 43.2 %"
PATTERN_VALUE_UNIT = re.compile(
    rf"^{LABEL}\s+{VALUE}\s*{FLAG}\s*(?P<unit>{UNIT_TOKEN})\s*(\(calc\))?$"
)

# A following line like "Reference range: <100" or "Reference Range <90"
PATTERN_NEXT_LINE_RANGE = re.compile(r"^Reference [Rr]ange:?\s*(?P<range>.+)$")

RANGE_LOW_HIGH = re.compile(r"^(?P<low>\d+\.?\d*)\s*-\s*(?P<high>\d+\.?\d*)")
RANGE_LESS_THAN = re.compile(r"^[<]\s*(?:or\s*=\s*)?(?P<high>\d+\.?\d*)", re.IGNORECASE)
RANGE_GREATER_THAN = re.compile(r"^[>]\s*(?:OR\s*=\s*)?(?P<low>\d+\.?\d*)", re.IGNORECASE)
UNIT_IN_RANGE = re.compile(rf"({UNIT_TOKEN})")


def _parse_range(range_str):
    """Pulls (ref_low, ref_high, unit) out of a range expression like
    '65-99 mg/dL', '<200 mg/dL', '> OR = 40 mg/dL', '<5.0 (calc)'."""
    range_str = range_str.strip()
    ref_low, ref_high = None, None
    m = RANGE_LOW_HIGH.match(range_str)
    if m:
        ref_low, ref_high = float(m.group("low")), float(m.group("high"))
    else:
        m = RANGE_LESS_THAN.match(range_str)
        if m:
            ref_high = float(m.group("high"))
        else:
            m = RANGE_GREATER_THAN.match(range_str)
            if m:
                ref_low = float(m.group("low"))
    unit_m = UNIT_IN_RANGE.search(range_str)
    unit = unit_m.group(1) if unit_m else None
    return ref_low, ref_high, unit


def extract_candidate_rows(text):
    lines = [l.strip() for l in text.splitlines()]
    rows = []
    seen_pages_header = False
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line or len(line) < 4:
            continue
        if NOISE_PATTERNS.search(line):
            continue

        m = PATTERN_INLINE_RANGE.match(line)
        if m:
            label = m.group("label").strip(" .:-")
            raw_value = m.group("value")
            ref_low, ref_high, unit = _parse_range(m.group("range"))
            value, value_text = (None, raw_value.rstrip(":")) if raw_value.upper().startswith("SEE") else (float(raw_value), None)
            rows.append({
                "label": label, "value": value, "value_text": value_text,
                "unit": unit, "ref_low": ref_low, "ref_high": ref_high,
                "flag": m.group("flag"), "raw_line": line,
            })
            continue

        m = PATTERN_VALUE_UNIT.match(line)
        if m:
            label = m.group("label").strip(" .:-")
            value = float(m.group("value"))
            unit = m.group("unit")
            ref_low, ref_high = None, None
            # Peek at the next non-empty line for a reference range.
            if i < len(lines):
                next_line = lines[i].strip()
                nm = PATTERN_NEXT_LINE_RANGE.match(next_line)
                if nm:
                    ref_low, ref_high, range_unit = _parse_range(nm.group("range"))
                    unit = unit or range_unit
                    i += 1  # consume the range line
            rows.append({
                "label": label, "value": value, "value_text": None,
                "unit": unit, "ref_low": ref_low, "ref_high": ref_high,
                "flag": m.group("flag"), "raw_line": line,
            })
            continue

    return rows


def parse(file_bytes):
    text = extract_text(file_bytes)
    rows = extract_candidate_rows(text)
    return {"rows": rows, "raw_text": text}
