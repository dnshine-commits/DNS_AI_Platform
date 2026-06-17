# Jetson Orin Nano 셋업 가이드

처음부터 끝까지 순서대로 진행하는 체크리스트입니다.
각 단계의 **✅ 확인** 명령이 정상 통과해야 다음 단계로 넘어가세요.

---

## 📦 사전 준비물

- [x] Jetson Orin Nano 보드 (8GB 권장)
- [x] microSD 카드 (64GB 이상) 또는 NVMe SSD
- [x] HDMI 터치 디스플레이
- [x] USB 마이크
- [x] 키보드 (초기 셋업용 — 셋업 완료 후 분리 가능)
- [x] 인터넷 연결 (Wi-Fi 또는 이더넷)
- [x] 노트북/PC (관제 화면 확인용, Jetson과 같은 네트워크)

---

# 🔹 STEP 0 — JetPack OS 설치 확인

이미 JetPack이 설치되어 있다고 가정합니다. 아니라면 [NVIDIA SDK Manager](https://developer.nvidia.com/sdk-manager)로 먼저 설치하세요.

## ✅ 확인
```bash
# JetPack 버전 확인
sudo apt-cache show nvidia-jetpack | grep Version

# CUDA 버전 확인
nvcc --version

# 기대 출력: JetPack 6.0+ / CUDA 12.x
```

CUDA가 안 잡히면:
```bash
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

---

# 🔹 STEP 1 — 시스템 기본 설정

## 1-1. 시스템 업데이트
```bash
sudo apt update
sudo apt upgrade -y
```

## 1-2. 전원 모드 최대 성능
```bash
# 사용 가능 모드 확인
sudo nvpmodel -q

# 최대 성능(MAXN)으로 설정 - 모드 0이 일반적으로 MAXN
sudo nvpmodel -m 0
sudo jetson_clocks
```

## 1-3. 한국어 폰트 설치 (UI 한글 표시용)
```bash
sudo apt install -y fonts-noto-cjk fonts-nanum
```

## ✅ 확인
```bash
# 시스템 정보
jtop
# 또는
sudo apt install python3-pip
sudo pip3 install jetson-stats
sudo jtop
```
`jtop` 화면에서 GPU/CPU/RAM이 정상적으로 표시되면 OK. `q`로 종료.

---

# 🔹 STEP 2 — 디스플레이 & 터치 확인

HDMI 터치 디스플레이를 연결한 상태에서 진행하세요.

## 2-1. 디스플레이 인식 확인
```bash
# X 디스플레이 확인
echo $DISPLAY    # :0 이 출력되어야 함

# 모니터 정보
xrandr
```

## 2-2. 터치 입력 확인
```bash
# 터치 장치 인식 확인 (USB 터치 디스플레이는 보통 자동 인식)
xinput list

# 출력 예시에서 터치 디바이스 ID 확인 (예: id=11)
# ↳ "USB Touchscreen" 같은 항목이 보여야 함
```

## ✅ 확인 — 터치 동작 테스트
```bash
# 터치 디바이스 ID로 테스트
xinput test <ID>
# 화면을 손가락으로 만지면 좌표가 출력되어야 함
# Ctrl+C로 종료
```

좌표가 어긋나면 캘리브레이션:
```bash
sudo apt install -y xinput-calibrator
xinput_calibrator
# 화면의 점 4개 순서대로 터치 → 출력된 설정값을 ~/.xinputrc에 저장
```

---

# 🔹 STEP 3 — USB 마이크 확인

USB 마이크를 Jetson에 연결한 상태에서 진행하세요.

## 3-1. 마이크 인식 확인
```bash
# 입력 장치 목록
arecord -l

# 출력 예시:
# **** List of CAPTURE Hardware Devices ****
# card 1: Device [USB PnP Audio Device], device 0: USB Audio [USB Audio]
#   ↑ 이 부분의 "card 1"을 기억하세요
```

## 3-2. 사용자를 audio 그룹에 추가
```bash
sudo usermod -a -G audio $USER
# 적용을 위해 재로그인 또는 재부팅 필요
```

## ✅ 확인 — 5초 녹음 후 재생 테스트
```bash
# card 번호를 위에서 확인한 값으로 (예: plughw:1,0)
arecord -D plughw:1,0 -f cd -d 5 test.wav
aplay test.wav
```

녹음한 목소리가 그대로 재생되면 성공. 안 들리면:
- `pavucontrol` 설치 후 입력 장치 음량 확인 (`sudo apt install -y pavucontrol`)
- 다른 USB 포트로 변경 시도

---

# 🔹 STEP 4 — Python 환경 준비

## 4-1. Python 버전 확인
```bash
python3 --version    # 3.10 이상이어야 함
```

## 4-2. 시스템 패키지 (Python 의존성)
```bash
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    portaudio19-dev libportaudio2 \
    libxcb-xinerama0 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 \
    alsa-utils \
    git curl unzip
```

## ✅ 확인
```bash
python3 -c "import sys; print(sys.version)"
which pip3
```

---

# 🔹 STEP 5 — 프로젝트 코드 배포

## 5-1. 코드 다운로드
zip 파일을 Jetson으로 옮긴 뒤:
```bash
cd ~
unzip emergency-bell.zip
cd emergency-bell
ls   # app/ server/ deploy/ requirements.txt README.md 가 보여야 함
```

## 5-2. Python 가상환경 생성
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

## ✅ 확인
```bash
# 가상환경 활성화 표시 확인
echo $VIRTUAL_ENV   # /home/<user>/emergency-bell/venv 가 출력됨
```

---

# 🔹 STEP 6 — PyTorch 설치 (Jetson 전용 wheel) ⚠️ 중요

OpenAI Whisper는 PyTorch에 의존하며, **일반 `pip install torch`로는 GPU가 안 잡힙니다.**
NVIDIA 공식 Jetson wheel을 사용해야 합니다.

## 6-1. JetPack 버전에 맞는 PyTorch 설치

JetPack 버전 확인:
```bash
sudo apt-cache show nvidia-jetpack | grep Version
```

### JetPack 6.x (Ubuntu 22.04, CUDA 12.x)
```bash
# 가상환경 활성화 상태에서
pip install --extra-index-url https://pypi.jetson-ai-lab.dev/jp6/cu126 \
    torch torchaudio
```

### JetPack 5.x (Ubuntu 20.04, CUDA 11.x)
```bash
pip install --extra-index-url https://pypi.jetson-ai-lab.dev/jp5/cu114 \
    torch torchaudio
```

> 위 인덱스가 안 되면 [NVIDIA 공식 PyTorch for Jetson 페이지](https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048)에서 직접 wheel 다운로드.

## ✅ 확인 — GPU 인식
```bash
python3 -c "
import torch
print(f'PyTorch 버전: {torch.__version__}')
print(f'CUDA 사용 가능: {torch.cuda.is_available()}')
print(f'GPU 이름: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"없음\"}')
"
```

기대 출력:
```
PyTorch 버전: 2.x.x
CUDA 사용 가능: True
GPU 이름: Orin
```

**`CUDA 사용 가능: False`가 나오면 Whisper가 CPU로 동작해서 매우 느려집니다. 반드시 True가 나올 때까지 PyTorch 설치를 점검하세요.**

---

# 🔹 STEP 7 — 프로젝트 의존성 설치

## 7-1. requirements.txt 설치
```bash
# 가상환경 활성화 상태에서
cd ~/emergency-bell
pip install -r requirements.txt
```

설치되는 주요 패키지:
- `PyQt5` — UI
- `openai-whisper` — 음성 인식
- `sounddevice` — 마이크 녹음
- `fastapi`, `uvicorn` — 관제 서버
- `qasync`, `httpx` — 비동기

## ✅ 확인
```bash
python3 -c "
import PyQt5; print('PyQt5: OK')
import whisper; print('Whisper: OK')
import sounddevice; print('SoundDevice: OK')
import fastapi; print('FastAPI: OK')
"
```

---

# 🔹 STEP 8 — Whisper 모델 다운로드

## 8-1. small 모델 받기 (약 460MB)
```bash
python3 -c "
import whisper
print('Whisper small 모델 다운로드 중... (약 460MB)')
model = whisper.load_model('small')
print('완료! 캐시 위치: ~/.cache/whisper/')
"
```

## ✅ 확인
```bash
ls -lh ~/.cache/whisper/
# small.pt (약 460MB) 파일이 있어야 함
```

---

# 🔹 STEP 9 — 마이크 + Whisper 통합 테스트

UI 없이 마이크와 Whisper만 단독으로 테스트합니다.

## 9-1. Python에서 마이크 인덱스 확인
```bash
python3 -c "
import sounddevice as sd
print(sd.query_devices())
"
```

USB 마이크 줄에서 인덱스 번호 확인 (예: `1 USB PnP Audio Device`).

## 9-2. 필요시 인덱스 고정
USB 마이크가 기본 장치가 아니라면 `app/config.py` 수정:
```python
AUDIO_DEVICE_INDEX = 1   # 위에서 확인한 USB 마이크 인덱스
```

## ✅ 확인 — 단독 ASR 테스트
```bash
cd ~/emergency-bell
source venv/bin/activate
python3 -m app.asr_service
```

기대 동작:
1. "5초간 녹음합니다. 발화해 주세요..." 메시지
2. 5초간 마이크에 발화 (예: "테스트입니다")
3. Whisper 추론 (GPU면 5~10초, CPU면 30초+)
4. 전사 결과 출력 + 신뢰도 표시

❌ 실패하면 STEP 6의 PyTorch CUDA 또는 STEP 3의 마이크 권한을 다시 확인하세요.

---

# 🔹 STEP 10 — 관제 서버 단독 실행

## 10-1. Jetson IP 확인
```bash
python3 deploy/find_my_ip.py
```
출력되는 `http://192.168.x.x:8000/` 주소를 메모해 두세요.

## 10-2. 방화벽 포트 열기
```bash
# ufw가 활성화되어 있다면
sudo ufw status
sudo ufw allow 8000/tcp   # 활성화 상태일 때만
```

## 10-3. 서버 실행
```bash
source venv/bin/activate
uvicorn server.mock_server:app --host 0.0.0.0 --port 8000
```

콘솔에 노트북 접속 주소가 출력됩니다.

## ✅ 확인 — 노트북 브라우저에서 접속
1. 노트북 브라우저 주소창에 `http://<JETSON_IP>:8000/` 입력
2. 산업용 다크 테마 관제 대시보드가 보여야 함
3. 우측 사이드바 "CONNECTION"이 녹색 "CONNECTED"

❌ 접속 실패 시:
- 두 장치가 같은 Wi-Fi인지
- `ping <JETSON_IP>` 가능한지
- Wi-Fi 공유기의 "AP 격리" 설정 확인

---

# 🔹 STEP 11 — 통신 테스트 (서버만으로)

서버가 잘 받는지 노트북에서 직접 호출 테스트:

## 11-1. 노트북에서 curl로 테스트 이벤트 전송
```bash
# 노트북 터미널에서 (Mac/Linux)
curl -X POST http://<JETSON_IP>:8000/api/control/register \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "TEST-001",
    "device_location": "테스트 위치",
    "timestamp": "2026-04-29T00:00:00",
    "category": "emergency",
    "transcript": "테스트 메시지"
  }'
```

## ✅ 확인
- Jetson 서버 콘솔에 `[REGISTER] emergency 테스트 메시지` 로그 출력
- **노트북 브라우저 화면에 즉시 반응:**
  - 상단 빨간 알림 배너
  - "EMERGENCY · 구급" 카운터 +1
  - 이벤트 카드 슬라이드 인

여기까지 되면 **네트워크/서버/SSE가 모두 정상**입니다.

---

# 🔹 STEP 12 — 키오스크 앱 실행

서버는 STEP 10대로 계속 실행한 상태에서, **별도 터미널**을 열어:

## 12-1. 앱 실행
```bash
cd ~/emergency-bell
source venv/bin/activate
python -m app
```

풀스크린 비상벨 화면이 떠야 합니다. (종료는 `ESC`)

## 12-2. 시나리오 테스트

| 단계 | 행동 | 노트북 화면 반응 |
|------|------|------------------|
| 1 | Jetson 빨간 비상버튼 터치 | (서버 호출 없음) |
| 2 | "구급 신고" 선택 | `ASR_SESSION` 이벤트 |
| 3 | 마이크에 5초 발화 | (녹음 중) |
| 4 | (자동) Whisper 전사 | `TRANSCRIBE` 이벤트 + 전사 텍스트 표시 |
| 5 | (자동) 관제 등록 | `REGISTER` 이벤트 + 알림 배너 + 카운터 +1 |

## ✅ 확인
- Jetson 화면: "상황 접수 완료 / EVENT_ID · ..." 표시
- 노트북 화면: 모든 단계의 이벤트가 시간순으로 누적

---

# 🎉 STEP 13 — 운영 모드 전환 (선택)

테스트 완료되면 부팅 시 자동 실행으로 전환:

## 13-1. systemd 유닛 설정 수정
```bash
nano deploy/emergency-bell.service
# User=jetson을 실제 사용자명으로 (echo $USER로 확인)
# WorkingDirectory= 경로도 실제 경로로
```

## 13-2. 등록 및 활성화
```bash
sudo cp deploy/emergency-bell-server.service /etc/systemd/system/
sudo cp deploy/emergency-bell.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable emergency-bell-server
sudo systemctl enable emergency-bell

sudo systemctl start emergency-bell-server
sudo systemctl start emergency-bell
```

## ✅ 확인
```bash
systemctl status emergency-bell-server
systemctl status emergency-bell

# 실시간 로그
journalctl -u emergency-bell -f
```

이제 Jetson을 재부팅하면 자동으로 키오스크 모드로 시작합니다.

---

# 🆘 자주 막히는 부분 빠른 참조

| 증상 | 가장 흔한 원인 | 해결 |
|------|--------------|-----|
| `torch.cuda.is_available() = False` | 일반 PyTorch 설치됨 | STEP 6 Jetson용 wheel로 재설치 |
| `No module named 'PyQt5'` | venv 미활성화 | `source venv/bin/activate` |
| 마이크 안 잡힘 | audio 그룹 누락 | `sudo usermod -aG audio $USER` 후 재로그인 |
| Whisper 추론 매우 느림 | CPU 폴백됨 | PyTorch CUDA 확인. 임시: `EB_WHISPER_MODEL=tiny` |
| 노트북에서 접속 X | 같은 네트워크 X 또는 방화벽 | `ping` 테스트, `ufw allow 8000` |
| 한글 □□□ 깨짐 | 폰트 미설치 | `sudo apt install fonts-noto-cjk` |
| 풀스크린 안 풀림 | 키오스크 모드 | `ESC` 키 또는 SSH로 `pkill -f 'python -m app'` |
| 화면이 꺼짐 | 절전 모드 | 다음 명령으로 비활성화 ↓ |

화면 절전 비활성화:
```bash
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.desktop.screensaver lock-enabled false
xset s off
xset -dpms
```

---

**중요**: 어느 STEP에서 막히면 그 단계의 ✅ 확인 명령부터 다시 실행해 보세요. 메시지를 캡처해 주시면 도와드리겠습니다.
