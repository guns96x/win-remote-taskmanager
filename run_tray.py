"""
Windows System Tray launcher for Windows Task Manager Remote.
Runs quietly in the background taskbar notification area.
"""

import threading
import webbrowser
import socket
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import uvicorn

from run import get_local_ip

PORT = 8899

def create_tray_image():
    # 64x64 icon with Windows Fluent Task Manager colors
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=(32, 32, 32, 255), outline=(96, 205, 255, 255), width=3)
    # Chart line inside
    d.line([(14, 46), (26, 36), (38, 20), (50, 28)], fill=(96, 205, 255, 255), width=4)
    return img

def start_server():
    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
        access_log=False
    )

def open_browser(icon, item):
    ip = get_local_ip()
    webbrowser.open(f"http://{ip}:{PORT}")

def quit_app(icon, item):
    icon.stop()
    import os
    os._exit(0)

def main():
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    ip = get_local_ip()
    url = f"http://{ip}:{PORT}"

    menu = (
        item("📱 Відкрити диспетчер", open_browser, default=True),
        item(f"🌐 Адреса: {url}", lambda icon, item: None, enabled=False),
        item("❌ Вийти", quit_app)
    )

    icon = pystray.Icon("WinTaskMgrRemote", create_tray_image(), "Windows Task Manager Remote", menu)
    icon.run()

if __name__ == "__main__":
    main()
