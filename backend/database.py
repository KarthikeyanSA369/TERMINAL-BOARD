"""
SYSFIX Database Module
Provides local persistence using SQLite for system metrics, drive health,
Windows event logs, network diagnostics, installed software, license audits,
and user alert history with parameterized queries and retention cleanup.
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# Default database location in user's AppData or local workspace
def get_db_path() -> str:
    app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if app_data:
        target_dir = os.path.join(app_data, "TerminalBoard")
        legacy_dir = os.path.join(app_data, "SYSFIX")
        os.makedirs(target_dir, exist_ok=True)
        new_db = os.path.join(target_dir, "terminal_board.db")
        legacy_db = os.path.join(legacy_dir, "sysfix.db")
        if not os.path.exists(new_db) and os.path.exists(legacy_db):
            try:
                import shutil
                shutil.copy2(legacy_db, new_db)
            except Exception:
                return legacy_db
        return new_db
    else:
        target_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(target_dir, exist_ok=True)
        return os.path.join(target_dir, "terminal_board.db")

DB_PATH = get_db_path()

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for high performance concurrent reads and writes
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Metric snapshots table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS metric_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        cpu_percent REAL,
        ram_percent REAL,
        ram_used_bytes INTEGER,
        ram_total_bytes INTEGER,
        battery_percent REAL,
        is_charging INTEGER,
        disk_free_gb REAL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_metric_timestamp ON metric_snapshots (timestamp)")

    # Drive health table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS drive_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        device_id TEXT,
        model TEXT,
        media_type TEXT,
        bus_type TEXT,
        operational_status TEXT,
        health_status TEXT,
        size_bytes INTEGER,
        details_json TEXT
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_drive_timestamp ON drive_snapshots (timestamp)")

    # Windows events table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS windows_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_record_id INTEGER,
        time_created TIMESTAMP,
        event_id INTEGER,
        provider_name TEXT,
        level_name TEXT,
        log_name TEXT,
        message TEXT,
        details_json TEXT,
        UNIQUE(log_name, event_record_id, event_id) ON CONFLICT IGNORE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON windows_events (time_created)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_level ON windows_events (level_name)")

    # Network diagnostic history
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS network_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_connected INTEGER,
        ping_ms REAL,
        dns_ok INTEGER,
        gateway_ok INTEGER,
        packet_loss REAL,
        gateway_ip TEXT,
        details_json TEXT
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_net_timestamp ON network_history (timestamp)")

    # Alerts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        metric_name TEXT,
        severity TEXT,
        title TEXT,
        message TEXT,
        evidence TEXT,
        recommended_steps TEXT,
        status TEXT DEFAULT 'active',
        resolved_at TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts (timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status)")

    # Installed software table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS installed_software (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        version TEXT,
        publisher TEXT,
        install_location TEXT,
        exe_path TEXT,
        source TEXT,
        category TEXT,
        last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, install_location) ON CONFLICT REPLACE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_software_name ON installed_software (name)")

    # License audit table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS license_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        version TEXT,
        publisher TEXT,
        category TEXT DEFAULT 'Software',
        license_category TEXT DEFAULT 'Unknown',
        license_identifier TEXT,
        license_source TEXT,
        evidence_source TEXT DEFAULT 'Unknown or inconclusive evidence',
        verification_status TEXT,
        verification_method TEXT DEFAULT 'Inconclusive Heuristic',
        activation_status TEXT DEFAULT 'Activation Data Unavailable',
        file_path TEXT,
        status_reason TEXT,
        notes TEXT,
        compliance_notes TEXT DEFAULT '',
        install_location TEXT,
        last_audited TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, version) ON CONFLICT REPLACE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_license_name ON license_audit (name)")

    # Microsoft Office licensing snapshots table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS office_licensing_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku_id TEXT,
        license_name TEXT,
        license_description TEXT,
        license_channel TEXT,
        license_status TEXT,
        normalized_status TEXT,
        error_code TEXT,
        error_description TEXT,
        last_5_key TEXT,
        activation_type TEXT,
        kms_server TEXT,
        remaining_grace_days INTEGER,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_office_status ON office_licensing_snapshots (normalized_status)")

    # Windows licensing snapshots table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS windows_licensing_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        description TEXT,
        status_code INTEGER,
        status_label TEXT,
        is_activated INTEGER,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Manual user license & subscription records table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS manual_license_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        publisher TEXT,
        license_category TEXT DEFAULT 'Subscription',
        purchase_date TEXT,
        expiry_date TEXT,
        source TEXT DEFAULT 'User-provided',
        notes TEXT,
        reminder_days TEXT DEFAULT '30,14,7,1',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manual_lic_name ON manual_license_records (name)")

    # Driver inventory snapshots table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS driver_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT NOT NULL,
        device_class TEXT,
        manufacturer TEXT,
        provider TEXT,
        driver_version TEXT,
        driver_date TEXT,
        device_id TEXT,
        inf_name TEXT,
        status TEXT,
        problem_code INTEGER DEFAULT 0,
        problem_description TEXT,
        health_classification TEXT DEFAULT 'HEALTHY',
        health_reason TEXT,
        last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_driver_health ON driver_inventory (health_classification)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_driver_name ON driver_inventory (device_name)")

    # License expiry notification tracker to suppress duplicates
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS license_expiry_reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_name TEXT NOT NULL,
        expiry_date TEXT NOT NULL,
        threshold_days INTEGER NOT NULL,
        notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(license_name, expiry_date, threshold_days) ON CONFLICT IGNORE
    )
    """)

    # Seed default settings if empty
    default_settings = {
        "cpu_warning_threshold": "85",
        "cpu_sustained_threshold": "90",
        "ram_warning_threshold": "85",
        "disk_warning_threshold": "10",
        "monitor_interval_sec": "3",
        "event_monitor_interval_sec": "30",
        "enable_desktop_notifications": "1",
        "enable_sound": "0",
        "retention_days": "30",
        "enable_background_monitor": "1",
        "theme": "dark"
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

    # Run safe migrations for existing installations
    migrate_database(db_path)

# Settings helpers
def get_setting(key: str, default: Any = None, db_path: Optional[str] = None) -> Any:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def get_all_settings(db_path: Optional[str] = None) -> Dict[str, str]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def set_setting(key: str, value: Any, db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    """, (key, str(value)))
    conn.commit()
    conn.close()

# Metric history helpers
def record_metric_snapshot(data: Dict[str, Any], db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO metric_snapshots (
        cpu_percent, ram_percent, ram_used_bytes, ram_total_bytes,
        battery_percent, is_charging, disk_free_gb
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("cpu_percent"),
        data.get("ram_percent"),
        data.get("ram_used_bytes"),
        data.get("ram_total_bytes"),
        data.get("battery_percent"),
        1 if data.get("is_charging") else 0,
        data.get("disk_free_gb")
    ))
    conn.commit()
    conn.close()

def get_recent_metrics(limit: int = 30, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, timestamp, cpu_percent, ram_percent, ram_used_bytes, ram_total_bytes,
           battery_percent, is_charging, disk_free_gb
    FROM metric_snapshots ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

# Alert helpers
def insert_alert(metric_name: str, severity: str, title: str, message: str,
                 evidence: str = "", recommended_steps: str = "",
                 db_path: Optional[str] = None) -> int:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO alerts (metric_name, severity, title, message, evidence, recommended_steps)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (metric_name, severity, title, message, evidence, recommended_steps))
    alert_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return alert_id

def get_alerts(status_filter: Optional[str] = None, limit: int = 100,
               db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if status_filter:
        cursor.execute("""
        SELECT * FROM alerts WHERE status = ? ORDER BY timestamp DESC LIMIT ?
        """, (status_filter, limit))
    else:
        cursor.execute("SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_alert_status(alert_id: int, new_status: str, db_path: Optional[str] = None) -> bool:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    resolved_at = datetime.utcnow().isoformat() if new_status in ("acknowledged", "dismissed") else None
    cursor.execute("""
    UPDATE alerts SET status = ?, resolved_at = ? WHERE id = ?
    """, (new_status, resolved_at, alert_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_active_alert_by_metric(metric_name: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM alerts WHERE metric_name = ? AND status = 'active'
    ORDER BY timestamp DESC LIMIT 1
    """, (metric_name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# Maintenance & Cleanup
def cleanup_old_records(retention_days: int = 30, db_path: Optional[str] = None) -> Dict[str, int]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    
    deleted = {}
    for table in ["metric_snapshots", "network_history", "windows_events"]:
        cursor.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
        deleted[table] = cursor.rowcount
        
    conn.commit()
    conn.close()
    return deleted

def clear_metric_history(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    conn.execute("DELETE FROM metric_snapshots")
    conn.commit()
    conn.close()

def clear_alert_history(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    conn.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()

def clear_all_history(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    conn.execute("DELETE FROM metric_snapshots")
    conn.execute("DELETE FROM drive_snapshots")
    conn.execute("DELETE FROM windows_events")
    conn.execute("DELETE FROM network_history")
    conn.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()

# Safe Schema Migrations & License Audit Persistence
def migrate_database(db_path: Optional[str] = None) -> None:
    """Safely migrate database schemas idempotently without data loss."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(license_audit)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        
        target_columns = [
            ("category", "TEXT DEFAULT 'Software'"),
            ("license_category", "TEXT DEFAULT 'Unknown'"),
            ("evidence_source", "TEXT DEFAULT 'Unknown or inconclusive evidence'"),
            ("verification_method", "TEXT DEFAULT 'Inconclusive Heuristic'"),
            ("activation_status", "TEXT DEFAULT 'Activation Data Unavailable'"),
            ("status_reason", "TEXT DEFAULT ''"),
            ("compliance_notes", "TEXT DEFAULT ''"),
            ("install_location", "TEXT DEFAULT ''"),
            ("expiry_date", "TEXT DEFAULT ''"),
            ("expiry_state", "TEXT DEFAULT 'UNKNOWN'")
        ]
        
        for col_name, col_type in target_columns:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE license_audit ADD COLUMN {col_name} {col_type}")
                
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_license_category ON license_audit (license_category)")

        # Create additional tables if not existing
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS office_licensing_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku_id TEXT,
            license_name TEXT,
            license_description TEXT,
            license_channel TEXT,
            license_status TEXT,
            normalized_status TEXT,
            error_code TEXT,
            error_description TEXT,
            last_5_key TEXT,
            activation_type TEXT,
            kms_server TEXT,
            remaining_grace_days INTEGER,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_office_status ON office_licensing_snapshots (normalized_status)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS windows_licensing_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            description TEXT,
            status_code INTEGER,
            status_label TEXT,
            is_activated INTEGER,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manual_license_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            publisher TEXT,
            license_category TEXT DEFAULT 'Subscription',
            purchase_date TEXT,
            expiry_date TEXT,
            source TEXT DEFAULT 'User-provided',
            notes TEXT,
            reminder_days TEXT DEFAULT '30,14,7,1',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_manual_lic_name ON manual_license_records (name)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS driver_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            device_class TEXT,
            manufacturer TEXT,
            provider TEXT,
            driver_version TEXT,
            driver_date TEXT,
            device_id TEXT,
            inf_name TEXT,
            status TEXT,
            problem_code INTEGER DEFAULT 0,
            problem_description TEXT,
            health_classification TEXT DEFAULT 'HEALTHY',
            health_reason TEXT,
            last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_driver_health ON driver_inventory (health_classification)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_driver_name ON driver_inventory (device_name)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS license_expiry_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_name TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            threshold_days INTEGER NOT NULL,
            notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(license_name, expiry_date, threshold_days) ON CONFLICT IGNORE
        )
        """)

        # Email Reports, Delivery History, Offline Queue & Driver Fault State Tables
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            smtp_host TEXT DEFAULT 'smtp.gmail.com',
            smtp_port INTEGER DEFAULT 587,
            smtp_use_tls INTEGER DEFAULT 1,
            smtp_use_ssl INTEGER DEFAULT 0,
            smtp_sender TEXT DEFAULT '',
            smtp_username TEXT DEFAULT '',
            recipient_email TEXT DEFAULT 'karthikeyansa369@gmail.com',
            daily_report_enabled INTEGER DEFAULT 1,
            daily_report_time TEXT DEFAULT '19:00',
            driver_alerts_enabled INTEGER DEFAULT 1,
            driver_recovery_enabled INTEGER DEFAULT 1,
            alert_cooldown_min INTEGER DEFAULT 60,
            scheduler_registered INTEGER DEFAULT 0,
            next_scheduled_run TEXT DEFAULT '',
            last_successful_delivery TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        INSERT OR IGNORE INTO email_settings (
            id, recipient_email, daily_report_time, daily_report_enabled,
            driver_alerts_enabled, driver_recovery_enabled
        ) VALUES (1, 'karthikeyansa369@gmail.com', '19:00', 1, 1, 1)
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_delivery_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_hist_ts ON email_delivery_history (timestamp)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_html TEXT NOT NULL,
            body_text TEXT DEFAULT '',
            attachments_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'PENDING',
            retry_count INTEGER DEFAULT 0,
            next_retry_at TIMESTAMP,
            last_error TEXT DEFAULT ''
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_q_status ON email_queue (status)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS driver_fault_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL UNIQUE,
            device_name TEXT NOT NULL,
            fault_signature TEXT NOT NULL,
            problem_code INTEGER DEFAULT 0,
            severity TEXT DEFAULT 'CRITICAL',
            first_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_alerted_at TIMESTAMP,
            status TEXT DEFAULT 'ACTIVE',
            recovery_detected_at TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_driver_fault_dev ON driver_fault_states (device_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_driver_fault_status ON driver_fault_states (status)")

        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

def save_or_update_license_audit_records(records: List[Dict[str, Any]], db_path: Optional[str] = None) -> None:
    """
    Persist or update license audit records, preserving existing manual compliance notes.
    """
    if not records:
        return
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Query existing compliance notes by name & version
    cursor.execute("SELECT name, version, compliance_notes FROM license_audit WHERE compliance_notes != '' AND compliance_notes IS NOT NULL")
    existing_notes = {(row["name"], row["version"]): row["compliance_notes"] for row in cursor.fetchall()}
    
    for r in records:
        name = r.get("name", "Unknown")
        version = r.get("version", "Unknown")
        custom_note = r.get("compliance_notes") or existing_notes.get((name, version), "")
        r["compliance_notes"] = custom_note
        
        cursor.execute("""
        INSERT INTO license_audit (
            name, version, publisher, category, license_category, license_identifier,
            license_source, evidence_source, verification_status, verification_method,
            activation_status, file_path, status_reason, notes, compliance_notes,
            install_location, expiry_date, expiry_state, last_audited
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, version) DO UPDATE SET
            publisher = excluded.publisher,
            category = excluded.category,
            license_category = excluded.license_category,
            license_identifier = excluded.license_identifier,
            license_source = excluded.license_source,
            evidence_source = excluded.evidence_source,
            verification_status = excluded.verification_status,
            verification_method = excluded.verification_method,
            activation_status = excluded.activation_status,
            file_path = excluded.file_path,
            status_reason = excluded.status_reason,
            notes = excluded.notes,
            compliance_notes = CASE WHEN license_audit.compliance_notes != '' THEN license_audit.compliance_notes ELSE excluded.compliance_notes END,
            install_location = excluded.install_location,
            expiry_date = CASE WHEN excluded.expiry_date != '' THEN excluded.expiry_date ELSE license_audit.expiry_date END,
            expiry_state = CASE WHEN excluded.expiry_state != 'UNKNOWN' THEN excluded.expiry_state ELSE license_audit.expiry_state END,
            last_audited = excluded.last_audited
        """, (
            name,
            version,
            r.get("publisher", ""),
            r.get("category", "Software"),
            r.get("license_category", "Unknown"),
            r.get("license_identifier", ""),
            r.get("license_source", ""),
            r.get("evidence_source", "Unknown or inconclusive evidence"),
            r.get("verification_status", "Unknown"),
            r.get("verification_method", "Inconclusive Heuristic"),
            r.get("activation_status", "Activation Data Unavailable"),
            r.get("file_path") or r.get("license_file", ""),
            r.get("status_reason", ""),
            r.get("notes", ""),
            custom_note,
            r.get("install_location") or r.get("install_path", ""),
            r.get("expiry_date", ""),
            r.get("expiry_state", "UNKNOWN"),
            r.get("last_audited") or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        ))
        
    conn.commit()
    conn.close()

def update_license_compliance_note(name: str, version: str, compliance_notes: str, db_path: Optional[str] = None) -> bool:
    """Update manual user compliance notes for an audited application."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE license_audit
    SET compliance_notes = ?,
        evidence_source = CASE WHEN evidence_source = 'Unknown or inconclusive evidence' THEN 'User-provided compliance records' ELSE evidence_source END
    WHERE name = ? AND version = ?
    """, (compliance_notes, name, version))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_all_license_audit_records(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all persisted license audit records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM license_audit ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Office Licensing Persistence
def save_office_licensing_snapshot(records: List[Dict[str, Any]], db_path: Optional[str] = None) -> None:
    """Persist Office licensing snapshot records."""
    if not records:
        return
    conn = get_connection(db_path)
    cursor = conn.cursor()
    for r in records:
        cursor.execute("""
        INSERT INTO office_licensing_snapshots (
            sku_id, license_name, license_description, license_channel,
            license_status, normalized_status, error_code, error_description,
            last_5_key, activation_type, kms_server, remaining_grace_days
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r.get("sku_id", ""),
            r.get("license_name", ""),
            r.get("license_description", ""),
            r.get("license_channel", ""),
            r.get("license_status", ""),
            r.get("normalized_status", "UNKNOWN"),
            r.get("error_code", ""),
            r.get("error_description", ""),
            r.get("last_5_key", ""),
            r.get("activation_type", ""),
            r.get("kms_server", ""),
            r.get("remaining_grace_days")
        ))
    conn.commit()
    conn.close()

def get_latest_office_licensing_snapshot(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve the most recent Office licensing records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM office_licensing_snapshots ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Windows Licensing Persistence
def save_windows_licensing_snapshot(data: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Persist Windows activation status snapshot."""
    if not data:
        return
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO windows_licensing_snapshots (
        product_name, description, status_code, status_label, is_activated
    ) VALUES (?, ?, ?, ?, ?)
    """, (
        data.get("product_name", "Windows"),
        data.get("description", ""),
        data.get("status_code", 0),
        data.get("status_label", "Unknown"),
        1 if data.get("is_activated") else 0
    ))
    conn.commit()
    conn.close()

def get_latest_windows_licensing_snapshot(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve latest Windows activation status snapshot."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM windows_licensing_snapshots ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# Manual User License & Subscription Records CRUD
def create_manual_license_record(data: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """Create a new user-entered manual subscription or license record."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    name_val = data.get("name") or data.get("app_name") or "Custom License"
    cat_val = data.get("license_category") or data.get("category") or "Subscription"
    notes_val = data.get("notes") or data.get("compliance_notes") or ""
    ref_val = data.get("license_reference") or ""
    if ref_val:
        notes_val = f"Ref: {ref_val} | {notes_val}" if notes_val else f"Ref: {ref_val}"
    rem_val = str(data.get("reminder_days") or data.get("reminder_days_before") or "30,14,7,1")

    cursor.execute("""
    INSERT INTO manual_license_records (
        name, publisher, license_category, purchase_date, expiry_date, source, notes, reminder_days
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name_val,
        data.get("publisher", ""),
        cat_val,
        data.get("purchase_date", ""),
        data.get("expiry_date", ""),
        "User-provided",
        notes_val,
        rem_val
    ))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id

def update_manual_license_record(record_id: int, data: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """Update an existing manual license record."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    name_val = data.get("name") or data.get("app_name") or ""
    cat_val = data.get("license_category") or data.get("category") or "Subscription"
    notes_val = data.get("notes") or data.get("compliance_notes") or ""
    ref_val = data.get("license_reference") or ""
    if ref_val and f"Ref: {ref_val}" not in notes_val:
        notes_val = f"Ref: {ref_val} | {notes_val}" if notes_val else f"Ref: {ref_val}"
    rem_val = str(data.get("reminder_days") or data.get("reminder_days_before") or "30,14,7,1")

    cursor.execute("""
    UPDATE manual_license_records
    SET name = ?, publisher = ?, license_category = ?, purchase_date = ?,
        expiry_date = ?, notes = ?, reminder_days = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (
        name_val,
        data.get("publisher", ""),
        cat_val,
        data.get("purchase_date", ""),
        data.get("expiry_date", ""),
        notes_val,
        rem_val,
        record_id
    ))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def delete_manual_license_record(record_id: int, db_path: Optional[str] = None) -> bool:
    """Delete a user manual license record."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM manual_license_records WHERE id = ?", (record_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_manual_license_records(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all user-provided manual license records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM manual_license_records ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["app_name"] = d.get("name", "")
        d["category"] = d.get("license_category", "")
        d["compliance_notes"] = d.get("notes", "")
        notes = d.get("notes", "")
        if "Ref: " in notes:
            d["license_reference"] = notes.split("Ref: ", 1)[1].split(" |", 1)[0]
        else:
            d["license_reference"] = ""
        res.append(d)
    return res

# Driver Inventory Persistence
def save_driver_snapshots(drivers: List[Dict[str, Any]], db_path: Optional[str] = None) -> None:
    """Persist driver inventory snapshot."""
    if not drivers:
        return
    conn = get_connection(db_path)
    cursor = conn.cursor()
    for d in drivers:
        cursor.execute("""
        INSERT INTO driver_inventory (
            device_name, device_class, manufacturer, provider, driver_version,
            driver_date, device_id, inf_name, status, problem_code,
            problem_description, health_classification, health_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d.get("device_name", ""),
            d.get("device_class", ""),
            d.get("manufacturer", ""),
            d.get("provider", ""),
            d.get("driver_version", ""),
            d.get("driver_date", ""),
            d.get("device_id", ""),
            d.get("inf_name", ""),
            d.get("status", "OK"),
            d.get("problem_code", 0),
            d.get("problem_description", ""),
            d.get("health_classification", "HEALTHY"),
            d.get("health_reason", "")
        ))
    conn.commit()
    conn.close()

def get_latest_driver_snapshots(limit: int = 250, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve recent driver inventory records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM driver_inventory ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Expiry Notification Tracker Helpers
def record_expiry_reminder(license_name: str, expiry_date: str, threshold: int, db_path: Optional[str] = None) -> bool:
    """Record an expiry notification to prevent duplicate reminders."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO license_expiry_reminders (license_name, expiry_date, threshold_days)
        VALUES (?, ?, ?)
        """, (license_name, expiry_date, threshold))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def is_expiry_reminder_sent(license_name: str, expiry_date: str, threshold: int, db_path: Optional[str] = None) -> bool:
    """Check if an expiry alert has already been dispatched for this specific threshold."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id FROM license_expiry_reminders
    WHERE license_name = ? AND expiry_date = ? AND threshold_days = ?
    """, (license_name, expiry_date, threshold))
    row = cursor.fetchone()
    conn.close()
    return row is not None

# ================= EMAIL AUTOMATION & DRIVER FAULT HELPERS ================= #

def get_email_settings(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve application email reporting and automation settings."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM email_settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["smtp_use_tls"] = bool(d.get("smtp_use_tls", 1))
        d["smtp_use_ssl"] = bool(d.get("smtp_use_ssl", 0))
        d["daily_report_enabled"] = bool(d.get("daily_report_enabled", 1))
        d["driver_alerts_enabled"] = bool(d.get("driver_alerts_enabled", 1))
        d["driver_recovery_enabled"] = bool(d.get("driver_recovery_enabled", 1))
        d["scheduler_registered"] = bool(d.get("scheduler_registered", 0))
        return d
    return {
        "id": 1,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
        "smtp_sender": "",
        "smtp_username": "",
        "recipient_email": "karthikeyansa369@gmail.com",
        "daily_report_enabled": True,
        "daily_report_time": "19:00",
        "driver_alerts_enabled": True,
        "driver_recovery_enabled": True,
        "alert_cooldown_min": 60,
        "scheduler_registered": False,
        "next_scheduled_run": "",
        "last_successful_delivery": ""
    }

def update_email_settings(data: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """Update application email reporting settings."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    fields = [
        "smtp_host", "smtp_port", "smtp_use_tls", "smtp_use_ssl", "smtp_sender",
        "smtp_username", "recipient_email", "daily_report_enabled", "daily_report_time",
        "driver_alerts_enabled", "driver_recovery_enabled", "alert_cooldown_min",
        "scheduler_registered", "next_scheduled_run", "last_successful_delivery"
    ]
    updates = []
    values = []
    for f in fields:
        if f in data:
            val = data[f]
            if isinstance(val, bool):
                val = 1 if val else 0
            updates.append(f"{f} = ?")
            values.append(val)
    if not updates:
        conn.close()
        return True
    
    updates.append("updated_at = CURRENT_TIMESTAMP")
    sql = f"UPDATE email_settings SET {', '.join(updates)} WHERE id = 1"
    cursor.execute(sql, values)
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def record_email_delivery(alert_type: str, recipient: str, subject: str, status: str,
                          error_message: str = "", retry_count: int = 0, db_path: Optional[str] = None) -> int:
    """Record email dispatch outcome in audit history."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO email_delivery_history (
        alert_type, recipient, subject, status, error_message, retry_count
    ) VALUES (?, ?, ?, ?, ?, ?)
    """, (alert_type, recipient, subject, status, error_message, retry_count))
    hist_id = cursor.lastrowid
    if status == "SENT":
        cursor.execute("UPDATE email_settings SET last_successful_delivery = CURRENT_TIMESTAMP WHERE id = 1")
    conn.commit()
    conn.close()
    return hist_id

def get_recent_email_deliveries(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve recent email delivery history records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM email_delivery_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def enqueue_email(alert_type: str, recipient: str, subject: str, body_html: str,
                  body_text: str = "", attachments_json: str = "[]", db_path: Optional[str] = None) -> int:
    """Place email message into offline persistent queue for background retry."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO email_queue (
        alert_type, recipient, subject, body_html, body_text, attachments_json, status, retry_count
    ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0)
    """, (alert_type, recipient, subject, body_html, body_text, attachments_json))
    queue_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return queue_id

def get_pending_email_queue(limit: int = 10, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve pending emails waiting in the retry queue."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM email_queue
    WHERE status = 'PENDING' AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP)
    ORDER BY id ASC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_email_queue_status(queue_id: int, status: str, last_error: str = "",
                              retry_increment: bool = True, db_path: Optional[str] = None) -> bool:
    """Update status of a queued email item."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if retry_increment and status == "PENDING":
        cursor.execute("""
        UPDATE email_queue
        SET status = ?, last_error = ?, retry_count = retry_count + 1,
            next_retry_at = datetime(CURRENT_TIMESTAMP, '+' || (retry_count * 5 + 2) || ' minutes')
        WHERE id = ?
        """, (status, last_error, queue_id))
    else:
        cursor.execute("""
        UPDATE email_queue
        SET status = ?, last_error = ?
        WHERE id = ?
        """, (status, last_error, queue_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_driver_fault_state(device_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Look up active or historical fault state for a specific device identifier."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM driver_fault_states WHERE device_id = ?", (device_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def record_driver_fault_state(device_id: str, device_name: str, fault_signature: str,
                              problem_code: int = 0, severity: str = "CRITICAL",
                              db_path: Optional[str] = None) -> bool:
    """Record or update a detected driver fault state transition."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO driver_fault_states (
        device_id, device_name, fault_signature, problem_code, severity, status, first_detected_at
    ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)
    ON CONFLICT(device_id) DO UPDATE SET
        device_name = excluded.device_name,
        fault_signature = excluded.fault_signature,
        problem_code = excluded.problem_code,
        severity = excluded.severity,
        status = 'ACTIVE'
    """, (device_id, device_name, fault_signature, problem_code, severity, now_str))
    conn.commit()
    conn.close()
    return True

def mark_driver_fault_alerted(device_id: str, db_path: Optional[str] = None) -> bool:
    """Mark that an email alert has been dispatched for this driver fault."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE driver_fault_states
    SET last_alerted_at = ?
    WHERE device_id = ?
    """, (now_str, device_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def mark_driver_fault_recovered(device_id: str, db_path: Optional[str] = None) -> bool:
    """Mark that a previously faulty device has recovered to healthy status."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE driver_fault_states
    SET status = 'RECOVERED', recovery_detected_at = ?
    WHERE device_id = ? AND status = 'ACTIVE'
    """, (now_str, device_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_all_active_driver_faults(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all currently active driver faults."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM driver_fault_states WHERE status = 'ACTIVE'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

