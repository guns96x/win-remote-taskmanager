"""
Remote Windows Power & Session Management.
"""

import subprocess
from typing import Dict, Any

def execute_cmd(args: list[str]) -> Dict[str, Any]:
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=3.0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        if res.returncode == 0:
            return {"success": True, "message": "Команду успішно виконано"}
        return {"success": False, "error": res.stderr.strip() or f"Код виходу {res.returncode}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def lock_workstation() -> Dict[str, Any]:
    return execute_cmd(["rundll32.exe", "user32.dll,LockWorkStation"])

def sleep_pc() -> Dict[str, Any]:
    return execute_cmd(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])

def restart_pc(delay_sec: int = 5) -> Dict[str, Any]:
    return execute_cmd(["shutdown", "/r", "/t", str(delay_sec), "/c", "Віддалене перезавантаження з Android"])

def shutdown_pc(delay_sec: int = 5) -> Dict[str, Any]:
    return execute_cmd(["shutdown", "/s", "/t", str(delay_sec), "/c", "Віддалене завершення роботи з Android"])

def cancel_shutdown() -> Dict[str, Any]:
    return execute_cmd(["shutdown", "/a"])
