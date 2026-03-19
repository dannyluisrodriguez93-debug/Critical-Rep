"""
PDF parser for Tableau revenue target attachments ("Sales vs Target.pdf").
Extracts MTD/QTD/YTD actuals, targets, and % of target using pdfplumber.
"""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)


def _parse_currency(s: str) -> float:
    if not s:
        return 0.0
    return float(re.sub(r"[^\d.]", "", s) or "0")


def _parse_pct(s: str) -> float:
    if not s:
        return 0.0
    return float(re.sub(r"[^\d.]", "", s) or "0")


def parse_revenue_pdf(pdf_path: str) -> dict:
    """
    Parse a Tableau 'Sales vs Target' PDF.
    Returns dict with month/quarter/year breakdown or empty dict on failure.
    """
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber not installed — run: pip install pdfplumber")
        return {}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        log.error("Failed to open PDF %s: %s", pdf_path, e)
        return {}

    result = {}
    for period in ("MONTH", "QUARTER", "YEAR"):
        # Look for patterns like "Actuals $142,859" near period heading
        section_pattern = re.compile(
            rf"{period}.*?Actuals\s+([\$\d,]+).*?"
            rf"RR Actuals\s+([\$\d,]+).*?"
            rf"Target\s+([\$\d,]+).*?"
            rf"(?:RR )?% of Target\s+([\d.]+)%.*?"
            rf"PY revenue\s+([\$\d,]+)",
            re.DOTALL | re.IGNORECASE,
        )
        m = section_pattern.search(text)
        if m:
            result[period.lower()] = {
                "actual":        _parse_currency(m.group(1)),
                "rr_actual":     _parse_currency(m.group(2)),
                "target":        _parse_currency(m.group(3)),
                "pct_of_target": _parse_pct(m.group(4)),
                "py_revenue":    _parse_currency(m.group(5)),
            }

    if not result:
        log.warning("Could not extract revenue targets from PDF — check format")

    return result


def parse_pdf_bytes(pdf_bytes: bytes) -> dict:
    """Parse PDF from raw bytes (e.g. from email attachment)."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = f.name
    try:
        return parse_revenue_pdf(tmp_path)
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    import sys, json
    logging.basicConfig(level=logging.INFO)
    path = sys.argv[1] if len(sys.argv) > 1 else "Sales vs Target.pdf"
    data = parse_revenue_pdf(path)
    print(json.dumps(data, indent=2))
