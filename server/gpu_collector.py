"""
GPU Metrics Collector supporting both NVIDIA dGPU and Intel Iris Xe iGPU.
Uses nvidia-smi for NVIDIA RTX and Windows PDH / DXGI for Intel Iris Xe.
"""

import subprocess
import time
import winreg
from typing import Optional, Dict, Any, List

try:
    import win32pdh
    HAS_WIN32PDH = True
except ImportError:
    HAS_WIN32PDH = False


class GPUCollector:
    def __init__(self, cache_ttl: float = 0.8):
        self.cache_ttl = cache_ttl
        self._last_check_nvidia = 0.0
        self._last_check_intel = 0.0
        self._cached_nvidia: Optional[Dict[str, Any]] = None
        self._cached_intel: Optional[Dict[str, Any]] = None
        self._has_nvidia = True

        # Intel Iris Xe Info
        self.intel_name, self.intel_driver = self._detect_intel_gpu_info()
        self.intel_luid = "114e2"  # Intel Iris Xe LUID hex substring

        # Windows PDH for Intel GPU
        self._pdh_query = None
        self._pdh_engine = None
        self._pdh_memory = None
        self._pdh_initialized = False
        if HAS_WIN32PDH:
            self._init_pdh()

    def _detect_intel_gpu_info(self) -> tuple[str, str]:
        """Reads Intel GPU brand and driver version from Windows registry."""
        try:
            base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
            for i in range(winreg.QueryInfoKey(key)[0]):
                sub = winreg.EnumKey(key, i)
                if sub.isdigit():
                    try:
                        sk = winreg.OpenKey(key, sub)
                        desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                        if "intel" in desc.lower() or "iris" in desc.lower():
                            ver, _ = winreg.QueryValueEx(sk, "DriverVersion")
                            return str(desc).strip(), str(ver).strip()
                    except Exception:
                        pass
        except Exception:
            pass
        return "Intel(R) Iris(R) Xe Graphics", "32.0.101.6790"

    def _init_pdh(self):
        try:
            self._pdh_query = win32pdh.OpenQuery()
            self._pdh_engine = win32pdh.AddCounter(self._pdh_query, r"\GPU Engine(*)\Utilization Percentage")
            self._pdh_memory = win32pdh.AddCounter(self._pdh_query, r"\GPU Adapter Memory(*)\Shared Usage")
            win32pdh.CollectQueryData(self._pdh_query)
            self._pdh_initialized = True
        except Exception:
            self._pdh_initialized = False

    def get_gpu_metrics(self) -> Dict[str, Any]:
        """Returns NVIDIA RTX metrics (primary dGPU)."""
        now = time.time()
        if self._cached_nvidia is not None and (now - self._last_check_nvidia) < self.cache_ttl:
            return self._cached_nvidia

        if self._has_nvidia:
            try:
                cmd = [
                    'nvidia-smi',
                    '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,driver_version',
                    '--format=csv,noheader,nounits'
                ]
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                )
                if res.returncode == 0 and res.stdout.strip():
                    parts = [p.strip() for p in res.stdout.strip().split(',')]
                    if len(parts) >= 6:
                        self._cached_nvidia = {
                            'name': parts[0],
                            'type': 'discrete',
                            'load': max(0.0, min(100.0, float(parts[1]))),
                            'memory_used_mb': float(parts[2]),
                            'memory_total_mb': float(parts[3]),
                            'memory_percent': round((float(parts[2]) / max(1.0, float(parts[3]))) * 100.0, 1),
                            'temp_c': float(parts[4]),
                            'driver': parts[5],
                            'available': True
                        }
                        self._last_check_nvidia = now
                        return self._cached_nvidia
            except FileNotFoundError:
                self._has_nvidia = False
            except Exception:
                pass

        if self._cached_nvidia is None:
            self._cached_nvidia = {
                'name': 'NVIDIA GeForce RTX 3050 Laptop GPU',
                'type': 'discrete',
                'load': 0.0,
                'memory_used_mb': 0.0,
                'memory_total_mb': 4096.0,
                'memory_percent': 0.0,
                'temp_c': 0.0,
                'driver': 'N/A',
                'available': False
            }
        self._last_check_nvidia = now
        return self._cached_nvidia

    def get_igpu_metrics(self, cpu_temp_c: float = 0.0) -> Dict[str, Any]:
        """Returns Intel Iris Xe Graphics metrics (iGPU)."""
        now = time.time()
        if self._cached_intel is not None and (now - self._last_check_intel) < self.cache_ttl:
            # Update temp from CPU if provided
            if cpu_temp_c > 0:
                self._cached_intel['temp_c'] = cpu_temp_c
            return self._cached_intel

        load = 0.0
        shared_mb = 0.0
        total_shared_mb = 16194.0  # ~16GB max shared RAM

        if self._pdh_initialized and self._pdh_query:
            try:
                win32pdh.CollectQueryData(self._pdh_query)
                res_eng = win32pdh.GetFormattedCounterArray(self._pdh_engine, win32pdh.PDH_FMT_DOUBLE)
                res_mem = win32pdh.GetFormattedCounterArray(self._pdh_memory, win32pdh.PDH_FMT_LARGE)

                load = sum(v for k, v in res_eng.items() if self.intel_luid in k.lower())
                load = max(0.0, min(100.0, round(load, 1)))

                shared_bytes = sum(v for k, v in res_mem.items() if self.intel_luid in k.lower())
                shared_mb = round(shared_bytes / (1024 * 1024), 1)
            except Exception:
                pass

        # Since Iris Xe is on the CPU die, its temperature is the package/CPU temperature
        temp_c = cpu_temp_c if cpu_temp_c > 0 else 55.0

        self._cached_intel = {
            'name': self.intel_name,
            'type': 'integrated',
            'load': load,
            'memory_used_mb': shared_mb,
            'memory_total_mb': total_shared_mb,
            'memory_percent': round((shared_mb / max(1.0, total_shared_mb)) * 100.0, 1),
            'temp_c': temp_c,
            'driver': self.intel_driver,
            'available': True
        }
        self._last_check_intel = now
        return self._cached_intel

    def get_all_gpus(self, cpu_temp_c: float = 0.0) -> List[Dict[str, Any]]:
        """Returns list of all available GPUs (Intel Iris Xe + NVIDIA RTX)."""
        gpus = []
        igpu = self.get_igpu_metrics(cpu_temp_c=cpu_temp_c)
        if igpu and igpu.get('available'):
            gpus.append(igpu)

        dgpu = self.get_gpu_metrics()
        if dgpu and dgpu.get('available'):
            gpus.append(dgpu)
        return gpus
