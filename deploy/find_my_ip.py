#!/usr/bin/env python3
"""
이 스크립트를 Jetson에서 실행하면 노트북에서 접속할 IP 주소를 알려줍니다.

사용:
    python3 deploy/find_my_ip.py
"""
import socket
import subprocess
import sys


def get_local_ips():
    """현재 보드의 모든 로컬 IP 주소 조회"""
    ips = set()

    # 1. 외부 연결 시뮬레이션으로 메인 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # 2. hostname -I (리눅스)
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
        for ip in result.stdout.strip().split():
            if "." in ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass

    return sorted(ips)


def main():
    print("\n" + "=" * 60)
    print("  EMERGENCY BELL · 네트워크 정보")
    print("=" * 60)

    hostname = socket.gethostname()
    print(f"\n  호스트명: {hostname}")

    ips = get_local_ips()
    if not ips:
        print("\n  ⚠ IP를 찾을 수 없습니다. 네트워크 연결을 확인하세요.")
        sys.exit(1)

    print(f"  IP 주소: {', '.join(ips)}")

    print(f"\n{'─' * 60}")
    print("  📋 노트북/PC 브라우저에서 이 주소로 접속하세요:")
    print(f"{'─' * 60}")
    for ip in ips:
        print(f"\n     ▶  http://{ip}:8000/")
    print()

    print(f"{'─' * 60}")
    print("  🔧 Jetson 비상벨 앱 실행 시 이 환경변수 사용:")
    print(f"{'─' * 60}")
    print(f"\n     export EB_SERVER_URL=http://127.0.0.1:8000")
    print(f"     # (Jetson에서 자기 서버를 호출하므로 localhost로 OK)")
    print()

    print(f"{'─' * 60}")
    print("  ✓ 체크리스트")
    print(f"{'─' * 60}")
    print("     □ Jetson과 노트북이 같은 Wi-Fi/네트워크에 있는지")
    print("     □ 방화벽에서 8000 포트가 열려있는지")
    print("       sudo ufw allow 8000/tcp")
    print("     □ 노트북에서 ping이 되는지 (ping <jetson_ip>)")
    print()
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
