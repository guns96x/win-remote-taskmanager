"""
Process Manager: tracks processes, normalizes CPU, calculates IO rates,
caches static process metadata, and provides safe kill capabilities.
"""

import time
import threading
from typing import Dict, Any, List, Optional
import psutil

CRITICAL_NAMES = {
    "system idle process",
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "winlogon.exe",
    "fontdrvhost.exe",
}

WINDOWS_SYSTEM_NAMES = {
    "svchost.exe",
    "dwm.exe",
    "sihost.exe",
    "taskhostw.exe",
    "ctfmon.exe",
    "conhost.exe",
    "explorer.exe",
    "spoolsv.exe",
    "searchindexer.exe",
    "securityhealthservice.exe",
    "smartscreen.exe",
    "runtimebroker.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "systemsettings.exe",
}


class ProcessManager:
    def __init__(self, update_interval: float = 1.5):
        self.update_interval = update_interval
        self.cores_logical = psutil.cpu_count(logical=True) or 1
        self._meta_cache: Dict[int, tuple[str, str, float, str]] = {}  # pid -> (exe, username, create_time, category)
        self._last_io: Dict[int, tuple[float, float, float]] = {}  # pid -> (read_bytes, write_bytes, timestamp)
        self._latest_list: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self.total_threads = 0
        self.total_handles = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run_loop(self):
        # Initial seeding
        self._scan_processes()
        while self._running:
            start_t = time.time()
            self._scan_processes()
            elapsed = time.time() - start_t
            sleep_t = max(0.2, self.update_interval - elapsed)
            time.sleep(sleep_t)

    def _categorize(self, name_lower: str, exe_path: str, username: str) -> str:
        if name_lower in CRITICAL_NAMES or name_lower in WINDOWS_SYSTEM_NAMES:
            return "windows"

        path_lower = exe_path.lower()
        if "c:\\windows\\system32" in path_lower or "c:\\windows\\syswow64" in path_lower:
            return "windows"

        user_lower = (username or "").lower()
        if "system" in user_lower or "local service" in user_lower or "network service" in user_lower:
            return "background"

        if "program files" in path_lower or "appdata" in path_lower or "users" in path_lower:
            return "app"

        return "background"

    def _scan_processes(self):
        now = time.time()
        collected: List[Dict[str, Any]] = []
        vmem = psutil.virtual_memory()
        total_ram_mb = vmem.total / (1024 * 1024)

        seen_pids = set()
        thread_accum = 0

        # Scan processes
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                pid = proc.info['pid']
                if pid == 0:
                    continue
                seen_pids.add(pid)

                name = proc.info.get('name') or f"PID {pid}"
                name_lower = name.lower()
                is_critical = pid in (0, 4) or name_lower in CRITICAL_NAMES

                # Normalized CPU %
                raw_cpu = proc.cpu_percent(interval=None)
                normalized_cpu = round(raw_cpu / self.cores_logical, 1)

                # Memory
                mem_info = proc.memory_info()
                rss_mb = round(mem_info.rss / (1024 * 1024), 1)
                mem_percent = round((rss_mb / total_ram_mb) * 100.0, 1)

                # Static metadata cached by PID
                if pid in self._meta_cache:
                    exe_path, username, create_t, category = self._meta_cache[pid]
                else:
                    try:
                        exe_path = proc.exe()
                    except Exception:
                        exe_path = ""
                    try:
                        username = proc.username()
                    except Exception:
                        username = ""
                    try:
                        create_t = proc.create_time()
                    except Exception:
                        create_t = 0
                    category = self._categorize(name_lower, exe_path, username)
                    self._meta_cache[pid] = (exe_path, username, create_t, category)

                # Disk IO rate
                disk_mbps = 0.0
                try:
                    io = proc.io_counters()
                    if pid in self._last_io:
                        prev_r, prev_w, prev_t = self._last_io[pid]
                        dt = max(0.001, now - prev_t)
                        delta_bytes = (io.read_bytes - prev_r) + (io.write_bytes - prev_w)
                        disk_mbps = round(max(0.0, delta_bytes / dt / (1024 * 1024)), 2)
                    self._last_io[pid] = (io.read_bytes, io.write_bytes, now)
                except Exception:
                    pass

                try:
                    num_th = proc.num_threads()
                    thread_accum += num_th
                except Exception:
                    pass

                collected.append({
                    "pid": pid,
                    "name": name,
                    "cpu": normalized_cpu,
                    "raw_cpu": round(raw_cpu, 1),
                    "memory_mb": rss_mb,
                    "memory_percent": mem_percent,
                    "disk_mbps": disk_mbps,
                    "category": category,
                    "status": "running",
                    "username": username,
                    "exe": exe_path,
                    "is_critical": is_critical,
                    "create_time": create_t
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        # Evict dead PIDs from caches
        for dead_pid in list(self._meta_cache.keys()):
            if dead_pid not in seen_pids:
                del self._meta_cache[dead_pid]
        for dead_pid in list(self._last_io.keys()):
            if dead_pid not in seen_pids:
                del self._last_io[dead_pid]

        with self._lock:
            self._latest_list = collected
            if thread_accum > 0:
                self.total_threads = thread_accum

    def get_processes(
        self,
        sort_by: str = "cpu",
        reverse: bool = True,
        search: str = "",
        category: Optional[str] = None,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        with self._lock:
            procs = list(self._latest_list)

        if search:
            q = search.lower().strip()
            procs = [
                p for p in procs
                if q in p["name"].lower() or q in str(p["pid"]) or q in p["username"].lower()
            ]

        if category and category != "all":
            procs = [p for p in procs if p["category"] == category]

        sort_key_map = {
            "cpu": lambda p: p["cpu"],
            "memory": lambda p: p["memory_mb"],
            "disk": lambda p: p["disk_mbps"],
            "name": lambda p: p["name"].lower(),
            "pid": lambda p: p["pid"]
        }
        key_fn = sort_key_map.get(sort_by, lambda p: p["cpu"])
        procs.sort(key=key_fn, reverse=reverse)

        return procs[:limit]

    def kill_process(self, pid: int, force: bool = False) -> Dict[str, Any]:
        if pid in (0, 4):
            return {"success": False, "error": "Заборонено завершувати системні процеси ядра (PID 0, 4)."}

        try:
            proc = psutil.Process(pid)
            name_lower = (proc.name() or "").lower()
            if name_lower in CRITICAL_NAMES:
                return {"success": False, "error": f"Заборонено завершувати критичний процес Windows ({proc.name()})."}

            if force:
                proc.kill()
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except psutil.TimeoutExpired:
                    proc.kill()

            return {"success": True, "message": f"Процес {name_lower} (PID {pid}) успішно завершено."}
        except psutil.NoSuchProcess:
            return {"success": True, "message": f"Процес (PID {pid}) вже завершився."}
        except psutil.AccessDenied:
            try:
                import subprocess
                cmd = ["taskkill", "/f", "/pid", str(pid)]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0:
                    return {"success": True, "message": f"Процес {pid} завершено через taskkill."}
                else:
                    return {"success": False, "error": f"Відмовлено в доступі. ({res.stderr.strip()})"}
            except Exception as e:
                return {"success": False, "error": f"Відмовлено в доступі для PID {pid}: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Помилка при завершенні: {e}"}
