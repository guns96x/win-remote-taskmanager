"""
FastAPI application for Remote Windows Task Manager.
"""

import io
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

import qrcode
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .collector import MetricsCollector
from .process_manager import ProcessManager
from .power_manager import lock_workstation, sleep_pc, restart_pc, shutdown_pc, cancel_shutdown

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

collector = MetricsCollector(history_length=60, interval=1.0)
process_mgr = ProcessManager(update_interval=1.5)
SERVER_PORT = 8899


@asynccontextmanager
async def lifespan(app: FastAPI):
    collector.start()
    process_mgr.start()
    yield
    collector.stop()
    process_mgr.stop()


app = FastAPI(title="Windows Task Manager Remote", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class KillRequest(BaseModel):
    force: bool = False


class PowerRequest(BaseModel):
    delay_sec: int = 5


@app.get("/api/system")
def get_system_info():
    snap = collector.get_snapshot()
    return {
        "hostname": collector.hostname,
        "local_ip": collector.local_ip,
        "port": SERVER_PORT,
        "url": f"http://{collector.local_ip}:{SERVER_PORT}",
        "cpu": snap["cpu"],
        "memory": snap["memory"],
        "gpu": snap["gpu"],
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


@app.get("/api/qr")
def get_qr_code():
    url = f"http://{collector.local_ip}:{SERVER_PORT}"
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
                "local_ip": collector.local_ip,
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

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        sender_task.cancel()


# Mount static web directory
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
