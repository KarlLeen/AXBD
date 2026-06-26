"""Export leads to the AthenaX "project list" spreadsheet format (17 columns).

Matches the columns/format of the reference workbook so the output can be
imported straight into Google Sheets. Array fields are flattened the same way
the reference sheet does:
  • backers / other links : "A ; B ; C"
  • team                  : "Name | Title | bio | linkedin | twitter" per member, members joined by " ; "
  • voices                : "source | summary | url" per item
  • bounties              : "title | description | reward | url" per item
The Scout's "not found" placeholder (and nulls) become blank cells.
"""
import json
from io import BytesIO

HEADERS = [
    "name", "category", "subcategory", "short_desc", "description", "stage",
    "founded", "backers", "twitter", "website", "discord", "docs", "github",
    "other link", "team", "voices", "bounties",
]


def _clean(v) -> str:
    """Scalar -> trimmed string; None / "not found" -> ""."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "not found" else s


def _arr(v) -> list:
    """Coerce a DB JSON-string or value into a list."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return []
    return v if isinstance(v, list) else []


def _join_simple(v) -> str:
    return " ; ".join(p for p in (_clean(x) for x in _arr(v)) if p)


def _join_objects(v, keys) -> str:
    out = []
    for item in _arr(v):
        if not isinstance(item, dict):
            continue
        parts = [p for p in (_clean(item.get(k)) for k in keys) if p]
        if parts:
            out.append(" | ".join(parts))
    return " ; ".join(out)


def lead_to_row(d: dict) -> list:
    """Flatten one lead dict (DB row or /api/leads shape) into the 17 columns."""
    return [
        _clean(d.get("name")),
        _clean(d.get("sector") or d.get("category")),   # DB stores category in `sector`
        _clean(d.get("subcategory")),
        _clean(d.get("short_description")),
        _clean(d.get("description")),
        _clean(d.get("stage")),
        _clean(d.get("founded")),
        _join_simple(d.get("backers")),
        _clean(d.get("twitter_url")),
        _clean(d.get("website") or d.get("url")),
        _clean(d.get("discord_url")),
        _clean(d.get("docs_url")),
        _clean(d.get("github_url")),
        _join_simple(d.get("other_links")),
        _join_objects(d.get("team"),     ("name", "title", "bio", "linkedin", "twitter")),
        _join_objects(d.get("voices"),   ("source", "summary", "url")),
        _join_objects(d.get("bounties"), ("title", "description", "reward", "url")),
    ]


def build_xlsx(leads: list[dict]) -> bytes:
    """Build an .xlsx workbook (single 'Sheet1', header + one row per lead)."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEADERS)
    for d in leads:
        ws.append(lead_to_row(d))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
