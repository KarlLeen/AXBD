"""Lead filtering — exclude Nouns DAO's own/affiliated projects."""
import json
from pathlib import Path

_EXCLUSIONS_PATH = Path(__file__).parent / "data" / "nouns_exclusions.json"


def _load_exclusions() -> dict:
    if not _EXCLUSIONS_PATH.exists():
        return {"twitter_handles": [], "farcaster": [], "name_keywords": []}
    with open(_EXCLUSIONS_PATH) as f:
        return json.load(f)


_EXCLUSIONS = _load_exclusions()
_TW = set(_EXCLUSIONS.get("twitter_handles", []))
_FC = set(_EXCLUSIONS.get("farcaster", []))
_KW = [k.lower() for k in _EXCLUSIONS.get("name_keywords", [])]


def is_excluded(lead: dict) -> tuple[bool, str]:
    """
    Return (excluded, reason). A lead is excluded if it is one of
    Nouns DAO's own or affiliated projects (we don't pitch Nouns to itself).
    """
    # 1. Twitter handle match
    handle = (lead.get("twitter_handle") or "").lstrip("@").lower()
    if handle and handle in _TW:
        return True, f"Nouns-affiliated Twitter handle @{handle}"

    # 2. URL contains an excluded twitter handle or farcaster channel
    url = (lead.get("url") or "").lower()
    for h in _TW:
        if f"x.com/{h}" in url or f"twitter.com/{h}" in url:
            return True, f"Nouns-affiliated URL ({h})"
    for c in _FC:
        if f"farcaster.xyz/{c}" in url or f"/channel/{c}" in url:
            return True, f"Nouns-affiliated Farcaster ({c})"

    # 3. Name keyword match
    name = (lead.get("name") or "").lower()
    desc = (lead.get("description") or "").lower()
    for kw in _KW:
        if kw in name:
            return True, f"Nouns-affiliated name keyword '{kw}'"

    # 4. Strong signal: name + description both scream Nouns-native
    #    (e.g. "Prop House (by Nouns DAO)") — catch "by nouns" / "funded by nouns"
    blob = f"{name} {desc}"
    for phrase in ("by nouns dao", "funded by nouns", "nouns dao proposal",
                   "subdao of nouns", "born in and funded by nouns"):
        if phrase in blob:
            return True, f"Nouns-native project ('{phrase}')"

    return False, ""


def filter_leads(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split leads into (kept, excluded)."""
    kept, excluded = [], []
    for lead in leads:
        is_excl, reason = is_excluded(lead)
        if is_excl:
            lead["_exclusion_reason"] = reason
            excluded.append(lead)
        else:
            kept.append(lead)
    return kept, excluded
