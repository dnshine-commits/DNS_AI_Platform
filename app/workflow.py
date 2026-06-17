"""
Workflow Engine - 비상 시나리오 실행

긴급 (우측 메뉴):
  - emergency : 구급 신고
  - fire      : 화재 신고
  - stop      : 긴급 작업중지
  - manager   : 관리자 연결

예방·관리 (좌측 메뉴):
  - incident  : 아차 사고 신고  (긴 발화, 종료 버튼으로 끝)
  - tbm       : TBM (Tool Box Meeting, 작업 전 안전 점검 회의 기록)
  - settings  : 환경 설정 (UI에서 직접 처리, 워크플로우 아님)
  - manager   : 관리자 연결 (양쪽 동일)
"""
import asyncio
import logging
from typing import AsyncIterator, Optional
from dataclasses import dataclass

from . import asr_service, server_client, config

logger = logging.getLogger(__name__)


@dataclass
class FlowEvent:
    """워크플로우 진행 이벤트 - UI에 전달"""
    step_index: int
    step_name: str
    status: str  # "running" | "ok" | "error"
    detail: str = ""
    transcript: str = ""
    audio_level: float = 0.0
    event_id: str = ""


# ===========================================================
# 워크플로우 메타데이터 (UI가 메뉴 만들 때 사용)
# ===========================================================
FLOWS = {
    # --- 긴급 (우측 메뉴) ---
    "emergency": {
        "label": "구급 신고",
        "icon": "🚑",
        "color_key": "emergency",
        "category": "urgent",
        "steps": [
            "ASR 활성화",
            "상황 발화 수집",
            "Whisper 전사",
            "구급 메시지 서버 전송",
            "관제 등록",
        ],
    },
    "fire": {
        "label": "화재 신고",
        "icon": "🔥",
        "color_key": "fire",
        "category": "urgent",
        "steps": [
            "ASR 활성화",
            "상황 발화 수집",
            "Whisper 전사",
            "화재 메시지 서버 전송",
            "비상망 전파",
            "관제 등록",
        ],
    },
    "stop": {
        "label": "긴급 작업중지",
        "icon": "⛔",
        "color_key": "stop",
        "category": "urgent",
        "steps": [
            "비상망 즉시 전파",
            "ASR 활성화",
            "작업중지 사유 발화",
            "Whisper 전사",
            "서버 연계",
            "관제 등록",
        ],
    },
    "manager": {
        "label": "관리자 연결",
        "icon": "📞",
        "color_key": "manager",
        "category": "both",  # 양쪽 메뉴 공용
        "steps": [
            "관리자 통화 연결",
            "통화 진행",
            "통화 내역 관제 등록",
        ],
    },

    # --- 예방·관리 (좌측 메뉴) ---
    "incident": {
        "label": "아차 사고 신고",
        "icon": "⚠",
        "color_key": "incident",
        "category": "prevention",
        "long_record": True,  # 종료 버튼으로 끝내는 긴 녹음
        "steps": [
            "ASR 활성화",
            "사고 내용 발화",
            "Whisper 전사",
            "관제 등록",
        ],
    },
    "tbm": {
        "label": "TBM 등록",
        "icon": "📋",
        "color_key": "tbm",
        "category": "prevention",
        "long_record": True,  # 종료 버튼으로 끝내는 긴 녹음
        "steps": [
            "ASR 활성화",
            "회의 내용 발화",
            "Whisper 전사",
            "관제 등록",
        ],
    },
    "settings": {
        "label": "환경 설정",
        "icon": "⚙",
        "color_key": "settings",
        "category": "prevention",
        "ui_only": True,  # 워크플로우 없음 - UI에서 직접 처리
        "steps": [],
    },
}


# ===========================================================
# 워크플로우 실행 - stop_event를 통해 외부에서 녹음 중단 가능
# ===========================================================
async def run_flow(
    flow_key: str,
    stop_event: Optional[asyncio.Event] = None,
    source: str = "urgent",  # "urgent" | "prevention" - 관리자 연결 출처 구분
) -> AsyncIterator[FlowEvent]:
    """
    워크플로우 실행. 각 단계마다 FlowEvent를 yield → UI가 실시간 반영.
    stop_event는 사용자가 "종료" 버튼을 눌렀을 때 set됨 → 녹음 즉시 중단.
    """
    flow = FLOWS[flow_key]
    logger.info(f"=== {flow['label']} 워크플로우 시작 ===")

    transcript = ""
    event_id = ""

    # ========== 분기 1: 긴급 시나리오 - 구급/화재 ==========
    if flow_key in ("emergency", "fire"):
        yield FlowEvent(0, flow["steps"][0], "running", "서버에 ASR 세션 요청 중")
        await server_client.activate_asr()
        yield FlowEvent(0, flow["steps"][0], "ok")

        yield FlowEvent(1, flow["steps"][1], "running", "발생상황을 말씀해 주세요")
        audio = await asr_service.record_audio(
            max_duration=config.RECORD_SECONDS,
            stop_event=stop_event,
        )

        yield FlowEvent(2, flow["steps"][2], "running", "Whisper 모델 추론 중")
        result = await asr_service.transcribe(audio)
        transcript = result["text"]
        yield FlowEvent(2, flow["steps"][2], "ok",
                        detail=f"신뢰도 {result['confidence']:.0%}",
                        transcript=transcript)

        yield FlowEvent(3, flow["steps"][3], "running")
        await server_client.send_transcript(flow_key, transcript, result["confidence"])
        yield FlowEvent(3, flow["steps"][3], "ok")

        if flow_key == "fire":
            yield FlowEvent(4, flow["steps"][4], "running", "사내 안전망 알림 송출")
            await server_client.broadcast_emergency("fire", transcript)
            yield FlowEvent(4, flow["steps"][4], "ok")

        last = len(flow["steps"]) - 1
        yield FlowEvent(last, flow["steps"][last], "running")
        ev = await server_client.register_event(flow_key, transcript)
        event_id = ev.get("event_id", "")
        yield FlowEvent(last, flow["steps"][last], "ok", event_id=event_id)

    # ========== 분기 2: 긴급 작업중지 ==========
    elif flow_key == "stop":
        yield FlowEvent(0, flow["steps"][0], "running", "안전망 즉시 전파")
        await server_client.broadcast_emergency("stop")
        yield FlowEvent(0, flow["steps"][0], "ok")

        yield FlowEvent(1, flow["steps"][1], "running")
        await server_client.activate_asr()
        yield FlowEvent(1, flow["steps"][1], "ok")

        yield FlowEvent(2, flow["steps"][2], "running", "작업중지 사유를 말씀해 주세요")
        audio = await asr_service.record_audio(
            max_duration=config.RECORD_SECONDS,
            stop_event=stop_event,
        )

        yield FlowEvent(3, flow["steps"][3], "running")
        result = await asr_service.transcribe(audio)
        transcript = result["text"]
        yield FlowEvent(3, flow["steps"][3], "ok",
                        detail=f"신뢰도 {result['confidence']:.0%}",
                        transcript=transcript)

        yield FlowEvent(4, flow["steps"][4], "running")
        await server_client.send_transcript("stop", transcript, result["confidence"])
        yield FlowEvent(4, flow["steps"][4], "ok")

        yield FlowEvent(5, flow["steps"][5], "running")
        ev = await server_client.register_event("stop", transcript)
        event_id = ev.get("event_id", "")
        yield FlowEvent(5, flow["steps"][5], "ok", event_id=event_id)

    # ========== 분기 3: 관리자 연결 ==========
    elif flow_key == "manager":
        yield FlowEvent(0, flow["steps"][0], "running", "관리자 호출 중")
        call = await server_client.connect_manager()
        manager_name = call.get("manager", "안전관리자")
        extension = call.get("extension", "0000")
        yield FlowEvent(0, flow["steps"][0], "ok",
                        detail=f"{manager_name} (내선 {extension})")

        yield FlowEvent(1, flow["steps"][1], "running",
                        "통화 중... (종료 버튼을 눌러주세요)")
        # 통화 종료를 stop_event 또는 30초 타임아웃으로 처리
        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30.0)
                logger.info("관리자 통화 사용자 종료")
            except asyncio.TimeoutError:
                logger.info("관리자 통화 타임아웃 (30초)")
        else:
            await asyncio.sleep(3)
        yield FlowEvent(1, flow["steps"][1], "ok")

        yield FlowEvent(2, flow["steps"][2], "running")
        ev = await server_client.register_event(
            "manager", "",
            extra={
                "manager": manager_name,
                "call_id": call.get("call_id"),
                "source": source,  # urgent | prevention
            }
        )
        event_id = ev.get("event_id", "")
        yield FlowEvent(2, flow["steps"][2], "ok", event_id=event_id)

    # ========== 분기 4: 아차 사고 / TBM (긴 발화 + 종료 버튼) ==========
    elif flow_key in ("incident", "tbm"):
        yield FlowEvent(0, flow["steps"][0], "running", "ASR 세션 요청")
        await server_client.activate_asr()
        yield FlowEvent(0, flow["steps"][0], "ok")

        prompt = ("아차 사고 내용을 말씀해 주세요\n(종료 버튼을 눌러 마무리)"
                  if flow_key == "incident"
                  else "TBM 회의 내용을 말씀해 주세요\n(종료 버튼을 눌러 마무리)")

        yield FlowEvent(1, flow["steps"][1], "running", prompt)
        # 최대 10분 (RECORD_SECONDS_LONG)까지 녹음, 사용자가 종료 누르면 끝
        audio = await asr_service.record_audio(
            max_duration=config.RECORD_SECONDS_LONG,
            stop_event=stop_event,
        )

        yield FlowEvent(2, flow["steps"][2], "running", "Whisper 모델 추론 중")
        result = await asr_service.transcribe(audio)
        transcript = result["text"]
        yield FlowEvent(2, flow["steps"][2], "ok",
                        detail=f"신뢰도 {result['confidence']:.0%}",
                        transcript=transcript)

        yield FlowEvent(3, flow["steps"][3], "running")
        ev = await server_client.register_event(flow_key, transcript)
        event_id = ev.get("event_id", "")
        yield FlowEvent(3, flow["steps"][3], "ok", event_id=event_id)

    logger.info(f"=== {flow['label']} 완료 (event_id={event_id}) ===")
