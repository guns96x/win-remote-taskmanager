"""
Direct ASUS TUF Hardware Monitor & Controller.
Interfaces with ASUS ATKACPI kernel driver and the local asus-pc-agent (port 8765)
with G-Helper config synchronization and Windows powercfg scheme switching.
"""

import os
import json
import ctypes
import struct
import subprocess
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

IOCTL_ASUS_ATK = 0x0022240C

# ATKACPI Device IDs
DEV_CPU_TEMP = 0x00120094
DEV_CPU_FAN = 0x00110013
DEV_GPU_FAN = 0x00110014
DEV_PERF_MODE = 0x00120075
DEV_KBD_BACKLIGHT = 0x00050021

# Power scheme GUIDs
GUID_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
GUID_HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GUID_POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"

ASUS_AGENT_URL = "http://127.0.0.1:8765"
ASUS_AGENT_TOKEN = "3f0f6c5206aafe05231c8c97034cd2cb"


class AsusHardware:
    def __init__(self):
        self._available = True
        self._cached_keyboard_level = 0
        self._cached_perf_mode = 1  # 0: Balanced, 1: Turbo, 2: Silent
        self._cached_screen_sleeping = False

    def _call_atk(self, method: int, dev_id: int, value: int = 0) -> Optional[int]:
        """Direct IOCTL call to \\.\\ATKACPI kernel driver."""
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
            # 16-byte buffer: [method, arg_size=8, dev_id, value]
            in_buf = struct.pack("<IIII", method, 8, dev_id, value)
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

    def read_dev(self, dev_id: int) -> Optional[int]:
        return self._call_atk(0x53545344, dev_id, 0)

    def write_dev(self, dev_id: int, value: int) -> bool:
        res = self._call_atk(0x53564544, dev_id, value)
        return (res == 1)

    def _agent_request(self, endpoint: str, method: str = "GET", params: Optional[dict] = None) -> Optional[dict]:
        """Calls local asus-pc-agent if available."""
        url = f"{ASUS_AGENT_URL}{endpoint}"
        if params and method == "GET":
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        
        headers = {
            "Authorization": f"Bearer {ASUS_AGENT_TOKEN}",
            "Content-Type": "application/json"
        }
        data = None
        if params and method == "POST":
            data = json.dumps(params).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        return None

    def get_hardware_status(self) -> Dict[str, Any]:
        """Reads CPU temperature, fan speeds, perf mode, battery, keyboard, and screen state."""
        # 1. ATKACPI Direct Read
        raw_temp = self.read_dev(DEV_CPU_TEMP)
        raw_cpu_fan = self.read_dev(DEV_CPU_FAN)
        raw_gpu_fan = self.read_dev(DEV_GPU_FAN)
        raw_perf = self.read_dev(DEV_PERF_MODE)
        raw_kbd = self.read_dev(DEV_KBD_BACKLIGHT)

        cpu_temp = (raw_temp & 0xFF) if raw_temp is not None else 0
        cpu_fan = ((raw_cpu_fan & 0xFF) * 100) if raw_cpu_fan is not None else 0
        gpu_fan = ((raw_gpu_fan & 0xFF) * 100) if raw_gpu_fan is not None else 0
        perf_mode = (raw_perf & 0xFF) if raw_perf is not None else self._cached_perf_mode

        if raw_kbd is not None and (raw_kbd & 0x10000 != 0):
            self._cached_keyboard_level = raw_kbd & 0x7F

        # Check with G-Helper config for source of truth
        ghelper_mode = self.read_ghelper_mode()
        if ghelper_mode is not None:
            perf_mode = ghelper_mode

        self._cached_perf_mode = perf_mode

        # Check with local agent for battery and monitor sleeping status
        agent_status = self._agent_request("/api/status")
        is_ac_plugged = True
        battery_percent = 100
        is_charging = False
        monitor_sleeping = self._cached_screen_sleeping
        keep_awake_active = True

        if agent_status:
            is_ac_plugged = agent_status.get("is_ac_plugged", True)
            battery_percent = agent_status.get("battery_percent", 100)
            is_charging = agent_status.get("is_charging", False)
            monitor_sleeping = agent_status.get("monitor_sleeping", False)
            self._cached_screen_sleeping = monitor_sleeping
            keep_awake_active = agent_status.get("keep_awake_active", True)
            if "keyboard_level" in agent_status and agent_status["keyboard_level"] >= 0:
                self._cached_keyboard_level = agent_status["keyboard_level"]

        mode_names = {0: "Баланс", 1: "Турбо", 2: "Тихий", 3: "Баланс"}
        mode_keys = {0: "balanced", 1: "turbo", 2: "silent", 3: "balanced"}

        return {
            "cpu_temp_c": cpu_temp,
            "cpu_fan_rpm": cpu_fan,
            "gpu_fan_rpm": gpu_fan,
            "perf_mode_id": perf_mode,
            "perf_mode_key": mode_keys.get(perf_mode, "balanced"),
            "perf_mode_name": mode_names.get(perf_mode, "Баланс"),
            "keyboard_level": self._cached_keyboard_level,
            "monitor_sleeping": monitor_sleeping,
            "is_ac_plugged": is_ac_plugged,
            "battery_percent": battery_percent,
            "is_charging": is_charging,
            "keep_awake_active": keep_awake_active,
            "is_asus": (raw_temp is not None or agent_status is not None)
        }

    def read_ghelper_mode(self) -> Optional[int]:
        """Reads performance mode from %APPDATA%\\GHelper\\config.json."""
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        cfg_path = os.path.join(appdata, "GHelper", "config.json")
        if not os.path.exists(cfg_path):
            return None
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                val = cfg.get("performance_mode")
                if isinstance(val, (int, float)) and int(val) in (0, 1, 2):
                    return int(val)
        except Exception:
            pass
        return None

    def sync_ghelper_config(self, mode: int):
        """Updates G-Helper config so the desktop app reflects the new profile."""
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return
        cfg_path = os.path.join(appdata, "GHelper", "config.json")
        if not os.path.exists(cfg_path):
            return
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["performance_mode"] = mode
            cfg["performance_0"] = mode
            cfg["performance_1"] = mode
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def sync_powercfg(self, mode: int):
        """Sets Windows active power scheme based on performance mode."""
        guid_map = {
            2: GUID_POWER_SAVER,
            1: GUID_HIGH_PERF,
            0: GUID_BALANCED
        }
        guid = guid_map.get(mode)
        if guid:
            try:
                subprocess.run(
                    ["powercfg", "/setactive", guid],
                    capture_output=True,
                    timeout=2.0,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
            except Exception:
                pass

    def set_performance_mode(self, mode: int) -> Dict[str, Any]:
        """Sets ASUS Performance mode (0: Balanced, 1: Turbo, 2: Silent)."""
        if mode not in (0, 1, 2):
            return {"success": False, "error": f"Некоректний режим: {mode} (0: Баланс, 1: Турбо, 2: Тихий)"}

        # 1. Try agent first (handles GHelper and notifications)
        agent_res = self._agent_request(f"/api/performance/mode?mode={mode}", method="POST")
        if not agent_res or not agent_res.get("success"):
            # Direct ATKACPI write
            self.write_dev(DEV_PERF_MODE, mode)
            self.sync_ghelper_config(mode)
            self.sync_powercfg(mode)

        self._cached_perf_mode = mode
        mode_names = {0: "Баланс", 1: "Турбо", 2: "Тихий"}
        return {
            "success": True,
            "mode": mode,
            "mode_name": mode_names.get(mode, "Баланс")
        }

    def set_keyboard_backlight(self, level: int) -> Dict[str, Any]:
        """Sets ASUS keyboard backlight level (0: Off, 1: Low, 2: Med, 3: Max)."""
        if level not in (0, 1, 2, 3):
            return {"success": False, "error": "Яскравість клавіатури має бути від 0 до 3"}

        agent_res = self._agent_request(f"/api/keyboard/level?level={level}", method="POST")
        if not agent_res or not agent_res.get("success"):
            # Direct ATKACPI write (requires bit 7 set: 0x80 | level)
            self.write_dev(DEV_KBD_BACKLIGHT, 0x80 | level)

        self._cached_keyboard_level = level
        return {"success": True, "level": level}

    def toggle_keyboard_backlight(self) -> Dict[str, Any]:
        """Toggles keyboard backlight between Off and Max."""
        next_level = 3 if self._cached_keyboard_level == 0 else 0
        return self.set_keyboard_backlight(next_level)

    def sleep_screen(self) -> Dict[str, Any]:
        """Turns off displays safely without breaking Tailscale / Modern Standby."""
        agent_res = self._agent_request("/api/monitor/sleep", method="POST")
        if agent_res and agent_res.get("success"):
            self._cached_screen_sleeping = True
            return {"success": True, "monitor_sleeping": True, "message": "Екран вимкнено (ноутбук працює у фоні)"}
        return {"success": False, "error": "Служба керування екраном недоступна"}

    def wake_screen(self) -> Dict[str, Any]:
        """Wakes displays and restores panel brightness."""
        agent_res = self._agent_request("/api/monitor/wake", method="POST")
        if agent_res and agent_res.get("success"):
            self._cached_screen_sleeping = False
            return {"success": True, "monitor_sleeping": False, "message": "Екран увімкнено"}
        return {"success": False, "error": "Служба керування екраном недоступна"}

    def toggle_screen(self) -> Dict[str, Any]:
        """Toggles screen between blanked and active."""
        if self._cached_screen_sleeping:
            return self.wake_screen()
        return self.sleep_screen()

    def hibernate_pc(self) -> Dict[str, Any]:
        """Initiates deep S4 hibernation."""
        agent_res = self._agent_request("/api/power/hibernate", method="POST")
        if not agent_res or not agent_res.get("success"):
            try:
                subprocess.run(
                    ["shutdown", "/h"],
                    capture_output=True,
                    timeout=3.0,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "message": "ПК переходить у глибоку гібернацію"}
