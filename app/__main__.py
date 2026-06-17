#!/usr/bin/env python3
"""Emergency Bell 앱 실행 진입점

사용법:
    python -m app          # 풀스크린 키오스크
    python -m app.main_ui  # 동일

환경변수:
    EB_SERVER_URL    - 관제 서버 URL (기본: http://127.0.0.1:8000)
    EB_DEVICE_ID     - 디바이스 식별자
    EB_LOCATION      - 설치 위치
    EB_WHISPER_MODEL - tiny|base|small|medium|large-v3 (기본: small)
"""
from .main_ui import main

if __name__ == "__main__":
    main()
