"""
SYSFIX License Expiry Engine & Reminder System
Evaluates software license expiration, subscription renewal windows, and grace periods:
- Expiry States: ACTIVE, EXPIRING_SOON, EXPIRED, GRACE_PERIOD, PERPETUAL, UNKNOWN, VERIFICATION_REQUIRED
- Configurable reminder windows: 30 days, 14 days, 7 days, 3 days, 1 day, on expiry date, and after expiry
- SQLite deduplication: Prevents repeat notifications for the same threshold window
- Manual subscription / license records management (CRUD)
- Integration with Windows native toasts and in-app alerts

Strict Integrity: Never invents expiry dates based on install dates or version numbers.
Separates current activation status from future subscription expiry.
"""

import csv
import io
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

from backend.core.cryptic import sanitize_report_text, to_cryptic

logger = logging.getLogger("SYSFIX.LicenseExpiry")

# Default reminder windows in days before expiry
STANDARD_REMINDER_WINDOWS = [30, 14, 7, 3, 1, 0, -1]

def parse_date_safe(date_str: Optional[str]) -> Optional[date]:
    """Safely parse various date formats into date object."""
    if not date_str or not str(date_str).strip():
        return None
    cleaned = str(date_str).strip()
    # Check for placeholder non-expiring dates (e.g. 01-01-1601 from OSPP beta expiration)
    if "1601" in cleaned or "0000" in cleaned or "none" in cleaned.lower():
        return None

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None

def evaluate_license_expiry(
    expiry_date_str: Optional[str],
    license_category: str = "Incomplete Evidence",
    raw_status: Optional[str] = None,
    warning_threshold_days: int = 30
) -> Dict[str, Any]:
    """
    Evaluate license expiry status without assuming or inventing dates.
    Returns normalized expiry state, days remaining, badge class, and explanation.
    """
    clean_cat = (license_category or "Incomplete Evidence").strip()
    status_lower = (raw_status or "").lower()

    # 1. Grace period evidence takes immediate precedence if active
    if "grace" in status_lower:
        return {
            "state": "GRACE_PERIOD",
            "badge_class": "badge-warning",
            "days_remaining": None,
            "expiry_date": expiry_date_str,
            "reason": "Software is currently running under a temporary activation grace period."
        }

    # 2. Check for perpetual / non-expiring license models
    is_perpetual = clean_cat in ("Open Source", "Perpetual", "Freeware")
    
    parsed_exp = parse_date_safe(expiry_date_str)
    
    # If no expiry date is discoverable
    if not parsed_exp:
        if is_perpetual:
            return {
                "state": "PERPETUAL",
                "badge_class": "badge-healthy",
                "days_remaining": None,
                "expiry_date": None,
                "reason": f"Perpetual {clean_cat} license. Does not require periodic renewal."
            }
        return {
            "state": "UNKNOWN",
            "badge_class": "badge-cryptic",
            "days_remaining": None,
            "expiry_date": None,
            "reason": "License expiry date is not documented in local registry metadata. Missing metadata does not indicate an expired license."
        }

    # Expiry date is known
    today = date.today()
    delta = (parsed_exp - today).days

    if delta < 0:
        return {
            "state": "EXPIRED",
            "badge_class": "badge-critical",
            "days_remaining": delta,
            "expiry_date": parsed_exp.strftime("%Y-%m-%d"),
            "reason": f"License expired {abs(delta)} day{'s' if abs(delta) != 1 else ''} ago on {parsed_exp.strftime('%Y-%m-%d')}."
        }
    elif delta <= warning_threshold_days:
        return {
            "state": "EXPIRING_SOON",
            "badge_class": "badge-warning",
            "days_remaining": delta,
            "expiry_date": parsed_exp.strftime("%Y-%m-%d"),
            "reason": f"License expires in {delta} day{'s' if delta != 1 else ''} on {parsed_exp.strftime('%Y-%m-%d')}."
        }
    else:
        return {
            "state": "ACTIVE",
            "badge_class": "badge-healthy",
            "days_remaining": delta,
            "expiry_date": parsed_exp.strftime("%Y-%m-%d"),
            "reason": f"License is active through {parsed_exp.strftime('%Y-%m-%d')} ({delta} days remaining)."
        }

def export_expiry_audit_to_csv(records: List[Dict[str, Any]]) -> str:
    """Export license expiry records to CSV."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")

    writer.writerow([
        "Application Name", "Publisher", "License Category", "Expiry Date",
        "Expiry State", "Days Remaining", "Source", "Notes"
    ])

    for r in records:
        writer.writerow([
            r.get("name", ""),
            r.get("publisher", ""),
            to_cryptic(r.get("license_category", "Cryptic")),
            to_cryptic(r.get("expiry_date", "Cryptic")),
            to_cryptic(r.get("expiry_state", "CRYPTIC")),
            str(r.get("days_remaining")) if r.get("days_remaining") is not None else "N/A",
            r.get("source", "Telemetry"),
            r.get("notes", "")
        ])

    return sanitize_report_text(output.getvalue())

def export_expiry_audit_to_html(records: List[Dict[str, Any]]) -> str:
    """Export license expiry records to responsive HTML."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_count = sum(1 for r in records if r.get("expiry_state") == "ACTIVE")
    expiring_count = sum(1 for r in records if r.get("expiry_state") == "EXPIRING_SOON")
    expired_count = sum(1 for r in records if r.get("expiry_state") == "EXPIRED")
    perpetual_count = sum(1 for r in records if r.get("expiry_state") == "PERPETUAL")

    rows_html = []
    for r in records:
        st = r.get("expiry_state", "CRYPTIC")
        badge_style = "background: #234e3f; color: #45D6A3;" if st in ("ACTIVE", "PERPETUAL") else \
                      "background: #4a3e21; color: #FFC66D;" if st in ("EXPIRING_SOON", "GRACE_PERIOD") else \
                      "background: #54222b; color: #FF647C;" if st == "EXPIRED" else \
                      "background: #333a4d; color: #A2ACC0;"

        days_text = f"{r.get('days_remaining')} days" if r.get("days_remaining") is not None else "--"
        if r.get("days_remaining") is not None and r.get("days_remaining") < 0:
            days_text = f"{abs(r.get('days_remaining'))} days ago"

        rows_html.append(f"""
        <tr>
          <td><strong>{r.get('name', '')}</strong></td>
          <td>{r.get('publisher', '')}</td>
          <td>{r.get('license_category', 'Incomplete Evidence')}</td>
          <td><code>{r.get('expiry_date') or 'Undisclosed'}</code></td>
          <td><span style="padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; {badge_style}">{st}</span></td>
          <td>{days_text}</td>
          <td><small>{r.get('source', 'Discovered')}</small></td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SYSFIX — License Expiry & Subscription Audit Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0F172A; color: #F8FAFC; margin: 0; padding: 30px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ border-bottom: 2px solid #334155; padding-bottom: 20px; margin-bottom: 24px; }}
    h1 {{ margin: 0 0 6px 0; font-size: 24px; color: #7C83FF; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
    .stat-card {{ background: #1E293B; border-radius: 8px; padding: 16px; border: 1px solid #334155; }}
    .stat-val {{ font-size: 26px; font-weight: bold; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #1E293B; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #334155; font-size: 13px; }}
    th {{ background: #0F172A; color: #94A3B8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
    tr:hover {{ background: rgba(124, 131, 255, 0.05); }}
    code {{ font-family: monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>SYSFIX — License Expiry & Subscription Audit Report</h1>
      <p style="margin: 0; color: #94A3B8; font-size: 13px;">Generated on {now_str} • Verified Expiry Tracking</p>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Active Subscriptions</div>
        <div class="stat-val" style="color: #45D6A3;">{active_count}</div>
      </div>
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Expiring Soon (&le;30d)</div>
        <div class="stat-val" style="color: #FFC66D;">{expiring_count}</div>
      </div>
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Expired Licenses</div>
        <div class="stat-val" style="color: #FF647C;">{expired_count}</div>
      </div>
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Perpetual / Non-Expiring</div>
        <div class="stat-val" style="color: #7C83FF;">{perpetual_count}</div>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Application</th>
          <th>Publisher</th>
          <th>License Category</th>
          <th>Expiry Date</th>
          <th>Status</th>
          <th>Time Remaining</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </div>
</body>
</html>"""
    return sanitize_report_text(html)

