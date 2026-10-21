"""
Windows System Tray launcher for Windows Task Manager Remote (TAILSCALE ONLY).
Runs quietly in the background taskbar notification area, bound to Tailscale IP.
"""

import threading
import webbrowser
import os
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import uvicorn

from run import get_tailscale_ip

PORT = 8899

def create_tray_image():
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Circle with Tailscale style or Fluent Task Manager style
    d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=(24, 24, 24, 255), outline=(96, 205, 255, 255), width=3)
    # Graph curve
    d.line([(14, 46), (26, 36), (38, 20), (50, 28)], fill=(96, 205, 255, 255), width=4)
    return img

def start_server(ip: str):
    uvicorn.run(
        "server.app:app",
        host=ip,
        port=PORT,
        log_level="warning",
        access_log=False
    )

def open_browser(icon, item):
    ip = get_tailscale_ip()
    if ip:
        webbrowser.open(f"http://{ip}:{PORT}")

def quit_app(icon, item):
    icon.stop()
    os._exit(0)

def main():
    ts_ip = get_tailscale_ip()
    if not ts_ip:
        print("[ПОМИЛКА] Tailscale не знайдено!")
        return

    server_thread = threading.Thread(target=start_server, args=(ts_ip,), daemon=True)
    server_thread.start()

    url = f"http://{ts_ip}:{PORT}"

    menu = (
        item("📱 Відкрити диспетчер", open_browser, default=True),
        item(f"🔒 Tailscale: {ts_ip}", lambda icon, item: None, enabled=False),
        item("❌ Вийти", quit_app)
    )

    icon = pystray.Icon("WinTaskMgrRemote", create_tray_image(), f"Диспетчер завдань (Tailscale: {ts_ip})", menu)
    icon.run()

if __name__ == "__main__":
    main()
