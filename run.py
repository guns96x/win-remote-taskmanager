"""
Windows Task Manager for Android - Server Runner (TAILSCALE ONLY).
Binds exclusively to the Tailscale IPv4 interface for private, encrypted remote access.
"""

import sys
import subprocess
import webbrowser
import psutil
import qrcode
import uvicorn

def get_tailscale_ip() -> str:
    """Finds active Tailscale IPv4 address (100.x.y.z)."""
    # 1. Try tailscale CLI
    try:
        res = subprocess.run(
            ['tailscale', 'ip', '-4'],
            capture_output=True,
            text=True,
            timeout=2.0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        if res.returncode == 0 and res.stdout.strip():
            ip = res.stdout.strip().splitlines()[0]
            if ip.startswith('100.'):
                return ip
    except Exception:
        pass

    # 2. Try net_if_addrs
    for iface, addrs in psutil.net_if_addrs().items():
        if 'tailscale' in iface.lower():
            for addr in addrs:
                if addr.family == 2 and addr.address.startswith('100.'):
                    return addr.address
    return ""

def print_tailscale_banner(ip: str, port: int):
    url = f"http://{ip}:{port}"
    print("=" * 66)
    print("    WINDOWS 11 TASK MANAGER FOR ANDROID (TAILSCALE EXCLUSIVE)")
    print("=" * 66)
    print(f"\n[+] Режим запуску:             Лише по Tailscale (безпечний тунель)")
    print(f"[+] Tailscale IP комп'ютера:   {ip}")
    print(f"[+] Пряме посилання для моб:   {url}")
    print(f"[+] Доступ з локального ПК:    http://{ip}:{port}\n")
    print("  Відскануйте QR-код нижче з телефону (увімкніть Tailscale на Android):")
    print("  (працює з будь-якої точки світу: через мобільний інтернет 4G/5G або Wi-Fi)\n")

    try:
        qr = qrcode.QRCode(box_size=1, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as e:
        print(f"  [!] QR: {e}")

    print("\n" + "=" * 66)
    print("  УВАГА: Сервер відкритий ВИКЛЮЧНО через Tailscale.")
    print("  Локальна мережа Wi-Fi не має доступу. На телефоні має бути активний Tailscale.")
    print("=" * 66 + "\n")

def main():
    port = 8899
    ts_ip = get_tailscale_ip()

    if not ts_ip:
        print("\n" + "!" * 66)
        print("  [ПОМИЛКА] Tailscale не знайдено або він не підключений!")
        print("  Будь ласка, запустіть додаток Tailscale на Windows і спробуйте знову.")
        print("!" * 66 + "\n")
        sys.exit(1)

    print_tailscale_banner(ts_ip, port)

    if "--open" in sys.argv:
        webbrowser.open(f"http://{ts_ip}:{port}")

    # Bind strictly to the Tailscale interface IP
    uvicorn.run(
        "server.app:app",
        host=ts_ip,
        port=port,
        log_level="warning",
        access_log=False
    )

if __name__ == "__main__":
    main()
