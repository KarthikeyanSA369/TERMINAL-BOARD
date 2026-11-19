"""
SYSFIX Global Cryptic Terminology Engine
Enforces user-facing terminology: never displays 'Unknown'; displays 'Cryptic' instead.

Principles:
- 'Cryptic' means available evidence is indeterminate or inconclusive.
- 'Cryptic' is NOT treated as a confirmed hardware fault or failure.
- Internal enum keys / third-party Windows APIs may retain technical identifiers,
  but presentation layer (HTML, emails, CSV exports, toast notifications) translates
  all indeterminate values to 'Cryptic'.
"""

import re
from typing import Any, Dict, List, Union


def to_cryptic(val: Any) -> str:
    """
    Format a scalar or string value, replacing any user-facing 'Unknown' with 'Cryptic'.
    Preserves other text while ensuring 'Unknown' is strictly sanitized.
    """
    if val is None:
        return "Cryptic"
    s = str(val).strip()
    if not s:
        return "Cryptic"
    if s.lower() == "unknown":
        return "Cryptic"
    # Replace standalone whole word 'unknown' (case-insensitive) with 'Cryptic'
    return re.sub(r"\bunknown\b", "Cryptic", s, flags=re.IGNORECASE)


def sanitize_report_text(text: str) -> str:
    """
    Sanitize an entire HTML or CSV document to ensure no user-facing 'Unknown' remains.
    Safely ignores URLs, variable identifiers, or internal code while replacing
    user-facing phrases.
    """
    if not text:
        return ""
    # Replace whole word unknown
    return re.sub(r"\bunknown\b", "Cryptic", text, flags=re.IGNORECASE)


def apply_cryptic_to_dict(data: Union[Dict[str, Any], List[Any], Any]) -> Any:
    """Recursively sanitize dictionary or list values for presentation."""
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                new_dict[k] = apply_cryptic_to_dict(v)
            elif isinstance(v, str):
                new_dict[k] = to_cryptic(v)
            else:
                new_dict[k] = v
        return new_dict
    elif isinstance(data, list):
        return [apply_cryptic_to_dict(item) for item in data]
    elif isinstance(data, str):
        return to_cryptic(data)
    return data
