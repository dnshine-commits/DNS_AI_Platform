"""
Server Client - 관제 시스템 / 비상망 / 매니저 연결
모든 통신은 httpx async 사용. 실패 시 로컬 큐에 적재 후 재전송.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from . import config

logger = logging.getLogger(__name__)

# 통신 실패 시 로컬 적재 (오프라인 복구용)
OFFLINE_QUEUE = config.LOG_DIR / "offline_queue.jsonl"


# ===========================================================
# 공통 HTTP 헬퍼
# ===========================================================
async def _post(endpoint: str, payload: dict, timeout: float = 5.0) -> dict:
    """POST 요청 - 실패 시 로컬 큐 적재 후 더미 응답 반환"""
    payload["device_id"] = config.DEVICE_ID
    payload["device_location"] = config.DEVICE_LOCATION
    payload["timestamp"] = datetime.utcnow().isoformat()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(endpoint, json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error(f"통신 실패 [{endpoint}]: {e} - 로컬 큐에 적재")
        with open(OFFLINE_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"endpoint": endpoint, "payload": payload}, ensure_ascii=False) + "\n")
        return {"offline": True, "queued": True, "error": str(e)}


# ===========================================================
# 1. ASR 세션 활성화
# ===========================================================
async def activate_asr() -> dict:
    """관제 서버에 ASR 세션 시작을 통지"""
    logger.info("ASR 세션 요청")
    return await _post(config.ENDPOINTS["asr_session"], {
        "action": "activate",
    })


# ===========================================================
# 2. 전사 결과 서버 전송
# ===========================================================
async def send_transcript(category: str, transcript: str, confidence: float) -> dict:
    """
    Whisper 전사 결과를 서버에 전송.
    category: "emergency" | "fire" | "stop"
    """
    logger.info(f"전사 결과 전송 [{category}]: {transcript[:30]}...")
    return await _post(config.ENDPOINTS["transcribe"], {
        "category": category,
        "transcript": transcript,
        "confidence": confidence,
    })


# ===========================================================
# 3. 비상망 전파
# ===========================================================
async def broadcast_emergency(category: str, message: str = "") -> dict:
    """
    비상망 전파 - 사내 안전망에 즉시 알림.
    화재/긴급작업중지에서 호출.
    """
    logger.info(f"비상망 전파 [{category}]")
    return await _post(config.ENDPOINTS["broadcast"], {
        "category": category,
        "message": message,
        "priority": "HIGH",
    })


# ===========================================================
# 4. 관제 시스템 등록
# ===========================================================
async def register_event(category: str, transcript: str = "", extra: Optional[dict] = None) -> dict:
    """
    최종 이벤트를 관제 시스템에 등록.
    모든 워크플로우의 마지막 단계에서 호출.
    """
    payload = {
        "category": category,
        "transcript": transcript,
        "extra": extra or {},
    }
    logger.info(f"관제 등록 [{category}]")
    return await _post(config.ENDPOINTS["register"], payload)


# ===========================================================
# 5. 관리자 통화 연결
# ===========================================================
async def connect_manager() -> dict:
    """관리자 통화 연결 (실제로는 SIP/WebRTC, 여기선 통화 ID만 발급)"""
    logger.info("관리자 통화 연결 요청")
    return await _post(config.ENDPOINTS["manager"], {
        "action": "connect",
    })


# ===========================================================
# 6. 오프라인 큐 재전송
# ===========================================================
async def flush_offline_queue() -> int:
    """네트워크 복구 후 오프라인 큐를 재전송. 성공한 항목 수 반환."""
    if not OFFLINE_QUEUE.exists():
        return 0

    success = 0
    remaining = []
    with open(OFFLINE_QUEUE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    for line in lines:
        try:
            item = json.loads(line)
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(item["endpoint"], json=item["payload"])
                if r.status_code < 400:
                    success += 1
                    continue
        except Exception:
            pass
        remaining.append(line)

    # 실패 항목만 다시 기록
    with open(OFFLINE_QUEUE, "w", encoding="utf-8") as f:
        f.write("\n".join(remaining) + ("\n" if remaining else ""))

    if success:
        logger.info(f"오프라인 큐 재전송: {success}건 성공, {len(remaining)}건 잔여")
    return success
