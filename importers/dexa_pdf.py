"""
DEXA scan PDF import. Same generic row-extraction as Quest labs (see
pdf_common.py), since DEXA report layouts vary a lot by scanner/clinic
(Hologic, GE Lunar, Bod Pod, etc.) and we don't have a sample yet to tune
against. Common DEXA metrics are flagged as "known" when recognized, purely
to make the review screen easier to scan — everything still goes through
manual review before saving.
"""
from . import pdf_common

KNOWN_METRICS = [
    "total body fat", "body fat %", "fat mass", "lean mass", "lean body mass",
    "bone mineral density", "bmd", "total mass", "android/gynoid",
    "android fat", "gynoid fat", "visceral adipose", "vat mass", "vat volume",
    "t-score", "z-score", "arms lean", "legs lean", "trunk lean",
    "arms fat", "legs fat", "trunk fat", "bone mineral content", "bmc",
]


def _is_known(label):
    low = label.lower()
    return any(k in low for k in KNOWN_METRICS)


def parse(file_bytes):
    text = pdf_common.extract_text(file_bytes)
    rows = pdf_common.extract_candidate_rows(text)
    for row in rows:
        row["known_metric"] = _is_known(row["label"])
    # Known DEXA metrics first, so the review screen surfaces the
    # important ones before the long tail of noise.
    rows.sort(key=lambda r: not r["known_metric"])
    return {"rows": rows, "raw_text": text}
