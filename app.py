"""
TERMINAL BOARD — Complete Windows System Diagnostics & Health Monitoring Application
Main Desktop Application Entry Point
"""

import sys
import os
import atexit
import argparse
import logging
import threading
import socket

# Add root folder to sys.path so modules import reliably
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.database import init_db
from backend.monitor import global_monitor
from backend.api import SYSFIXApi, create_flask_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TERMINAL_BOARD.Main")

def get_resource_path(relative_path: str) -> str:
    """Resolve an asset or resource path across development and PyInstaller frozen states."""
    if getattr(sys, 'frozen', False):
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        candidates = [
            os.path.join(base_dir, relative_path),
            os.path.join(os.path.dirname(sys.executable), '_internal', relative_path),
            os.path.join(os.path.dirname(sys.executable), relative_path),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return os.path.join(ROOT_DIR, relative_path)

def get_frontend_dir() -> str:
    """Locate frontend assets whether running from source or PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        for candidate in [
            os.path.join(base_dir, 'frontend'),
            os.path.join(os.path.dirname(sys.executable), '_internal', 'frontend'),
            os.path.join(os.path.dirname(sys.executable), 'frontend')
        ]:
            if os.path.isdir(candidate):
                return candidate
    return os.path.join(ROOT_DIR, "frontend")

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if local TCP port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def find_available_port(start_port: int = 5055, host: str = "127.0.0.1") -> int:
    """Find an available port starting from start_port."""
    port = start_port
    while port < start_port + 100:
        if not is_port_in_use(port, host):
            return port
        port += 1
    return start_port

from backend.core.subproc import cleanup_child_processes

_single_instance_mutex = None

def check_single_instance() -> bool:
    """Ensure only one interactive instance of TERMINAL BOARD runs concurrently."""
    global _single_instance_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Local\\TERMINAL_BOARD_SINGLETON_MUTEX"
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            if mutex:
                kernel32.CloseHandle(mutex)
            return False
        _single_instance_mutex = mutex
        return True
    except Exception as e:
        logger.warning(f"Single-instance check warning: {e}")
        return True

def activate_existing_window():
    """Focus existing window if another instance was launched."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "TERMINAL BOARD — Windows Diagnostics & System Health")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

def cleanup():
    """Ensure background threads and child processes terminate cleanly upon exit."""
    logger.info("Initiating TERMINAL BOARD clean shutdown...")
    try:
        global_monitor.stop()
    except Exception as e:
        logger.warning(f"Error stopping monitor: {e}")

    try:
        cleanup_child_processes()
    except Exception as e:
        logger.warning(f"Error cleaning up child processes: {e}")

    global _single_instance_mutex
    if _single_instance_mutex and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_single_instance_mutex)
            _single_instance_mutex = None
        except Exception:
            pass

atexit.register(cleanup)

def main():
    parser = argparse.ArgumentParser(description="TERMINAL BOARD — Windows System Diagnostics & Health Monitor")
    parser.add_argument("--web", action="store_true", help="Launch in local browser mode via HTTP server")
    parser.add_argument("--port", type=int, default=5055, help="Port for local HTTP server (default: 5055)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--headless", action="store_true", help="Run background collection once and exit")
    parser.add_argument("--send-daily-report", action="store_true", help="Generate and dispatch daily 7:00 PM full-system diagnostic email report, then exit")
    parser.add_argument("--check-driver-alerts", action="store_true", help="Evaluate hardware driver faults and alert if critical, then exit")
    parser.add_argument("--hardware-scan", action="store_true", help="Execute complete hardware discovery and health assessment from command line, then exit")
    parser.add_argument("--detailed-scan", action="store_true", help="Execute detailed hardware scan including active diagnostic stress tests")
    parser.add_argument("--export-report", type=str, choices=["json", "txt", "html", "all"], default="all", help="Export hardware diagnostic report format (default: all)")
    args = parser.parse_args()

    # 1. Initialize SQLite Database
    logger.info("Initializing SQLite database...")
    init_db()

    # Dedicated CLI Tasks (Exit immediately, do not start persistent telemetry or UI)
    if args.send_daily_report:
        logger.info("Executing scheduled/headless daily report dispatch...")
        try:
            from backend.core.email_reports import send_daily_full_system_report
            success, msg = send_daily_full_system_report(manual=False)
            logger.info(f"Report dispatch result: success={success}, msg={msg}")
            return 0 if success else 1
        except Exception as e:
            logger.error(f"Error during daily report execution: {e}")
            return 1
        finally:
            cleanup()

    if args.check_driver_alerts:
        logger.info("Executing driver fault check...")
        try:
            from backend.core.driver_alerts import evaluate_driver_fault_and_alert
            dispatched = evaluate_driver_fault_and_alert()
            logger.info(f"Dispatched {len(dispatched)} driver alerts.")
            return 0
        except Exception as e:
            logger.error(f"Error during driver fault check: {e}")
            return 1
        finally:
            cleanup()

    if args.hardware_scan or args.detailed_scan:
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.AttachConsole(-1)
            except Exception:
                pass
        mode = "detailed" if args.detailed_scan else "fast"
        logger.info(f"Executing CLI {mode.upper()} hardware diagnostic assessment...")
        try:
            from backend.core.hardware_diagnostics import run_hardware_assessment
            from backend.core.fault_correlation import correlate_faults
            from backend.core.hardware_report import (
                build_full_report_model, export_report_json, export_report_txt, export_report_html
            )
            from backend.core.driver_inventory import get_complete_driver_inventory

            def _cli_progress(pct, stage, test):
                print(f"[{pct:>3}%] {stage}: {test}")

            assess_res = run_hardware_assessment(scan_type=mode, progress_callback=_cli_progress)
            drivers = get_complete_driver_inventory()
            findings = correlate_faults(assess_res["inventory"], assess_res["error_events"], assess_res["diagnostic_tests"], drivers)
            report = build_full_report_model(assess_res, findings)

            fmt = args.export_report
            if fmt in ("json", "all"):
                jp = export_report_json(report)
                print(f"[EXPORT] JSON report: {jp}")
            if fmt in ("txt", "all"):
                tp = export_report_txt(report)
                print(f"[EXPORT] TXT report: {tp}")
            if fmt in ("html", "all"):
                hp = export_report_html(report)
                print(f"[EXPORT] HTML report: {hp}")

            print(f"\n[SUMMARY] Overall Health: {report['report_metadata']['overall_status']} | Components: {len(report['section_3_hardware_inventory'])} | Findings: {len(findings)}")
            return 0
        except Exception as e:
            logger.error(f"Error during CLI hardware scan: {e}")
            return 1
        finally:
            cleanup()

    # Prevent multiple redundant GUI/desktop instances
    if not args.headless and not args.web:
        if not check_single_instance():
            logger.info("Another instance of TERMINAL BOARD is already running. Focusing existing window and exiting.")
            activate_existing_window()
            return 0

    # 2. Start Background Telemetry Monitor for active application session
    logger.info("Starting background telemetry worker...")
    global_monitor.start()

    frontend_dir = get_frontend_dir()
    logger.info(f"Loaded frontend assets from: {frontend_dir}")

    if args.headless:
        logger.info("Headless diagnostic run complete.")
        cleanup()
        return 0

    actual_port = args.port
    if is_port_in_use(actual_port, args.host):
        actual_port = find_available_port(args.port + 1, args.host)
        logger.info(f"Port {args.port} in use; switched to available port {actual_port}")

    if args.web:
        # Browser HTTP mode
        logger.info(f"Starting TERMINAL BOARD web interface on http://{args.host}:{actual_port}")
        app = create_flask_app(frontend_dir)
        try:
            import webbrowser
            threading.Timer(0.8, lambda: webbrowser.open(f"http://{args.host}:{actual_port}")).start()
            app.run(host=args.host, port=actual_port, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("Stopping TERMINAL BOARD HTTP server...")
        finally:
            cleanup()
        return 0

    # Native Desktop Window via PyWebView
    try:
        import webview
        import time
        logger.info("Creating native desktop window via PyWebView...")

        # Start background Flask server on local port for robust asset loading & REST fallback
        flask_app = create_flask_app(frontend_dir)
        server_thread = threading.Thread(
            target=lambda: flask_app.run(host="127.0.0.1", port=actual_port, debug=False, use_reloader=False),
            daemon=True
        )
        server_thread.start()
        time.sleep(0.3)  # Ensure port is bound before webview connects

        # Desktop Window Settings (Optimized for 1366x768 / 1440x900 / 1920x1080)
        api_instance = SYSFIXApi()
        window = webview.create_window(
            title="TERMINAL BOARD — Windows Diagnostics & System Health",
            url=f"http://127.0.0.1:{actual_port}",
            js_api=api_instance,
            width=1366,
            height=768,
            min_size=(1024, 640),
            background_color="#080F20",
            text_select=False
        )

        def on_closing():
            logger.info("Main window closing, running cleanup...")
            cleanup()

        window.events.closing += on_closing

        webview.start(debug=False)
    except Exception as e:
        logger.warning(f"PyWebView native window could not be initialized: {e}. Falling back to browser view...")
        # Fallback to Flask web view
        app = create_flask_app(frontend_dir)
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{actual_port}")).start()
        try:
            app.run(host="127.0.0.1", port=actual_port, debug=False, use_reloader=False)
        finally:
            cleanup()
    finally:
        cleanup()

    return 0

if __name__ == "__main__":
    sys.exit(main())
