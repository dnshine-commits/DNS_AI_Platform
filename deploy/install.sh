#!/bin/bash
# ===================================================================
# Emergency Bell - Jetson Orin Nano 설치 스크립트
# 권장 환경: JetPack 6.0+ (Ubuntu 22.04, CUDA 12.2)
# ===================================================================
set -e

echo "================================================="
echo "  Emergency Bell 설치 스크립트"
echo "  대상: NVIDIA Jetson Orin Nano (JetPack 6.x)"
echo "================================================="

# 1. 시스템 의존성
echo ""
echo "[1/5] 시스템 패키지 설치..."
sudo apt update
sudo apt install -y \
    python3-pip python3-venv \
    portaudio19-dev libportaudio2 \
    libxcb-xinerama0 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 \
    fonts-noto-cjk \
    alsa-utils \
    git curl

# 2. Python 가상환경
echo ""
echo "[2/5] Python 가상환경 생성..."
cd "$(dirname "$0")/.."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 3. PyTorch (Jetson용 - NVIDIA 공식 wheel)
echo ""
echo "[3/5] Jetson용 PyTorch 설치 안내..."
echo "  ⚠ OpenAI Whisper는 PyTorch가 필수입니다."
echo "  Jetson은 PyTorch를 NVIDIA 공식 wheel로 설치해야 합니다."
echo ""
echo "  공식 가이드:"
echo "  https://forums.developer.nvidia.com/t/pytorch-for-jetson/"
echo ""
echo "  (예시 - JetPack 6.x 기준, 실제 URL은 위 페이지에서 확인)"
echo "  pip install --extra-index-url https://pypi.jetson-ai-lab.dev/jp6/cu126 torch torchaudio"
echo ""
read -p "PyTorch 설치를 완료하셨습니까? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "  PyTorch 설치 후 이 스크립트를 다시 실행하세요."
    exit 1
fi

# 4. Python 패키지
echo ""
echo "[4/5] Python 패키지 설치..."
pip install -r requirements.txt

# 5. 모델 다운로드 (오프라인 환경 대비 미리 받아두기)
echo ""
echo "[5/5] Whisper 모델 다운로드..."
python3 -c "
import whisper
print('Whisper small 모델 다운로드 중... (약 460MB)')
model = whisper.load_model('small', device='cpu')
print('모델 캐시 완료: ~/.cache/whisper/')
" || echo "  ⚠ 모델 다운로드 실패. 인터넷 연결을 확인하세요."

# 로그 디렉토리
sudo mkdir -p /var/log/emergency-bell
sudo chown $USER:$USER /var/log/emergency-bell

echo ""
echo "================================================="
echo "  설치 완료!"
echo "================================================="
echo ""
echo "▶ 실행 방법:"
echo "  1. Mock 서버 시작 (별도 터미널):"
echo "     source venv/bin/activate"
echo "     uvicorn server.mock_server:app --host 0.0.0.0 --port 8000"
echo ""
echo "  2. 키오스크 앱 시작:"
echo "     source venv/bin/activate"
echo "     python -m app"
echo ""
echo "  3. 관제 대시보드 확인 (브라우저):"
echo "     http://<jetson_ip>:8000/"
echo ""
echo "▶ 부팅 시 자동 실행:"
echo "  sudo cp deploy/emergency-bell.service /etc/systemd/system/"
echo "  sudo systemctl enable emergency-bell"
echo "  sudo systemctl start emergency-bell"
