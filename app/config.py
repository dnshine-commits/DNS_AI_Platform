"""
emergency-bell 설정 파일
모든 경로/엔드포인트/모델 옵션을 한 곳에서 관리
"""
import os
from pathlib import Path

# ============== 디바이스 식별 ==============
DEVICE_ID = os.getenv("EB_DEVICE_ID", "IS-BELL-0427")
DEVICE_LOCATION = os.getenv("EB_LOCATION", "공장 A동 - 1층 출입구")

# ============== 서버 / 관제 ==============
# 로컬 mock 서버 기본값 - 실제 배포 시 EB_SERVER_URL 환경변수로 교체
SERVER_URL = os.getenv("EB_SERVER_URL", "http://127.0.0.1:8000")
ENDPOINTS = {
    "asr_session": f"{SERVER_URL}/api/asr/session",
    "transcribe":  f"{SERVER_URL}/api/asr/transcribe",
    "broadcast":   f"{SERVER_URL}/api/network/broadcast",
    "register":    f"{SERVER_URL}/api/control/register",
    "manager":     f"{SERVER_URL}/api/manager/connect",
}

# ============== Whisper ASR (OpenAI 원본) ==============
# 모델 사이즈: tiny | base | small | medium | large
# Jetson Orin Nano 8GB 권장: small (속도/정확도 균형)
# 주의: 원본 whisper는 faster-whisper보다 느림. 더 빠르게 하려면 tiny/base 고려
WHISPER_MODEL_SIZE = os.getenv("EB_WHISPER_MODEL", "small")
WHISPER_LANGUAGE   = "ko"           # 한국어 고정
WHISPER_DEVICE     = "cuda"          # Jetson GPU 사용. CPU 강제 시 "cpu"

# ============== 마이크 / 녹음 ==============
AUDIO_SAMPLE_RATE = 16000      # Whisper 권장 샘플레이트
AUDIO_CHANNELS    = 1
RECORD_SECONDS    = 5          # 긴급 시나리오(구급/화재/작업중지) 발화 최대 시간
RECORD_SECONDS_LONG = 600      # 긴 시나리오(TBM/아차사고) 발화 최대 시간 (사용자가 종료 버튼으로 끊음)
AUDIO_DEVICE_INDEX = 24     # Jabra SPEAK 510 USB
SILENCE_THRESHOLD  = 500       # VAD 임계치 (옵션)

# ============== UI ==============
FULLSCREEN = True              # 키오스크 모드
HIDE_CURSOR = True             # 터치 전용 환경
SCREEN_TIMEOUT_SECONDS = 30    # 메뉴 진입 후 자동 복귀
HAPTIC_VIBRATE_MS = 40         # navigator.vibrate 미지원 환경에선 무시

# ============== 로깅 ==============
LOG_DIR = Path(os.getenv("EB_LOG_DIR", "/var/log/emergency-bell"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "events.log"

# ============== 색상 (UI 테마) ==============
COLORS = {
    "bg":         "#0A0D10",
    "bg_panel":   "#13171B",
    "border":     "#2A2F36",
    "text":       "#E8EAED",
    "text_dim":   "#71757B",
    "accent":     "#FFD400",   # 네온 옐로우
    # 긴급 (우측 메뉴)
    "emergency":  "#FF3355",   # 구급 - 레드
    "fire":       "#FF6B1A",   # 화재 - 오렌지
    "stop":       "#FFD400",   # 작업중지 - 옐로우
    "manager":    "#4DD8E6",   # 관리자 - 시안
    # 예방·관리 (좌측 메뉴)
    "incident":   "#A78BFA",   # 아차사고 - 퍼플
    "tbm":        "#22D3EE",   # TBM - 시안 블루
    "settings":   "#94A3B8",   # 환경설정 - 슬레이트
    "ok":         "#4ADE80",
}
