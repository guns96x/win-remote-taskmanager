"""
Direct ASUS TUF Hardware Monitor via ATKACPI kernel driver.
Reads CPU Temperature, CPU Fan Speed, GPU Fan Speed, and Performance Mode.
"""

import ctypes
import struct
from typing import Dict, Any, Optional

IOCTL_ASUS_ATK = 0x0022240C

DEV_CPU_TEMP = 0x00120094
DEV_CPU_FAN = 0x00110013
DEV_GPU_FAN = 0x00110014
DEV_PERF_MODE = 0x00120075


class AsusHardware:
    def __init__(self):
        self._available = True

    def _call_atk(self, dev_id: int) -> Optional[int]:
        if not self._available:
            return None
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateFileW(
            r"\\.\ATKACPI",
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE
            3,           # FILE_SHARE_READ | FILE_SHARE_WRITE
            None,
            3,           # OPEN_EXISTING
            0,
            None
        )
        if h == -1 or h == 0xFFFFFFFF:
            self._available = False
            return None

        try:
            in_buf = struct.pack("<IIII", 0x53545344, 8, dev_id, 0)
            out_buf = ctypes.create_string_buffer(16)
            returned = ctypes.c_ulong()
            ok = kernel32.DeviceIoControl(
                h,
                IOCTL_ASUS_ATK,
                in_buf,
                len(in_buf),
                out_buf,
                len(out_buf),
                ctypes.byref(returned),
                None
            )
            if ok and returned.value >= 4:
                return struct.unpack("<I", out_buf.raw[:4])[0]
            return None
        finally:
            kernel32.CloseHandle(h)

    def get_hardware_status(self) -> Dict[str, Any]:
        raw_temp = self._call_atk(DEV_CPU_TEMP)
        raw_cpu_fan = self._call_atk(DEV_CPU_FAN)
        raw_gpu_fan = self._call_atk(DEV_GPU_FAN)
        raw_perf = self._call_atk(DEV_PERF_MODE)

        cpu_temp = (raw_temp & 0xFF) if raw_temp is not None else 0
        cpu_fan = ((raw_cpu_fan & 0xFF) * 100) if raw_cpu_fan is not None else 0
        gpu_fan = ((raw_gpu_fan & 0xFF) * 100) if raw_gpu_fan is not None else 0
        perf_mode = (raw_perf & 0xFF) if raw_perf is not None else 0

        # Performance mode name: 0/3: Balanced, 1: Turbo, 2: Silent
        mode_names = {0: "Баланс", 1: "Турбо", 2: "Тихий", 3: "Баланс"}
        mode_name = mode_names.get(perf_mode, "Баланс")

        return {
            "cpu_temp_c": cpu_temp,
            "cpu_fan_rpm": cpu_fan,
            "gpu_fan_rpm": gpu_fan,
            "perf_mode_id": perf_mode,
            "perf_mode_name": mode_name,
            "is_asus": (raw_temp is not None)
        }
