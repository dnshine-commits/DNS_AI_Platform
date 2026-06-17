"""
관제 모니터링 서버 (FastAPI + Server-Sent Events)
================================================================
Jetson에서 발생한 모든 비상 이벤트를 실시간으로 노트북/PC 브라우저에 푸시.

실행 (Jetson에서):
    uvicorn server.mock_server:app --host 0.0.0.0 --port 8000

노트북/PC 브라우저에서 접속:
    http://<JETSON_IP>:8000/

동작:
    Jetson 터치 → POST 요청 → SSE 푸시 → 노트북 화면 즉시 반응
"""
import asyncio
import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Emergency Bell Control Center")

# 인메모리 이벤트 저장소 + SSE 구독자 큐
EVENTS = []
SUBSCRIBERS: list[asyncio.Queue] = []
LOG_FILE = Path("./mock_events.jsonl")


# =====================================================================
# 요청 모델
# =====================================================================
class BasePayload(BaseModel):
    device_id: str
    device_location: str
    timestamp: str

class ASRSession(BasePayload):
    action: str

class TranscribePayload(BasePayload):
    category: str
    transcript: str
    confidence: float

class BroadcastPayload(BasePayload):
    category: str
    message: str = ""
    priority: str = "HIGH"

class RegisterPayload(BasePayload):
    category: str
    transcript: str = ""
    extra: dict = {}

class ManagerPayload(BasePayload):
    action: str


# =====================================================================
# 이벤트 발행 (모든 SSE 구독자에 푸시)
# =====================================================================
async def publish_event(kind: str, data: dict):
    entry = {
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "data": data,
    }
    EVENTS.append(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            pass

    print(f"[{kind}] {data.get('category', '')} {data.get('transcript', '')[:60]}")


# =====================================================================
# 비상벨 → 관제 엔드포인트
# =====================================================================
@app.post("/api/asr/session")
async def asr_session(payload: ASRSession):
    await publish_event("ASR_SESSION", payload.dict())
    return {"session_id": f"asr_{int(time.time() * 1000)}", "status": "LISTENING"}


@app.post("/api/asr/transcribe")
async def transcribe(payload: TranscribePayload):
    await publish_event("TRANSCRIBE", payload.dict())
    return {"received": True, "transcript_id": f"TR-{int(time.time())}"}


@app.post("/api/network/broadcast")
async def broadcast(payload: BroadcastPayload):
    await publish_event("BROADCAST", payload.dict())
    return {"broadcasted": True, "recipients": 47, "broadcast_id": f"BC-{int(time.time())}"}


@app.post("/api/control/register")
async def register(payload: RegisterPayload):
    event_id = f"EVT-{int(time.time() * 1000) % 100000000:08d}"
    await publish_event("REGISTER", {**payload.dict(), "event_id": event_id})

    # ⭐ 아차사고(incident)인 경우 - 노트북 FMEA 서버로 자동 위임
    if payload.category == "incident" and payload.transcript:
        # 백그라운드로 FMEA 요청 (응답 시간 영향 없음)
        asyncio.create_task(_delegate_fmea(event_id, payload.transcript))

    return {"registered": True, "event_id": event_id}


async def _delegate_fmea(event_id: str, transcript: str):
    """아차사고 이벤트를 노트북 FMEA 서버로 위임"""
    fmea_url = os.getenv("EB_FMEA_URL", "http://192.168.0.52:8001")  # 노트북 IP:포트
    input_id = os.getenv("EB_INPUT_ID", "20240036")

    # 시작 알림
    await publish_event("FMEA_STARTED", {
        "event_id": event_id,
        "transcript": transcript,
    })

    # 콜백 URL: FMEA 서버가 진행 상황을 푸시할 우리쪽 엔드포인트
    callback_url = f"http://127.0.0.1:8000/api/fmea/progress"

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(f"{fmea_url}/generate-fmea", json={
                "transcript": transcript,
                "input_id": input_id,
                "event_id": event_id,
                "callback_url": callback_url,
            })
            r.raise_for_status()
            result = r.json()
    except Exception as e:
        await publish_event("FMEA_COMPLETED", {
            "event_id": event_id,
            "success": False,
            "error": f"FMEA 서버 호출 실패: {e}",
        })
        return

    # 완료 알림 (전체 결과를 브라우저로 푸시)
    await publish_event("FMEA_COMPLETED", {
        "event_id": event_id,
        **result,
    })


@app.post("/api/fmea/progress")
async def fmea_progress(payload: dict):
    """FMEA 서버가 보내는 단계별 진행 상황을 받아 브라우저로 SSE 푸시"""
    await publish_event("FMEA_PROGRESS", payload)
    return {"ok": True}


@app.post("/api/manager/connect")
async def manager_connect(payload: ManagerPayload):
    await publish_event("MANAGER_CONNECT", payload.dict())
    return {
        "call_id": f"CALL-{int(time.time())}",
        "manager": "김안전 (안전관리책임자)",
        "extension": "4112",
    }


# =====================================================================
# Server-Sent Events 스트림 (브라우저가 자동 재연결)
# =====================================================================
@app.get("/stream")
async def stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    SUBSCRIBERS.append(queue)

    async def event_gen():
        try:
            yield f"event: connected\ndata: {json.dumps({'ok': True})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if queue in SUBSCRIBERS:
                SUBSCRIBERS.remove(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/events")
async def get_events():
    return {"events": EVENTS[-100:]}


@app.delete("/events")
async def clear_events():
    EVENTS.clear()
    return {"cleared": True}


@app.get("/health")
async def health():
    return {
        "status": "online",
        "subscribers": len(SUBSCRIBERS),
        "events_in_memory": len(EVENTS),
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


# =====================================================================
# 관제 대시보드 HTML (노트북에서 접속)
# =====================================================================
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>Emergency Bell · Control Center</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0A0D10; --panel: #13171B; --border: #2A2F36;
  --text: #E8EAED; --dim: #71757B;
  --accent: #FFD400; --emergency: #FF3355; --fire: #FF6B1A;
  --stop: #FFD400; --manager: #4DD8E6; --ok: #4ADE80;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: "JetBrains Mono", monospace; min-height: 100vh;
  background-image:
    linear-gradient(rgba(255,212,0,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,212,0,0.05) 1px, transparent 1px);
  background-size: 32px 32px;
}
header {
  background: rgba(0,0,0,0.5); border-bottom: 1px solid var(--border);
  padding: 12px 24px; display: flex; justify-content: space-between;
  align-items: center; backdrop-filter: blur(10px);
  position: sticky; top: 0; z-index: 10;
  font-size: 11px; letter-spacing: 2px; text-transform: uppercase;
}
header .left { display: flex; gap: 12px; align-items: center; }
header .left .pulse {
  width: 8px; height: 8px; border-radius: 50%; background: var(--ok);
  animation: pulse 1.5s infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
header .right { color: var(--dim); }
header .right .accent { color: var(--accent); margin-left: 12px; }

.container { max-width: 1400px; margin: 0 auto; padding: 32px 24px; }

h1 {
  font-family: "Bebas Neue", sans-serif; letter-spacing: 4px;
  font-size: 48px; margin-bottom: 4px;
}
h1 .slash { color: var(--accent); }
.subtitle { color: var(--accent); font-size: 11px; letter-spacing: 4px; margin-bottom: 8px; }
.divider { width: 80px; height: 2px; background: var(--accent); margin: 16px 0 32px; }

.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.stat {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 4px; padding: 16px;
}
.stat .label { color: var(--dim); font-size: 10px; letter-spacing: 3px; margin-bottom: 8px; }
.stat .value { font-size: 32px; font-weight: 700; font-family: "Bebas Neue", sans-serif; letter-spacing: 2px; }
.stat .value.emergency { color: var(--emergency); }
.stat .value.fire { color: var(--fire); }
.stat .value.stop { color: var(--stop); }
.stat .value.manager { color: var(--manager); }

.main { display: grid; grid-template-columns: 1.3fr 1fr; gap: 24px; }
@media (max-width: 1024px) { .main { grid-template-columns: 1fr; } }

.panel {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 4px; overflow: hidden;
}
.panel-head {
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11px; letter-spacing: 3px; color: var(--dim); text-transform: uppercase;
}
.panel-head .count { color: var(--accent); font-weight: 700; }

#events { padding: 8px; max-height: 70vh; overflow-y: auto; }
.event {
  background: rgba(0,0,0,0.3); border-left: 3px solid var(--border);
  padding: 12px 14px; margin-bottom: 8px; border-radius: 3px;
  animation: slideIn 0.4s ease; transition: transform 0.2s;
}
.event:hover { transform: translateX(2px); }
@keyframes slideIn {
  from { opacity: 0; transform: translateX(-8px); }
  to { opacity: 1; transform: translateX(0); }
}
.event.ASR_SESSION { border-left-color: var(--manager); }
.event.TRANSCRIBE { border-left-color: var(--accent); }
.event.BROADCAST { border-left-color: var(--fire); animation: slideIn 0.4s ease, flash 1s ease 1; }
.event.REGISTER { border-left-color: var(--ok); }
.event.MANAGER_CONNECT { border-left-color: var(--manager); }
@keyframes flash {
  0%, 100% { background: rgba(0,0,0,0.3); }
  30% { background: rgba(255,107,26,0.2); }
}

.event-header {
  display: flex; justify-content: space-between;
  margin-bottom: 6px; align-items: center;
}
.kind {
  font-size: 11px; font-weight: 700; letter-spacing: 3px;
  padding: 3px 8px; border-radius: 2px;
}
.kind.ASR_SESSION { background: rgba(77,216,230,0.15); color: var(--manager); }
.kind.TRANSCRIBE { background: rgba(255,212,0,0.15); color: var(--accent); }
.kind.BROADCAST { background: rgba(255,107,26,0.15); color: var(--fire); }
.kind.REGISTER { background: rgba(74,222,128,0.15); color: var(--ok); }
.kind.MANAGER_CONNECT { background: rgba(255,51,85,0.15); color: var(--emergency); }
.event-time { color: var(--dim); font-size: 11px; }
.event-body { font-size: 13px; line-height: 1.5; }
.event-body .meta { color: var(--dim); font-size: 11px; margin-top: 4px; }
.event-body .transcript {
  background: rgba(255,212,0,0.05); border-left: 2px solid var(--accent);
  padding: 8px 12px; margin-top: 6px; border-radius: 2px;
  color: var(--text); font-style: italic;
}
.event-body .category { color: var(--accent); font-weight: 700; }

.empty { color: var(--dim); padding: 40px; text-align: center; font-style: italic; }

.alert-banner {
  position: fixed; top: 60px; left: 50%; transform: translateX(-50%);
  background: var(--emergency); color: white; padding: 16px 32px;
  font-weight: 700; letter-spacing: 4px; border-radius: 4px;
  box-shadow: 0 0 60px rgba(255,51,85,0.6);
  animation: alertPop 0.4s ease; z-index: 100;
}
@keyframes alertPop {
  0% { transform: translateX(-50%) translateY(-20px); opacity: 0; }
  100% { transform: translateX(-50%) translateY(0); opacity: 1; }
}

#latest-event {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 4px; padding: 24px; margin-bottom: 24px; min-height: 100px;
}
#latest-event .empty-state { color: var(--dim); text-align: center; padding: 20px; }
#latest-event .big {
  font-family: "Bebas Neue", sans-serif; font-size: 36px;
  letter-spacing: 3px; margin: 12px 0;
}

footer { text-align: center; color: var(--dim); padding: 32px; font-size: 11px; letter-spacing: 3px; }
.connection-status { display: inline-flex; align-items: center; gap: 6px; }
.connection-status.live::before {
  content: ''; width: 8px; height: 8px; border-radius: 50%;
  background: var(--ok); animation: pulse 1.5s infinite;
}
.connection-status.offline::before {
  content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--emergency);
}

/* ===== FMEA 영역 스타일 ===== */
.fmea-section {
  margin-top: 12px; padding: 12px;
  background: rgba(167,139,250,0.05);
  border: 1px solid rgba(167,139,250,0.3);
  border-radius: 4px;
}
.fmea-header {
  font-size: 12px; font-weight: 700; color: #A78BFA;
  letter-spacing: 2px; margin-bottom: 8px;
}
.fmea-stages {
  display: flex; flex-direction: column; gap: 4px;
}
.fmea-stage {
  display: flex; align-items: center; gap: 8px;
  font-size: 11px; padding: 4px 8px;
  background: rgba(0,0,0,0.2); border-radius: 3px;
  color: var(--dim);
  transition: all 0.3s;
}
.fmea-stage.running {
  background: rgba(255,212,0,0.1); color: var(--accent);
}
.fmea-stage.running .stage-status { animation: pulse 1.5s infinite; }
.fmea-stage.done {
  background: rgba(74,222,128,0.1); color: var(--ok);
}
.fmea-stage.error {
  background: rgba(255,51,85,0.1); color: var(--emergency);
}
.fmea-stage .stage-num {
  width: 18px; height: 18px; border-radius: 50%;
  background: rgba(255,255,255,0.1);
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
}
.fmea-stage .stage-label { flex: 1; }
.fmea-stage .stage-status { font-size: 14px; }

.fmea-block {
  margin-top: 8px; padding: 8px 10px;
  background: rgba(0,0,0,0.25); border-radius: 3px;
  border-left: 2px solid #A78BFA;
}
.fmea-block-title {
  font-size: 11px; font-weight: 700; color: #A78BFA;
  margin-bottom: 4px; letter-spacing: 1px;
}
.fmea-list {
  margin: 0; padding-left: 18px; font-size: 12px;
  color: var(--text); line-height: 1.6;
}
.fmea-list li { margin-bottom: 2px; }
.fmea-content {
  font-size: 12px; color: var(--text); line-height: 1.6;
  padding: 4px 0; white-space: pre-wrap; word-break: break-word;
}
.fmea-risk {
  display: flex; gap: 16px; font-size: 12px; color: var(--text);
}
.fmea-risk .rpn b { color: var(--emergency); }
.fmea-details {
  margin-top: 8px; font-size: 11px;
}
.fmea-details summary {
  cursor: pointer; color: var(--accent);
  padding: 4px 0;
}
.fmea-report {
  margin-top: 8px; padding: 12px;
  background: rgba(0,0,0,0.4); border-radius: 3px;
  font-size: 11px; color: var(--text);
  white-space: pre-wrap; word-break: break-word;
  max-height: 400px; overflow-y: auto;
}
.fmea-error {
  font-size: 11px; color: var(--emergency); padding: 4px 0;
}
</style></head>
<body>

<header>
  <div class="left">
    <span class="pulse"></span>
    <span>CONTROL_CENTER · LIVE</span>
    <span style="color: var(--dim);">|</span>
    <span style="color: var(--dim);">SERVER · <span id="server-host"></span></span>
  </div>
  <div class="right">
    <span id="clock">00:00:00</span>
    <span class="accent">SAFETY-CTRL v2.4</span>
  </div>
</header>

<div class="container">
  <div class="subtitle">INDUSTRIAL · SAFETY · CONTROL CENTER</div>
  <h1>관제 모니터 <span class="slash">/</span> EMERGENCY BELL</h1>
  <div class="divider"></div>

  <div style="margin-bottom: 12px; font-size: 10px; letter-spacing: 3px; color: var(--emergency);">긴급 · URGENT</div>
  <div class="stats" style="margin-bottom: 16px;">
    <div class="stat"><div class="label">EMERGENCY · 구급</div><div class="value emergency" id="cnt-emergency">0</div></div>
    <div class="stat"><div class="label">FIRE · 화재</div><div class="value fire" id="cnt-fire">0</div></div>
    <div class="stat"><div class="label">WORK STOP · 작업중지</div><div class="value stop" id="cnt-stop">0</div></div>
    <div class="stat"><div class="label">MANAGER · 관리자(긴급)</div><div class="value manager" id="cnt-manager-urgent">0</div></div>
  </div>

  <div style="margin-bottom: 12px; font-size: 10px; letter-spacing: 3px; color: #A78BFA;">예방·관리 · PREVENTION</div>
  <div class="stats">
    <div class="stat"><div class="label">INCIDENT · 아차사고</div><div class="value" id="cnt-incident" style="color:#A78BFA">0</div></div>
    <div class="stat"><div class="label">TBM · 회의</div><div class="value" id="cnt-tbm" style="color:#22D3EE">0</div></div>
    <div class="stat"><div class="label">MANAGER · 관리자(예방)</div><div class="value" id="cnt-manager-prevention" style="color:#4DD8E6">0</div></div>
    <div class="stat"><div class="label">SETTINGS · 환경설정</div><div class="value" id="cnt-settings" style="color:#94A3B8">0</div></div>
  </div>

  <div id="latest-event">
    <div class="empty-state">
      <div style="font-size: 11px; letter-spacing: 3px; color: var(--accent); margin-bottom: 8px;">LATEST · EVENT</div>
      <div>대기 중 — Jetson 비상벨에서 이벤트 발생을 기다리는 중...</div>
    </div>
  </div>

  <div class="main">
    <div class="panel">
      <div class="panel-head">
        <span>● EVENT_STREAM · 실시간 이벤트</span>
        <span class="count" id="event-count">0 EVENTS</span>
      </div>
      <div id="events"><div class="empty">// 이벤트 대기 중...</div></div>
    </div>

    <div class="panel">
      <div class="panel-head"><span>● SYSTEM · 상태</span></div>
      <div style="padding: 16px;">
        <div style="margin-bottom: 16px;">
          <div style="color: var(--dim); font-size: 11px; letter-spacing: 3px; margin-bottom: 6px;">CONNECTION</div>
          <div class="connection-status live" id="conn-status">CONNECTED</div>
        </div>
        <div style="margin-bottom: 16px;">
          <div style="color: var(--dim); font-size: 11px; letter-spacing: 3px; margin-bottom: 6px;">SERVER ENDPOINT</div>
          <div style="font-size: 13px;" id="server-endpoint"></div>
        </div>
        <div style="margin-bottom: 16px;">
          <div style="color: var(--dim); font-size: 11px; letter-spacing: 3px; margin-bottom: 6px;">DEVICES</div>
          <div id="device-list" style="font-size: 13px;">없음</div>
        </div>
        <div style="margin-bottom: 16px;">
          <div style="color: var(--dim); font-size: 11px; letter-spacing: 3px; margin-bottom: 6px;">UPTIME</div>
          <div style="font-size: 13px;" id="uptime">-</div>
        </div>
        <button onclick="clearEvents()" style="
          background: transparent; color: var(--dim);
          border: 1px solid var(--border); padding: 8px 16px;
          font-family: inherit; font-size: 11px; letter-spacing: 2px;
          cursor: pointer; border-radius: 3px; width: 100%;
        ">CLEAR EVENTS</button>
      </div>
    </div>
  </div>
</div>

<footer>EMERGENCY BELL · CONTROL CENTER · POWERED BY FASTAPI + SSE</footer>

<script>
const KIND_LABEL = {
  ASR_SESSION: 'ASR 세션 시작',
  TRANSCRIBE: 'Whisper 전사 완료',
  BROADCAST: '비상망 전파',
  REGISTER: '관제 등록 완료',
  MANAGER_CONNECT: '관리자 통화 연결',
  FMEA_STARTED: 'FMEA 분석 시작',
  FMEA_PROGRESS: 'FMEA 진행',
  FMEA_COMPLETED: 'FMEA 분석 완료',
};
const CATEGORY_LABEL = {
  // 긴급
  emergency: '🚑 구급',
  fire: '🔥 화재',
  stop: '⛔ 긴급 작업중지',
  manager: '📞 관리자 연결',
  // 예방·관리
  incident: '⚠ 아차 사고',
  tbm: '📋 TBM 회의',
  settings: '⚙ 환경설정',
};

const counts = {
  emergency: 0, fire: 0, stop: 0,
  'manager-urgent': 0, 'manager-prevention': 0,
  incident: 0, tbm: 0, settings: 0,
};
const devices = new Set();
const startTime = Date.now();

document.getElementById('server-host').textContent = location.host;
document.getElementById('server-endpoint').textContent = location.origin;

function clock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('ko-KR', { hour12: false });
  const sec = Math.floor((Date.now() - startTime) / 1000);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  document.getElementById('uptime').textContent =
    `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
setInterval(clock, 1000); clock();

function renderEvent(e) {
  const data = e.data || {};
  const cat = data.category;
  let body = '';
  if (cat) body += `<div><span class="category">${CATEGORY_LABEL[cat] || cat}</span></div>`;
  if (data.transcript) body += `<div class="transcript">💬 "${data.transcript}"</div>`;
  if (data.event_id) body += `<div class="meta">EVENT_ID · ${data.event_id}</div>`;
  if (data.confidence !== undefined) body += `<div class="meta">신뢰도 ${(data.confidence * 100).toFixed(0)}%</div>`;
  if (data.recipients) body += `<div class="meta">수신자 ${data.recipients}명</div>`;
  if (data.manager) body += `<div class="meta">담당자: ${data.manager} · 내선 ${data.extension || ''}</div>`;
  body += `<div class="meta">📍 ${data.device_location || '-'} · ${data.device_id || '-'}</div>`;

  // ⭐ 아차사고인 경우 FMEA 영역을 미리 추가 (FMEA_STARTED 이벤트가 오면 채워짐)
  if (cat === 'incident' && data.event_id) {
    body += `<div class="fmea-section" id="fmea-${data.event_id}" style="display:none"></div>`;
  }

  const time = e.received_at ? new Date(e.received_at).toLocaleTimeString('ko-KR', { hour12: false }) : '-';
  const div = document.createElement('div');
  div.className = `event ${e.kind}`;
  if (data.event_id) div.setAttribute('data-event-id', data.event_id);
  div.innerHTML = `
    <div class="event-header">
      <span class="kind ${e.kind}">${KIND_LABEL[e.kind] || e.kind}</span>
      <span class="event-time">${time}</span>
    </div>
    <div class="event-body">${body}</div>
  `;
  return div;
}

// =====================================================================
// FMEA 이벤트 처리 - incident 카드에 정보 추가
// =====================================================================
const FMEA_STAGES = [
  { key: '1_query_expansion', label: '쿼리 보정' },
  { key: '2_db_search', label: '현장 조회' },
  { key: '3_accident_analyst', label: '사고 RAG 검색' },
  { key: '4_law_advisor', label: '법령 RAG 검색' },
  { key: '5_fmea_generator', label: 'FMEA 생성' },
];

function handleFmeaEvent(e) {
  const data = e.data || {};
  const eventId = data.event_id;
  if (!eventId) return;

  const fmeaDiv = document.getElementById(`fmea-${eventId}`);
  if (!fmeaDiv) return;

  fmeaDiv.style.display = 'block';

  if (e.kind === 'FMEA_STARTED') {
    // 5단계 진행 표시 초기화
    fmeaDiv.innerHTML = `
      <div class="fmea-header">⚙ FMEA 분석 진행 중...</div>
      <div class="fmea-stages">
        ${FMEA_STAGES.map((s, i) => `
          <div class="fmea-stage" data-stage="${s.key}" id="stage-${eventId}-${s.key}">
            <span class="stage-num">${i + 1}</span>
            <span class="stage-label">${s.label}</span>
            <span class="stage-status">⏳</span>
          </div>
        `).join('')}
      </div>
    `;
    showAlert('⚙ 아차사고 FMEA 분석 시작');

  } else if (e.kind === 'FMEA_PROGRESS') {
    const stageEl = document.getElementById(`stage-${eventId}-${data.stage}`);
    if (stageEl) {
      const statusEl = stageEl.querySelector('.stage-status');
      if (data.status === 'running') {
        stageEl.classList.add('running');
        statusEl.textContent = '●';
      } else if (data.status === 'ok') {
        stageEl.classList.remove('running');
        stageEl.classList.add('done');
        statusEl.textContent = '✓';
      } else if (data.status === 'error') {
        stageEl.classList.add('error');
        statusEl.textContent = '✗';
      }
    }

  } else if (e.kind === 'FMEA_COMPLETED') {
    if (!data.success) {
      fmeaDiv.innerHTML = `
        <div class="fmea-header" style="color: var(--emergency)">⚠ FMEA 분석 실패</div>
        <div class="fmea-error">${data.error || '알 수 없는 오류'}</div>
      `;
      return;
    }

    const finalFmea = data.final_fmea || {};
    const refinedQuery = data.refined_query || '';
    const siteInfo = data.site_info || {};

    let resultHtml = `
      <div class="fmea-header" style="color: var(--ok)">✓ FMEA 분석 완료 (${data.elapsed_sec || 0}초)</div>
    `;

    // 보정된 쿼리
    if (refinedQuery) {
      resultHtml += `
        <div class="fmea-block">
          <div class="fmea-block-title">🔄 보정된 쿼리</div>
          <div style="font-size:12px; color: var(--text); padding: 4px 0;">${escapeHtml(refinedQuery)}</div>
        </div>
      `;
    }

    // 현장 정보
    if (siteInfo && (siteInfo.work_type || siteInfo.id)) {
      resultHtml += `
        <div class="fmea-block">
          <div class="fmea-block-title">🏗 현장 정보</div>
          <div class="fmea-risk">
            ${siteInfo.id ? `<span>ID: <b>${escapeHtml(siteInfo.id)}</b></span>` : ''}
            ${siteInfo.work_type ? `<span>작업: <b>${escapeHtml(siteInfo.work_type)}</b></span>` : ''}
            ${siteInfo.worker_count != null ? `<span>인원: <b>${siteInfo.worker_count}</b>명</span>` : ''}
          </div>
          ${siteInfo.special_notes ? `<div style="font-size:11px; color: var(--dim); margin-top:4px;">📝 ${escapeHtml(siteInfo.special_notes)}</div>` : ''}
        </div>
      `;
    }

    // ⭐ FMEA 5항목 (한글 키)
    const sections = [
      { title: '⚠ 잠재적 사고 유형', key: '잠재적 사고 유형', color: 'var(--emergency)' },
      { title: '🔍 사고 원인',       key: '사고 원인',       color: 'var(--fire)' },
      { title: '📊 위험도',          key: '위험도',          color: 'var(--accent)' },
      { title: '⚖ 위법사항',         key: '위법사항',        color: '#A78BFA' },
      { title: '💡 대응 방안',       key: '대응방안',        color: 'var(--ok)' },
    ];

    for (const sec of sections) {
      const val = finalFmea[sec.key];
      if (val) {
        resultHtml += `
          <div class="fmea-block" style="border-left-color: ${sec.color}">
            <div class="fmea-block-title" style="color: ${sec.color}">${sec.title}</div>
            <div class="fmea-content">${escapeHtml(String(val))}</div>
          </div>
        `;
      }
    }

    fmeaDiv.innerHTML = resultHtml;
    showAlert('✓ FMEA 분석 완료');
  }
}

function escapeHtml(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function updateLatest(e) {
  const data = e.data || {};
  const cat = data.category;
  const catColor = {
    incident: 'var(--emergency)',
    tbm: 'var(--manager)',
    manager: 'var(--stop)',
    settings: '#A78BFA',
    // 구버전
    emergency: 'var(--emergency)',
    fire: 'var(--fire)',
    stop: 'var(--stop)',
  }[cat] || 'var(--accent)';

  let html = `<div style="font-size: 11px; letter-spacing: 3px; color: ${catColor}; margin-bottom: 4px;">LATEST · ${KIND_LABEL[e.kind] || e.kind}</div>`;
  if (cat) html += `<div class="big" style="color: ${catColor};">${CATEGORY_LABEL[cat] || cat}</div>`;
  if (data.transcript) html += `<div class="transcript" style="background: rgba(255,212,0,0.05); border-left: 2px solid var(--accent); padding: 12px 16px; margin-top: 8px; border-radius: 2px; font-style: italic;">💬 "${data.transcript}"</div>`;
  if (data.device_location) html += `<div style="margin-top: 12px; color: var(--dim); font-size: 12px;">📍 ${data.device_location} · ${data.device_id || ''}</div>`;

  document.getElementById('latest-event').innerHTML = html;
}

function showAlert(text) {
  const banner = document.createElement('div');
  banner.className = 'alert-banner';
  banner.textContent = text;
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 4000);
}

function addEvent(e, prepend = true) {
  const data = e.data || {};

  // ⭐ FMEA 관련 이벤트는 별도로 처리 (기존 카드에 정보 추가)
  if (e.kind === 'FMEA_STARTED' || e.kind === 'FMEA_PROGRESS' || e.kind === 'FMEA_COMPLETED') {
    handleFmeaEvent(e);
    return;
  }

  if (e.kind === 'REGISTER' && data.category) {
    let counterKey = data.category;
    // manager는 source(긴급/예방)에 따라 분리
    if (data.category === 'manager') {
      const source = (data.extra && data.extra.source) || 'urgent';
      counterKey = `manager-${source}`;
    }
    if (counts[counterKey] !== undefined) {
      counts[counterKey]++;
      const el = document.getElementById(`cnt-${counterKey}`);
      if (el) el.textContent = counts[counterKey];
    }
  }

  if (data.device_id) devices.add(data.device_id);
  document.getElementById('device-list').textContent = devices.size > 0 ? Array.from(devices).join(', ') : '없음';

  const list = document.getElementById('events');
  const empty = list.querySelector('.empty');
  if (empty) empty.remove();

  const node = renderEvent(e);
  if (prepend) list.insertBefore(node, list.firstChild);
  else list.appendChild(node);

  while (list.children.length > 50) list.removeChild(list.lastChild);

  updateLatest(e);

  if (e.kind === 'REGISTER') {
    const labels = {
      emergency: '🚑 구급 신고 접수',
      fire: '🔥 화재 신고 접수',
      stop: '⛔ 긴급 작업중지',
      manager: '📞 관리자 통화 완료',
      incident: '⚠ 아차 사고 신고 접수',
      tbm: '📋 TBM 회의 등록',
      settings: '⚙ 환경설정 변경',
    };
    let alertText = labels[data.category] || '이벤트 접수';
    if (data.category === 'manager' && data.extra && data.extra.source) {
      alertText = data.extra.source === 'prevention'
        ? '📞 관리자 통화 완료 (예방)'
        : '📞 관리자 통화 완료 (긴급)';
    }
    showAlert(alertText);
  }
  document.getElementById('event-count').textContent = `${list.children.length} EVENTS`;
}

fetch('/events').then(r => r.json()).then(d => { d.events.forEach(e => addEvent(e, false)); });

let eventSource;
function connect() {
  eventSource = new EventSource('/stream');
  eventSource.onopen = () => {
    document.getElementById('conn-status').textContent = 'CONNECTED';
    document.getElementById('conn-status').className = 'connection-status live';
  };
  eventSource.onmessage = (msg) => {
    try { addEvent(JSON.parse(msg.data), true); } catch (err) { console.error(err); }
  };
  eventSource.onerror = () => {
    document.getElementById('conn-status').textContent = 'RECONNECTING...';
    document.getElementById('conn-status').className = 'connection-status offline';
  };
}
connect();

function clearEvents() {
  if (!confirm('모든 이벤트를 지우시겠습니까?')) return;
  fetch('/events', { method: 'DELETE' }).then(() => {
    document.getElementById('events').innerHTML = '<div class="empty">// 이벤트 대기 중...</div>';
    Object.keys(counts).forEach(k => { counts[k] = 0; document.getElementById(`cnt-${k}`).textContent = 0; });
    document.getElementById('event-count').textContent = '0 EVENTS';
  });
}
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


# =====================================================================
# 시작 시 IP 안내 (Jetson에서 실행할 때 노트북 접속 주소 출력)
# =====================================================================
@app.on_event("startup")
async def announce():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        except Exception:
            pass
        finally:
            s.close()
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  EMERGENCY BELL · CONTROL CENTER")
    print("=" * 60)
    print(f"  서버 시작: {datetime.now().isoformat(timespec='seconds')}")
    print(f"\n  🖥  같은 네트워크의 노트북/PC에서 아래 주소 접속:")
    if ips:
        for ip in ips:
            print(f"     ▶  http://{ip}:8000/")
    print(f"     ▶  http://localhost:8000/  (Jetson 자기 자신)")
    print("\n" + "=" * 60 + "\n")
