"""
ASUS Profile & Silent/Turbo Scheduler.
Allows setting automated time-based rules for ASUS performance modes
(e.g., Silent mode at night, Turbo/Balanced during the day).
Runs as a background ticker on the Windows host.
"""

import os
import json
import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

SCHEDULES_FILE = os.path.join(os.path.dirname(__file__), "schedules.json")


class AsusScheduler:
    def __init__(self, asus_hw):
        self.asus_hw = asus_hw
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_triggered_minute: Optional[str] = None
        self.enabled = True
        self.rules: List[Dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self):
        default_rules = [
            {
                "id": "night-silent",
                "name": "Нічний тихий режим",
                "enabled": True,
                "time": "23:00",
                "mode": 2,  # Silent
                "mode_name": "Тихий (Silent)",
                "keyboard_level": 0,
                "days": [0, 1, 2, 3, 4, 5, 6]
            },
            {
                "id": "day-turbo",
                "name": "Денний турбо режим",
                "enabled": True,
                "time": "09:00",
                "mode": 1,  # Turbo
                "mode_name": "Турбо (Turbo)",
                "keyboard_level": 2,
                "days": [0, 1, 2, 3, 4, 5, 6]
            }
        ]
        if os.path.exists(SCHEDULES_FILE):
            try:
                with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.enabled = data.get("enabled", True)
                    self.rules = data.get("rules", default_rules)
                    return
            except Exception:
                pass
        self.rules = default_rules
        self._save_rules()

    def _save_rules(self):
        try:
            with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
                json.dump({"enabled": self.enabled, "rules": self.rules}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "rules": list(self.rules),
                "current_time": datetime.now().strftime("%H:%M")
            }

    def set_enabled(self, enabled: bool):
        with self._lock:
            self.enabled = enabled
            self._save_rules()

    def add_or_update_rule(self, rule: Dict[str, Any]):
        with self._lock:
            if not rule.get("id"):
                rule["id"] = f"rule-{int(time.time())}"
            t = rule.get("time", "12:00").strip()
            rule["time"] = t
            m = int(rule.get("mode", 0))
            rule["mode"] = m
            names = {0: "Баланс (Balanced)", 1: "Турбо (Turbo)", 2: "Тихий (Silent)"}
            rule["mode_name"] = names.get(m, "Баланс")
            if "enabled" not in rule:
                rule["enabled"] = True
            if "days" not in rule:
                rule["days"] = [0, 1, 2, 3, 4, 5, 6]

            existing = False
            for i, r in enumerate(self.rules):
                if r.get("id") == rule["id"]:
                    self.rules[i] = rule
                    existing = True
                    break
            if not existing:
                self.rules.append(rule)
            self._save_rules()

    def delete_rule(self, rule_id: str):
        with self._lock:
            self.rules = [r for r in self.rules if r.get("id") != rule_id]
            self._save_rules()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            try:
                now = datetime.now()
                cur_minute = now.strftime("%Y-%m-%d %H:%M")
                cur_time = now.strftime("%H:%M")
                cur_day = now.weekday()  # 0 = Monday ... 6 = Sunday

                if self.enabled and cur_minute != self._last_triggered_minute:
                    with self._lock:
                        for rule in self.rules:
                            if not rule.get("enabled", True):
                                continue
                            if rule.get("time") == cur_time:
                                days = rule.get("days", [0, 1, 2, 3, 4, 5, 6])
                                if cur_day in days:
                                    mode = rule.get("mode", 0)
                                    self.asus_hw.set_performance_mode(mode)
                                    if "keyboard_level" in rule and rule["keyboard_level"] is not None:
                                        self.asus_hw.set_keyboard_backlight(rule["keyboard_level"])
                                    self._last_triggered_minute = cur_minute
                                    break
            except Exception:
                pass
            time.sleep(15)
