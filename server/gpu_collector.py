"""
GPU Metrics Collector using nvidia-smi with caching and graceful fallbacks.
"""

import subprocess
import time
from typing import Optional, Dict, Any

class GPUCollector:
    def __init__(self, cache_ttl: float = 0.9):
        self.cache_ttl = cache_ttl
        self._last_check = 0.0
        self._cached_data: Optional[Dict[str, Any]] = None
        self._has_nvidia = True

    def get_gpu_metrics(self) -> Optional[Dict[str, Any]]:
        now = time.time()
        if self._cached_data is not None and (now - self._last_check) < self.cache_ttl:
            return self._cached_data

        if not self._has_nvidia:
            return self._cached_data

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
                    self._cached_data = {
                        'name': parts[0],
                        'load': max(0.0, min(100.0, float(parts[1]))),
                        'memory_used_mb': float(parts[2]),
                        'memory_total_mb': float(parts[3]),
                        'memory_percent': round((float(parts[2]) / max(1.0, float(parts[3]))) * 100.0, 1),
                        'temp_c': float(parts[4]),
                        'driver': parts[5],
                        'available': True
                    }
                    self._last_check = now
                    return self._cached_data
        except FileNotFoundError:
            self._has_nvidia = False
        except Exception:
            pass

        if self._cached_data is None:
            self._cached_data = {
                'name': 'GPU (Інтегрована або недоступна)',
                'load': 0.0,
                'memory_used_mb': 0.0,
                'memory_total_mb': 0.0,
                'memory_percent': 0.0,
                'temp_c': 0.0,
                'driver': 'N/A',
                'available': False
            }
        self._last_check = now
        return self._cached_data
