"""
SYSFIX Background Monitor Orchestrator
Coordinates background polling threads for CPU/RAM telemetry, storage health,
Windows event logs, network status, and alert evaluation.
Supports pause, resume, manual refresh, and clean termination.
"""

import time
import threading
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from backend.core.metrics import collect_all_metrics, get_top_processes
from backend.core.storage import get_drive_health_list
from backend.core.events import get_recent_windows_events
from backend.core.network import run_comprehensive_network_diagnosis
from backend.core.alerts import evaluate_system_alerts
from backend.core.scheduler import check_and_execute_scheduled_tasks
from backend.core.driver_alerts import evaluate_driver_fault_and_alert_async
from backend.database import record_metric_snapshot, get_setting

logger = logging.getLogger("SYSFIX.Monitor")

class BackgroundMonitor:
    def __init__(self):
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Shared cached state
        self._cached_metrics: Dict[str, Any] = {}
        self._cached_drives: list = []
        self._cached_events: list = []
        self._cached_network: Dict[str, Any] = {}
        self._cached_processes: list = []
        self._last_metrics_check: Optional[str] = None
        self._last_storage_check: Optional[str] = None
        self._last_events_check: Optional[str] = None
        self._last_network_check: Optional[str] = None
        self._is_running = False
        self._bg_init_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts background worker thread cleanly."""
        if self._is_running:
            return
        self._stop_event.clear()
        self._pause_event.clear()
        self._is_running = True
        try:
            # Immediate fast collection so initial dashboard metrics are ready instantly
            self.manual_refresh_metrics(include_processes=False)
        except Exception as e:
            logger.warning(f"Immediate metrics collection warning: {e}")
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="SYSFIX-Worker")
        self._bg_init_thread: Optional[threading.Thread] = None
        self._thread.start()
        logger.info("SYSFIX Background Monitor thread started.")

    def stop(self) -> None:
        """Signals worker thread to stop cleanly."""
        self._stop_event.set()
        self._pause_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._bg_init_thread and self._bg_init_thread.is_alive():
            self._bg_init_thread.join(timeout=1.0)
        self._is_running = False
        logger.info("SYSFIX Background Monitor thread stopped.")

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def manual_refresh_metrics(self, include_processes: bool = True) -> Dict[str, Any]:
        """Trigger an immediate synchronous refresh of metrics."""
        try:
            m = collect_all_metrics()
            with self._lock:
                self._cached_metrics = m
                self._last_metrics_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if include_processes:
                procs = get_top_processes(limit=15)
                with self._lock:
                    self._cached_processes = procs
            return m
        except Exception as e:
            logger.error(f"Manual metrics refresh error: {e}")
            return self._cached_metrics

    def manual_refresh_processes(self) -> list:
        try:
            procs = get_top_processes(limit=15)
            with self._lock:
                self._cached_processes = procs
            return procs
        except Exception as e:
            logger.error(f"Manual processes refresh error: {e}")
            return self._cached_processes

    def manual_refresh_storage(self) -> list:
        try:
            d = get_drive_health_list()
            with self._lock:
                self._cached_drives = d
                self._last_storage_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return d
        except Exception as e:
            logger.error(f"Manual storage refresh error: {e}")
            return self._cached_drives

    def manual_refresh_network(self) -> Dict[str, Any]:
        try:
            n = run_comprehensive_network_diagnosis()
            with self._lock:
                self._cached_network = n
                self._last_network_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return n
        except Exception as e:
            logger.error(f"Manual network refresh error: {e}")
            return self._cached_network

    def manual_refresh_events(self) -> list:
        try:
            ev = get_recent_windows_events(max_per_log=30)
            with self._lock:
                self._cached_events = ev
                self._last_events_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return ev
        except Exception as e:
            logger.error(f"Manual events refresh error: {e}")
            return self._cached_events

    def get_snapshot(self) -> Dict[str, Any]:
        """Provides thread-safe atomic view of latest monitoring data."""
        with self._lock:
            return {
                "metrics": self._cached_metrics,
                "drives": self._cached_drives,
                "events": self._cached_events,
                "network": self._cached_network,
                "processes": self._cached_processes,
                "last_metrics_check": self._last_metrics_check,
                "last_storage_check": self._last_storage_check,
                "last_events_check": self._last_events_check,
                "last_network_check": self._last_network_check,
                "is_paused": self.is_paused()
            }

    def _worker_loop(self) -> None:
        last_fast_tick = 0.0
        last_slow_tick = 0.0
        last_net_tick = 0.0
        last_schedule_tick = 0.0
        last_driver_tick = 0.0

        # Initial fast collection on launch
        try:
            self.manual_refresh_metrics()
        except Exception as e:
            logger.error(f"Initial metrics collection warning: {e}")

        # Non-blocking asynchronous initial collection of storage, network, and event logs
        def _initial_slow_collection():
            if self._stop_event.is_set():
                return
            try:
                self.manual_refresh_processes()
            except Exception as e:
                logger.warning(f"Initial processes background check warning: {e}")

            if self._stop_event.is_set():
                return
            try:
                self.manual_refresh_storage()
            except Exception as e:
                logger.warning(f"Initial storage background check warning: {e}")

            if self._stop_event.is_set():
                return
            try:
                self.manual_refresh_network()
            except Exception as e:
                logger.warning(f"Initial network background check warning: {e}")

            if self._stop_event.is_set():
                return
            try:
                self.manual_refresh_events()
            except Exception as e:
                logger.warning(f"Initial events background check warning: {e}")

        self._bg_init_thread = threading.Thread(target=_initial_slow_collection, daemon=True, name="TERMINAL-InitialBg")
        self._bg_init_thread.start()

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(1.0)
                continue

            now = time.time()
            interval_sec = float(get_setting("monitor_interval_sec", "3"))

            # 1. Fast tick (CPU, RAM, Battery, Procs)
            if now - last_fast_tick >= interval_sec:
                try:
                    m = collect_all_metrics()
                    procs = get_top_processes(limit=15)
                    with self._lock:
                        self._cached_metrics = m
                        self._cached_processes = procs
                        self._last_metrics_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Record to SQLite
                    record_metric_snapshot({
                        "cpu_percent": m["cpu"]["percent"],
                        "ram_percent": m["ram"]["percent"],
                        "ram_used_bytes": m["ram"]["used_bytes"],
                        "ram_total_bytes": m["ram"]["total_bytes"],
                        "battery_percent": m["battery"]["percent"],
                        "is_charging": m["battery"]["is_charging"],
                        "disk_free_gb": m["disk_free_gb"]
                    })

                    # Evaluate alert conditions
                    evaluate_system_alerts(m, self._cached_drives, self._cached_network)
                except Exception as e:
                    logger.error(f"Error in metrics loop: {e}")
                last_fast_tick = now

            # 2. Medium tick (Network - every 12 seconds)
            if now - last_net_tick >= 12.0:
                try:
                    self.manual_refresh_network()
                except Exception as e:
                    logger.error(f"Error in network loop: {e}")
                last_net_tick = now

            # 3. Slow tick (Drives & Windows Event Log - every 30 seconds)
            if now - last_slow_tick >= 30.0:
                try:
                    self.manual_refresh_storage()
                    self.manual_refresh_events()
                except Exception as e:
                    logger.error(f"Error in slow storage/event loop: {e}")
                last_slow_tick = now

            # 4. Schedule & queue tick (Daily 7:00 PM check & offline queue drain - every 30 seconds)
            if now - last_schedule_tick >= 30.0:
                try:
                    check_and_execute_scheduled_tasks()
                except Exception as e:
                    logger.error(f"Error in scheduler tick: {e}")
                last_schedule_tick = now

            # 5. Driver health & faulty driver alerts tick (every 60 seconds)
            if now - last_driver_tick >= 60.0:
                try:
                    evaluate_driver_fault_and_alert_async(self._cached_events)
                except Exception as e:
                    logger.error(f"Error evaluating driver faults: {e}")
                last_driver_tick = now

            time.sleep(1.0)

# Global monitor instance
global_monitor = BackgroundMonitor()
