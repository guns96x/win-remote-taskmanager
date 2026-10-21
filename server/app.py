"""
FastAPI application for Remote Windows Task Manager.
"""

import io
import asyncio
import socket
import json
import base64
import ssl
import urllib.request
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List

import qrcode
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .collector import MetricsCollector
from .process_manager import ProcessManager
from .power_manager import lock_workstation, sleep_pc, restart_pc, shutdown_pc, cancel_shutdown
from .scheduler import AsusScheduler

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

collector = MetricsCollector(history_length=60, interval=1.0)
process_mgr = ProcessManager(update_interval=1.5)
asus_scheduler = AsusScheduler(collector.asus_hw)
SERVER_PORT = 8899


@asynccontextmanager
async def lifespan(app: FastAPI):
    collector.start()
    process_mgr.start()
    asus_scheduler.start()
    yield
    collector.stop()
    process_mgr.stop()
    asus_scheduler.stop()


app = FastAPI(title="Windows Task Manager Remote", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # Never cache dynamic HTML, JS, CSS, or JSON API responses
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


class KillRequest(BaseModel):
    force: bool = False


class PowerRequest(BaseModel):
    delay_sec: int = 5


class AsusPerfRequest(BaseModel):
    mode: int


class AsusKeyboardRequest(BaseModel):
    level: int


def get_primary_mac() -> str:
    """Finds physical Realtek/Intel Ethernet MAC address for Wake-on-LAN."""
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            iface_low = iface.lower()
            if any(v in iface_low for v in ['vethernet', 'vmnet', 'virtual', 'wsl', 'loopback', 'bluetooth']):
                continue
            if 'ethernet' in iface_low or 'eth' in iface_low:
                for addr in addrs:
                    if getattr(addr, 'family', None) in (psutil.AF_LINK, -1) and addr.address:
                        mac = addr.address.replace('-', ':').upper()
                        if len(mac) == 17 and not mac.startswith('00:00'):
                            return mac
    except Exception:
        pass
    return "E8:9C:25:4C:4C:CA"


@app.get("/api/system")
def get_system_info():
    snap = collector.get_snapshot()
    return {
        "hostname": collector.hostname,
        "local_ip": collector.tailscale_ip,
        "tailscale_ip": collector.tailscale_ip,
        "mac_address": get_primary_mac(),
        "mikrotik_tailscale_ip": "100.95.32.60",
        "mikrotik_lan_ip": "192.168.80.1",
        "port": SERVER_PORT,
        "url": f"http://{collector.tailscale_ip}:{SERVER_PORT}",
        "cpu": snap["cpu"],
        "memory": snap["memory"],
        "gpu": snap["gpu"],
        "igpu": snap.get("igpu"),
        "gpus": snap.get("gpus", []),
        "disk": snap["disk"],
        "network": snap["network"],
        "boot_time": collector.boot_time,
    }


@app.get("/api/metrics")
def get_metrics():
    return collector.get_snapshot()


@app.get("/api/processes")
def get_processes(
    sort_by: str = "cpu",
    reverse: bool = True,
    search: str = "",
    category: Optional[str] = None,
    limit: int = 400
):
    return {
        "processes": process_mgr.get_processes(
            sort_by=sort_by,
            reverse=reverse,
            search=search,
            category=category,
            limit=limit
        ),
        "total": len(process_mgr._latest_list)
    }


@app.post("/api/process/{pid}/kill")
def kill_process(pid: int, req: KillRequest = KillRequest()):
    res = process_mgr.kill_process(pid, force=req.force)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/power/{action}")
def handle_power(action: str, req: PowerRequest = PowerRequest()):
    if action == "lock":
        return lock_workstation()
    elif action == "sleep":
        return sleep_pc()
    elif action == "restart":
        return restart_pc(delay_sec=req.delay_sec)
    elif action == "shutdown":
        return shutdown_pc(delay_sec=req.delay_sec)
    elif action == "cancel":
        return cancel_shutdown()
    raise HTTPException(status_code=400, detail=f"Невідома дія живлення: {action}")


# --- ASUS TUF Hardware & G-Helper Endpoints ---

@app.get("/api/asus/status")
def get_asus_status():
    return collector.asus_hw.get_hardware_status()


@app.post("/api/asus/performance")
def set_asus_performance(req: AsusPerfRequest):
    res = collector.asus_hw.set_performance_mode(req.mode)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Помилка зміни режиму"))
    return res


@app.post("/api/asus/keyboard")
def set_asus_keyboard(req: AsusKeyboardRequest):
    res = collector.asus_hw.set_keyboard_backlight(req.level)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Помилка зміни підсвітки"))
    return res


@app.post("/api/asus/keyboard/toggle")
def toggle_asus_keyboard():
    return collector.asus_hw.toggle_keyboard_backlight()


@app.post("/api/asus/screen/{action}")
def handle_asus_screen(action: str):
    if action == "sleep":
        return collector.asus_hw.sleep_screen()
    elif action == "wake":
        return collector.asus_hw.wake_screen()
    elif action == "toggle":
        return collector.asus_hw.toggle_screen()
    raise HTTPException(status_code=400, detail=f"Невідома дія екрана: {action}")


class ScheduleRuleRequest(BaseModel):
    id: Optional[str] = None
    name: str = "Розклад"
    time: str = "23:00"
    mode: int = 2
    enabled: bool = True
    keyboard_level: Optional[int] = 0
    days: Optional[list[int]] = [0, 1, 2, 3, 4, 5, 6]


class ScheduleToggleRequest(BaseModel):
    enabled: bool


@app.get("/api/asus/schedules")
def get_asus_schedules():
    return asus_scheduler.get_status()


@app.post("/api/asus/schedules")
def add_or_update_schedule(rule: ScheduleRuleRequest):
    asus_scheduler.add_or_update_rule(rule.dict())
    return asus_scheduler.get_status()


@app.post("/api/asus/schedules/toggle")
def toggle_schedules(req: ScheduleToggleRequest):
    asus_scheduler.set_enabled(req.enabled)
    return asus_scheduler.get_status()


@app.delete("/api/asus/schedules/{rule_id}")
def delete_schedule(rule_id: str):
    asus_scheduler.delete_rule(rule_id)
    return asus_scheduler.get_status()


class WolSendRequest(BaseModel):
    mac: Optional[str] = None
    target_ip: Optional[str] = "255.255.255.255"
    port: Optional[int] = 9


class MikrotikWolRequest(BaseModel):
    host: Optional[str] = "100.95.32.60"
    port: Optional[int] = 80
    user: Optional[str] = "admin"
    password: Optional[str] = ""
    mac: Optional[str] = None
    interface: Optional[str] = "ether3"
    use_https: Optional[bool] = False


@app.get("/api/wol/info")
def get_wol_info():
    return {
        "mac": get_primary_mac(),
        "mikrotik_tailscale": "100.95.32.60",
        "mikrotik_lan": "192.168.80.1",
        "default_interface": "ether3",
        "default_port": 80
    }


@app.post("/api/wol/send")
def send_direct_wol(req: WolSendRequest = WolSendRequest()):
    clean_mac = (req.mac or get_primary_mac()).replace(":", "").replace("-", "")
    if len(clean_mac) != 12:
        raise HTTPException(status_code=400, detail="Невірний формат MAC-адреси")
    try:
        mac_bytes = bytes.fromhex(clean_mac)
        payload = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            target = req.target_ip or "255.255.255.255"
            port = req.port or 9
            s.sendto(payload, (target, port))
            if target != "255.255.255.255":
                try:
                    s.sendto(payload, ("255.255.255.255", 9))
                except Exception:
                    pass
        return {"success": True, "message": f"WOL пакет надіслано на {target}:{port}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/wol/mikrotik")
def send_mikrotik_wol(req: MikrotikWolRequest = MikrotikWolRequest()):
    mac = req.mac or get_primary_mac()
    host = req.host or "100.95.32.60"
    port = req.port or 80
    proto = "https" if req.use_https else "http"
    iface = req.interface or "ether3"
    
    body_data = json.dumps({"mac": mac, "interface": iface}).encode("utf-8")
    auth_str = f"{req.user or 'admin'}:{req.password or ''}"
    auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_b64}"
    }
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    hosts_to_try = [host]
    if host == "100.95.32.60":
        hosts_to_try.append("192.168.80.1")
    elif host == "192.168.80.1":
        hosts_to_try.append("100.95.32.60")
        
    last_err = None
    for h in hosts_to_try:
        target_url = f"{proto}://{h}:{port}/rest/tool/wol"
        try:
            r = urllib.request.Request(target_url, data=body_data, headers=headers, method="POST")
            with urllib.request.urlopen(r, timeout=3, context=ctx) as resp:
                resp_text = resp.read().decode("utf-8", errors="ignore")
                return {
                    "success": True,
                    "target": target_url,
                    "status": resp.status,
                    "response": resp_text
                }
        except Exception as e:
            last_err = e
            
    return {
        "success": False,
        "error": str(last_err),
        "note": "Перевірте доступність MikroTik REST (IP service www) або облікові дані"
    }


@app.post("/api/asus/hibernate")
def handle_asus_hibernate():
    return collector.asus_hw.hibernate_pc()


@app.get("/TaskMgr.apk")
@app.get("/app.apk")
@app.get("/AsusControl.apk")
def download_app_apk():
    apk_path = WEB_DIR / "TaskMgr.apk"
    if apk_path.exists():
        return FileResponse(
            str(apk_path),
            media_type="application/vnd.android.package-archive",
            filename="TaskMgr.apk"
        )
    raise HTTPException(status_code=404, detail="APK ще компілюється або не знайдено")


@app.get("/api/qr")
def get_qr_code():
    url = f"http://{collector.tailscale_ip}:{SERVER_PORT}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    
    # Send initial full state immediately
    try:
        initial_payload = {
            "type": "init",
            "system": {
                "hostname": collector.hostname,
                "local_ip": collector.tailscale_ip,
                "tailscale_ip": collector.tailscale_ip,
                "cpu_model": collector.cpu_name,
                "cores_logical": collector.cores_logical,
                "cores_physical": collector.cores_physical,
            },
            "metrics": collector.get_snapshot(),
            "processes": process_mgr.get_processes(limit=300),
            "total_processes": len(process_mgr._latest_list)
        }
        await websocket.send_json(initial_payload)
    except Exception:
        return

    # Background task for sending periodic updates
    tick_counter = 0
    client_settings = {
        "interval": 1.0,
        "processes_enabled": True,
        "sort_by": "cpu",
        "reverse": True,
        "search": "",
        "category": "all"
    }

    async def sender_loop():
        nonlocal tick_counter
        while True:
            await asyncio.sleep(client_settings["interval"])
            tick_counter += 1
            snap = collector.get_snapshot()

            payload = {
                "type": "tick",
                "metrics": snap,
            }

            # Update processes every tick if enabled
            if client_settings["processes_enabled"]:
                payload["processes"] = process_mgr.get_processes(
                    sort_by=client_settings["sort_by"],
                    reverse=client_settings["reverse"],
                    search=client_settings["search"],
                    category=client_settings["category"],
                    limit=300
                )
                payload["total_processes"] = len(process_mgr._latest_list)

            await websocket.send_json(payload)

    sender_task = asyncio.create_task(sender_loop())

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "config":
                client_settings["interval"] = max(0.5, float(data.get("interval", 1.0)))
                client_settings["processes_enabled"] = bool(data.get("processes_enabled", True))
                client_settings["sort_by"] = data.get("sort_by", client_settings["sort_by"])
                client_settings["reverse"] = bool(data.get("reverse", client_settings["reverse"]))
                client_settings["search"] = str(data.get("search", ""))
                client_settings["category"] = data.get("category", "all")

            elif msg_type == "kill":
                pid = int(data.get("pid", 0))
                force = bool(data.get("force", False))
                result = process_mgr.kill_process(pid, force=force)
                await websocket.send_json({"type": "kill_result", "pid": pid, "result": result})

            elif msg_type == "power":
                act = str(data.get("action"))
                res = {"success": False, "error": "unknown"}
                if act == "lock":
                    res = lock_workstation()
                elif act == "sleep":
                    res = sleep_pc()
                elif act == "restart":
                    res = restart_pc()
                elif act == "shutdown":
                    res = shutdown_pc()
                elif act == "cancel":
                    res = cancel_shutdown()
                await websocket.send_json({"type": "power_result", "action": act, "result": res})

            elif msg_type == "asus_perf":
                mode = int(data.get("mode", 0))
                res = collector.asus_hw.set_performance_mode(mode)
                await websocket.send_json({"type": "asus_action_result", "action": "perf", "result": res})
                await websocket.send_json({"type": "asus_update", "asus": collector.asus_hw.get_hardware_status()})

            elif msg_type == "asus_keyboard":
                level = int(data.get("level", 0))
                res = collector.asus_hw.set_keyboard_backlight(level)
                await websocket.send_json({"type": "asus_action_result", "action": "keyboard", "result": res})
                await websocket.send_json({"type": "asus_update", "asus": collector.asus_hw.get_hardware_status()})

            elif msg_type == "asus_keyboard_toggle":
                res = collector.asus_hw.toggle_keyboard_backlight()
                await websocket.send_json({"type": "asus_action_result", "action": "keyboard_toggle", "result": res})
                await websocket.send_json({"type": "asus_update", "asus": collector.asus_hw.get_hardware_status()})

            elif msg_type == "asus_screen":
                act = str(data.get("action", "toggle"))
                res = {"success": False}
                if act == "sleep":
                    res = collector.asus_hw.sleep_screen()
                elif act == "wake":
                    res = collector.asus_hw.wake_screen()
                elif act == "toggle":
                    res = collector.asus_hw.toggle_screen()
                await websocket.send_json({"type": "asus_action_result", "action": f"screen_{act}", "result": res})
                await websocket.send_json({"type": "asus_update", "asus": collector.asus_hw.get_hardware_status()})

            elif msg_type == "asus_hibernate":
                res = collector.asus_hw.hibernate_pc()
                await websocket.send_json({"type": "asus_action_result", "action": "hibernate", "result": res})

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        sender_task.cancel()


# Mount static web directory
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
