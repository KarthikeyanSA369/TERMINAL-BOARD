"""
Terminal Board — Instant File Search Engine
High-performance file and folder search inspired by Everything Search.
Uses SQLite FTS5 for sub-millisecond incremental search, indexed metadata,
fast scandir crawler, and safe Windows Explorer shell actions.
"""

import os
import sys
import time
import sqlite3
import threading
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from backend.database import DB_PATH, get_connection

_INDEXER_THREAD: Optional[threading.Thread] = None
_INDEXER_STOP_FLAG = threading.Event()
_INDEXER_STATE = {
    "status": "idle",       # "idle", "indexing", "stopped"
    "indexed_count": 0,
    "current_path": "",
    "last_indexed_at": None,
    "error": None
}

def init_search_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    """Initialize file indexing and search history tables with FTS5."""
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        
        # Primary file metadata table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            ext TEXT,
            size_bytes INTEGER DEFAULT 0,
            modified_ts INTEGER DEFAULT 0,
            is_dir INTEGER DEFAULT 0
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_name ON file_index (name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_ext ON file_index (ext)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_size ON file_index (size_bytes)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_mod ON file_index (modified_ts)")

        # FTS5 Virtual Table for Instant Text Search
        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS file_index_fts USING fts5(
            name,
            path,
            content='file_index',
            content_rowid='id',
            tokenize='unicode61'
        )
        """)

        # Triggers to keep FTS5 synchronized with file_index
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS file_index_ai AFTER INSERT ON file_index BEGIN
            INSERT INTO file_index_fts(rowid, name, path) VALUES (new.id, new.name, new.path);
        END;
        """)
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS file_index_ad AFTER DELETE ON file_index BEGIN
            INSERT INTO file_index_fts(file_index_fts, rowid, name, path) VALUES('delete', old.id, old.name, old.path);
        END;
        """)
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS file_index_au AFTER UPDATE ON file_index BEGIN
            INSERT INTO file_index_fts(file_index_fts, rowid, name, path) VALUES('delete', old.id, old.name, old.path);
            INSERT INTO file_index_fts(rowid, name, path) VALUES (new.id, new.name, new.path);
        END;
        """)

        # Search history table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_hist_time ON search_history (timestamp)")

        conn.commit()

        # Update initial count in state
        cursor.execute("SELECT COUNT(*) FROM file_index")
        _INDEXER_STATE["indexed_count"] = cursor.fetchone()[0]
    finally:
        if close_conn:
            conn.close()

def get_indexer_status() -> Dict[str, Any]:
    """Return live status of the background indexer."""
    return dict(_INDEXER_STATE)

def start_background_indexing(target_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Start or resume the background file indexing worker."""
    global _INDEXER_THREAD, _INDEXER_STOP_FLAG
    
    if _INDEXER_THREAD and _INDEXER_THREAD.is_alive():
        return {"success": False, "message": "Indexing is already running in background."}

    _INDEXER_STOP_FLAG.clear()
    
    if not target_dirs:
        # Default to user home directory and primary working drives
        user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        target_dirs = [user_profile]

    def _worker():
        global _INDEXER_STATE
        _INDEXER_STATE["status"] = "indexing"
        _INDEXER_STATE["error"] = None
        conn = get_connection()
        init_search_schema(conn)

        batch = []
        batch_size = 2000

        def flush_batch(b):
            if not b:
                return
            try:
                conn.executemany("""
                    INSERT OR REPLACE INTO file_index (path, name, ext, size_bytes, modified_ts, is_dir)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, b)
                conn.commit()
            except Exception as e:
                pass

        try:
            for root_dir in target_dirs:
                if not os.path.isdir(root_dir):
                    continue

                for dirpath, dirnames, filenames in os.walk(root_dir):
                    if _INDEXER_STOP_FLAG.is_set():
                        break

                    # Skip heavy or protected system/virtual environment directories
                    dirnames[:] = [d for d in dirnames if not d.startswith('$') and d not in (
                        'node_modules', '.git', '__pycache__', 'AppData\\Local\\Temp', 'Windows\\WinSxS'
                    )]

                    _INDEXER_STATE["current_path"] = dirpath

                    # Index directories
                    for d in dirnames:
                        full_dp = os.path.join(dirpath, d)
                        batch.append((full_dp, d, "", 0, 0, 1))

                    # Index files
                    for f in filenames:
                        full_fp = os.path.join(dirpath, f)
                        try:
                            st = os.stat(full_fp)
                            ext = os.path.splitext(f)[1].lower().lstrip(".")
                            batch.append((full_fp, f, ext, st.st_size, int(st.st_mtime), 0))
                        except (PermissionError, FileNotFoundError, OSError):
                            continue

                        if len(batch) >= batch_size:
                            flush_batch(batch)
                            _INDEXER_STATE["indexed_count"] += len(batch)
                            batch = []

                if _INDEXER_STOP_FLAG.is_set():
                    break

            if batch:
                flush_batch(batch)
                _INDEXER_STATE["indexed_count"] += len(batch)

            _INDEXER_STATE["status"] = "idle"
            _INDEXER_STATE["last_indexed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            _INDEXER_STATE["status"] = "stopped"
            _INDEXER_STATE["error"] = str(e)
        finally:
            conn.close()

    _INDEXER_THREAD = threading.Thread(target=_worker, daemon=True, name="TerminalBoard-FileIndexer")
    _INDEXER_THREAD.start()
    return {"success": True, "message": "Background file indexing started."}

def stop_background_indexing() -> Dict[str, Any]:
    """Signal background indexing to halt."""
    global _INDEXER_STOP_FLAG
    _INDEXER_STOP_FLAG.set()
    _INDEXER_STATE["status"] = "stopped"
    return {"success": True, "message": "Stop signal sent to indexer."}

def clear_search_index() -> Dict[str, Any]:
    """Wipe the local file index."""
    stop_background_indexing()
    time.sleep(0.1)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM file_index")
        conn.execute("DELETE FROM file_index_fts")
        conn.commit()
        _INDEXER_STATE["indexed_count"] = 0
        return {"success": True, "message": "File index cleared successfully."}
    finally:
        conn.close()

def search_files(
    query: str,
    extension: Optional[str] = None,
    path_filter: Optional[str] = None,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    modified_days: Optional[int] = None,
    limit: int = 100,
    save_history: bool = True
) -> Dict[str, Any]:
    """
    Search indexed files and directories with filters and instant FTS5 matching.
    """
    start_time = time.perf_counter()
    init_search_schema()
    conn = get_connection()
    clean_query = query.strip() if query else ""

    try:
        if save_history and clean_query:
            try:
                conn.execute("INSERT INTO search_history (query) VALUES (?)", (clean_query,))
                conn.commit()
            except Exception:
                pass

        params = []
        where_clauses = []

        if clean_query:
            # FTS5 search query
            # Escape double quotes and create prefix matching query
            escaped_q = clean_query.replace('"', '""')
            fts_query = f'"{escaped_q}"*'
            where_clauses.append("f.id IN (SELECT rowid FROM file_index_fts WHERE file_index_fts MATCH ?)")
            params.append(fts_query)

        if extension:
            clean_ext = extension.lstrip(".").lower()
            where_clauses.append("f.ext = ?")
            params.append(clean_ext)

        if path_filter:
            where_clauses.append("f.path LIKE ?")
            params.append(f"%{path_filter}%")

        if min_size is not None and min_size > 0:
            where_clauses.append("f.size_bytes >= ?")
            params.append(min_size)

        if max_size is not None and max_size > 0:
            where_clauses.append("f.size_bytes <= ?")
            params.append(max_size)

        if modified_days is not None and modified_days > 0:
            cutoff_ts = int((datetime.now() - timedelta(days=modified_days)).timestamp())
            where_clauses.append("f.modified_ts >= ?")
            params.append(cutoff_ts)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        sql = f"""
            SELECT f.id, f.path, f.name, f.ext, f.size_bytes, f.modified_ts, f.is_dir
            FROM file_index f
            {where_sql}
            ORDER BY f.is_dir DESC, f.name ASC
            LIMIT ?
        """
        params.append(min(max(limit, 1), 500))

        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            mod_dt = datetime.fromtimestamp(r["modified_ts"]).strftime("%Y-%m-%d %H:%M:%S") if r["modified_ts"] else "Unknown"
            size_str = "Folder" if r["is_dir"] else _format_size(r["size_bytes"])
            results.append({
                "id": r["id"],
                "path": r["path"],
                "name": r["name"],
                "ext": r["ext"],
                "size_bytes": r["size_bytes"],
                "size_formatted": size_str,
                "modified": mod_dt,
                "is_dir": bool(r["is_dir"])
            })

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return {
            "query": clean_query,
            "total": len(results),
            "duration_ms": elapsed_ms,
            "results": results
        }
    finally:
        conn.close()

def _format_size(bytes_val: int) -> str:
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{round(bytes_val / 1024.0, 1)} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{round(bytes_val / (1024.0 * 1024.0), 1)} MB"
    else:
        return f"{round(bytes_val / (1024.0 * 1024.0 * 1024.0), 2)} GB"

def open_file_in_windows(path: str) -> Dict[str, Any]:
    """Safely open file or folder using native Windows shell association."""
    if not os.path.exists(path):
        return {"success": False, "message": f"File does not exist: {path}"}
    try:
        os.startfile(path)
        return {"success": True, "message": f"Opened {path}"}
    except Exception as e:
        return {"success": False, "message": f"Error opening file: {e}"}

def open_folder_in_explorer(path: str) -> Dict[str, Any]:
    """Open Windows Explorer with file or folder selected."""
    if not os.path.exists(path):
        return {"success": False, "message": f"Path does not exist: {path}"}
    try:
        if os.path.isdir(path):
            subprocess.Popen(["explorer.exe", path])
        else:
            subprocess.Popen(["explorer.exe", f"/select,{path}"])
        return {"success": True, "message": f"Opened in Explorer: {path}"}
    except Exception as e:
        return {"success": False, "message": f"Error opening Explorer: {e}"}

def get_search_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve recent file search queries."""
    init_search_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, query, timestamp FROM search_history ORDER BY id DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "query": r["query"], "timestamp": r["timestamp"]} for r in cursor.fetchall()]
    finally:
        conn.close()

def clear_search_history() -> Dict[str, Any]:
    """Clear file search query history."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM search_history")
        conn.commit()
        return {"success": True, "message": "Search history cleared."}
    finally:
        conn.close()
