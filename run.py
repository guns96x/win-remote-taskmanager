"""
Windows Task Manager for Android - Server Runner with Terminal QR Code.
"""

import sys
import socket
import webbrowser
import qrcode
import uvicorn

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def print_banner(ip: str, port: int):
    url = f"http://{ip}:{port}"
    print("=" * 64)
    print("    WINDOWS 11 TASK MANAGER FOR ANDROID - REMOTE AGENT")
    print("=" * 64)
    print(f"\n[+] Сервер успішно запущено!")
    print(f"[+] Локальна адреса на ПК:     http://localhost:{port}")
    print(f"[+] Адреса для телефону:       {url}\n")
    print("  Для миттєвого підключення з телефону відскануйте QR-код нижче:")
    print("  (камерою смартфона або будь-яким QR-сканером в одній мережі Wi-Fi)\n")

    try:
        qr = qrcode.QRCode(box_size=1, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as e:
        print(f"  [!] Не вдалося вивести QR у консоль: {e}")

    print("\n" + "=" * 64)
    print("  Підказка: на Android у Chrome натисніть 'Додати на головний екран'")
    print("  щоб використовувати диспетчер як нативний повноекранний додаток.")
    print("=" * 64 + "\n")

def main():
    port = 8899
    ip = get_local_ip()
    print_banner(ip, port)

    if "--open" in sys.argv:
        webbrowser.open(f"http://localhost:{port}")

    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False
    )

if __name__ == "__main__":
    main()
