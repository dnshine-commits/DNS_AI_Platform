# Emergency Bell · 산업안전 비상벨 시스템

NVIDIA Jetson Orin Nano + USB 마이크 + HDMI 터치스크린 환경에서 동작하는 산업 현장용 비상벨 키오스크.
Jetson에서 발생한 모든 행동(터치, 음성, 상태 변화)이 **노트북/PC 브라우저에서 실시간으로 보입니다.**

## 🎯 동작 시나리오

```
┌─────────────────┐         HTTP/SSE         ┌──────────────────┐
│  Jetson Orin    │ ───────────────────────▶ │  노트북/PC       │
│  + USB 마이크   │  실시간 이벤트 푸시      │  관제 대시보드   │
│  + HDMI 터치    │                          │  (브라우저)      │
└─────────────────┘                          └──────────────────┘
```

1. 작업자가 Jetson 터치스크린에서 비상버튼 누름
2. 4개 옵션 중 선택 (구급/화재/작업중지/관리자)
3. 마이크에 발화 → Whisper(Jetson 로컬) 전사
4. **노트북 브라우저 화면이 즉시 반응** (Server-Sent Events)
   - 카운터 증가, 이벤트 카드 슬라이드 인, 화면 상단에 알림 배너

## 📋 폴더 구조

```
emergency-bell/
├── app/                          # Jetson 키오스크 앱
│   ├── main_ui.py                # PyQt5 풀스크린 UI
│   ├── workflow.py               # 4개 시나리오 엔진
│   ├── asr_service.py            # USB 마이크 + openai-whisper
│   ├── server_client.py          # 노트북에 이벤트 전송
│   └── config.py                 # 설정
├── server/
│   └── mock_server.py            # FastAPI + SSE 관제 서버
├── deploy/
│   ├── install.sh                # Jetson 의존성 설치
│   ├── find_my_ip.py             # 노트북 접속 IP 알려주기
│   ├── emergency-bell.service    # 키오스크 자동실행
│   └── emergency-bell-server.service  # 관제 서버 자동실행
├── requirements.txt
└── README.md
```

## ⚡ 빠른 시작 (5분 안에 동작 확인)

### 1단계: Jetson에 코드 배포
```bash
# Jetson에서
cd ~
unzip emergency-bell.zip   # 또는 git clone
cd emergency-bell

chmod +x deploy/install.sh
./deploy/install.sh        # Python 가상환경 + 의존성 + Whisper 모델 자동 설치
```

### 2단계: 네트워크 IP 확인
```bash
python3 deploy/find_my_ip.py
```
출력 예시:
```
  ▶  http://192.168.0.42:8000/
```
이 주소를 **노트북에서 접속할 주소**로 기억합니다.

### 3단계: 관제 서버 실행 (Jetson 터미널 1)
```bash
source venv/bin/activate
uvicorn server.mock_server:app --host 0.0.0.0 --port 8000
```
서버 시작 시 노트북 접속 주소가 콘솔에 출력됩니다.

### 4단계: 노트북에서 관제 화면 열기
노트북 브라우저에서 `http://<JETSON_IP>:8000/` 접속.
산업용 다크 테마 대시보드가 뜨고 "● CONNECTED" 표시.

### 5단계: Jetson 키오스크 앱 실행 (Jetson 터미널 2)
```bash
source venv/bin/activate
python -m app
```
풀스크린 비상벨 화면이 뜸.

### 6단계: 테스트
1. Jetson 화면의 빨간 비상버튼을 터치
2. 4개 옵션 중 하나 선택 (예: 구급 신고)
3. 마이크에 5초간 발화 (예: "작업자가 다쳤습니다")
4. **노트북 브라우저가 자동으로 반응합니다:**
   - 우측에 새 이벤트 카드 슬라이드 인
   - 상단에 빨간 알림 배너 등장
   - 카운터 +1
   - 전사 텍스트가 화면 중앙에 크게 표시

## 🔧 네트워크 트러블슈팅

### 노트북에서 접속이 안 될 때

```bash
# 1) Jetson 방화벽 확인
sudo ufw allow 8000/tcp
sudo ufw status

# 2) 노트북에서 핑 테스트
ping <JETSON_IP>

# 3) 노트북에서 포트 열려있는지
# Mac/Linux:
nc -zv <JETSON_IP> 8000
# Windows PowerShell:
Test-NetConnection <JETSON_IP> -Port 8000

# 4) Jetson과 노트북이 같은 네트워크인지
# 두 장치 IP가 같은 대역(예: 둘 다 192.168.0.x)이어야 함
```

### Wi-Fi가 분리된 환경 (게스트망 등)
공유기의 "AP 격리" 또는 "클라이언트 격리"가 켜져 있으면 같은 Wi-Fi라도 통신 안 됨.
공유기 관리자 페이지에서 끄거나, 유선 LAN으로 연결하세요.

### 외부 망에서 접속하고 싶을 때 (선택)
인터넷 어디서나 접속하려면 [ngrok](https://ngrok.com/) 같은 터널 서비스 사용:
```bash
# Jetson에서
ngrok http 8000
# → 출력된 https://xxxx.ngrok.io 주소를 어디서든 접속 가능
```

## 🎤 USB 마이크 설정

### 마이크 인식 확인
```bash
# 입력 장치 목록
arecord -l

# Python에서 보이는 장치 (인덱스 확인용)
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

### 특정 USB 마이크 강제 사용
`app/config.py` 수정:
```python
AUDIO_DEVICE_INDEX = 1   # 위 명령에서 본 USB 마이크의 인덱스
```

### 녹음 테스트
```bash
arecord -D plughw:1,0 -f cd -d 3 test.wav && aplay test.wav
```

## 🖥 HDMI 터치패드 설정

대부분의 HDMI 터치 디스플레이는 USB로 터치 신호를 보내며 별도 드라이버 없이 X11에서 인식됩니다.

### 터치 동작 확인
```bash
xinput list                    # 터치 장치가 있는지
xinput test <device_id>        # 화면 만져보면 좌표 출력되는지
```

### 좌표 매핑 (멀티 모니터 환경)
```bash
xinput map-to-output <touch_id> HDMI-0
```

### 캘리브레이션
```bash
sudo apt install xinput-calibrator
xinput_calibrator
# 출력된 설정값을 ~/.xinputrc 또는 /usr/share/X11/xorg.conf.d/ 에 저장
```

## ⚙ 환경 설정

`app/config.py` 수정 또는 환경변수:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `EB_SERVER_URL` | `http://127.0.0.1:8000` | 관제 서버 URL |
| `EB_DEVICE_ID` | `IS-BELL-0427` | 디바이스 식별자 |
| `EB_LOCATION` | `공장 A동 - 1층` | 설치 위치 |
| `EB_WHISPER_MODEL` | `small` | tiny/base/small/medium/large-v3 |

**여러 대 Jetson이 한 노트북으로 보고할 경우**, 각 Jetson에서 다른 `EB_DEVICE_ID`/`EB_LOCATION` 설정 + `EB_SERVER_URL`을 노트북 IP로 지정.

## 🚀 부팅 자동 실행 (운영 배포)

```bash
# 1) 서비스 파일을 사용자 환경에 맞게 수정
# (deploy/emergency-bell.service의 User=, WorkingDirectory= 경로)

# 2) systemd 등록
sudo cp deploy/emergency-bell-server.service /etc/systemd/system/
sudo cp deploy/emergency-bell.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable emergency-bell-server
sudo systemctl enable emergency-bell

sudo systemctl start emergency-bell-server
sudo systemctl start emergency-bell

# 3) 로그 확인
journalctl -u emergency-bell -f
journalctl -u emergency-bell-server -f
```

부팅 시:
- 관제 서버 자동 시작
- 키오스크 앱 자동 풀스크린 실행
- 비정상 종료 시 자동 재시작

## 🐛 자주 발생하는 문제

| 증상 | 원인 / 해결 |
|------|------------|
| `Could not connect to display` | systemd 유닛에 `DISPLAY=:0`, `XAUTHORITY=/home/<user>/.Xauthority` 추가 |
| `No module named 'torch'` | Jetson용 PyTorch가 설치 안 됨. NVIDIA 공식 wheel 설치 필요 |
| Whisper GPU 추론 실패 | PyTorch+CUDA 설치 확인. 자동으로 CPU 폴백되지만 매우 느림 |
| Whisper 추론이 느림 (5초+) | 원본 whisper는 Jetson에서 느림. `EB_WHISPER_MODEL=tiny` 또는 `base`로 변경 권장 |
| 마이크 권한 없음 | `sudo usermod -a -G audio $USER` 후 재로그인 |
| 한글 깨짐 | `sudo apt install fonts-noto-cjk` |
| SSE가 일정 시간 후 끊김 | 프록시(nginx 등) 사용 시 `proxy_buffering off; proxy_read_timeout 3600;` |
| 풀스크린 해제하고 싶음 | `app/config.py`의 `FULLSCREEN = False` |

## 📊 실시간 모니터링 화면 구성

브라우저로 보이는 화면 ([http://<JETSON_IP>:8000/](#)):

- **상단**: 연결 상태 LED, 시계, 서버 정보
- **중앙 상단**: 4개 카테고리별 누적 카운터
- **좌측 메인**: 실시간 이벤트 스트림 (최신 이벤트 슬라이드 인)
- **우측 사이드바**: 연결 상태, 등록 디바이스, 가동 시간, 클리어 버튼
- **알림 배너**: REGISTER 이벤트 발생 시 4초간 화면 상단에 빨간 배너 표시

## 🔌 향후 확장

- 실제 관제 서버로 전환: `mock_server.py`의 엔드포인트 시그니처 그대로 구현
- 다중 Jetson 지원: 이미 `device_id` 기반으로 분리되어 있음
- MQTT/Kafka 연동: `server_client.py`의 `_post()`만 교체
- 음성 명령(웨이크워드): `asr_service.py`에 `webrtcvad` 추가
- 영상 녹화: 비상 발생 시 USB 카메라 영상 5초 캡처

---
**Made for industrial safety. Stay safe.**
