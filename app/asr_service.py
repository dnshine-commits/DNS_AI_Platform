"""
ASR Service - Jetson 로컬에서 마이크 녹음 후 OpenAI Whisper로 전사
사용 모델: openai-whisper (원본)

v2 변경점: 녹음 도중 외부에서 stop_event로 즉시 중단 가능
            (사용자가 "종료" 버튼을 누르면 바로 전사 시작)
"""
import asyncio
import logging
import threading
import numpy as np
import sounddevice as sd
from typing import Optional, Callable

from . import config

logger = logging.getLogger(__name__)

# ===========================================================
# Whisper 모델 - 모듈 로드 시 한 번만 초기화 (메모리 절약)
# ===========================================================
_whisper_model = None


def get_whisper_model():
    """OpenAI Whisper 모델 lazy 로딩"""
    global _whisper_model
    if _whisper_model is None:
        import whisper
        import torch

        device = "cuda" if torch.cuda.is_available() and config.WHISPER_DEVICE == "cuda" else "cpu"
        logger.info(f"Whisper 모델 로딩 중: {config.WHISPER_MODEL_SIZE} ({device})")

        try:
            _whisper_model = whisper.load_model(
                config.WHISPER_MODEL_SIZE,
                device=device,
            )
            logger.info(f"Whisper 모델 로딩 완료 ({device})")
        except Exception as e:
            logger.error(f"Whisper GPU 로딩 실패, CPU로 폴백: {e}")
            _whisper_model = whisper.load_model(config.WHISPER_MODEL_SIZE, device="cpu")
            logger.info("Whisper 모델 로딩 완료 (CPU)")

    return _whisper_model


# ===========================================================
# 마이크 녹음 (중단 가능)
# ===========================================================
async def record_audio(
    max_duration: float = config.RECORD_SECONDS,
    on_level: Optional[Callable[[float], None]] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> np.ndarray:
    """
    마이크에서 최대 max_duration 초 동안 PCM 16kHz mono 녹음.
    stop_event가 set되면 즉시 녹음 중단 후 그 시점까지의 오디오 반환.

    on_level 콜백으로 실시간 음량(0~1) 전달 → UI 사운드 웨이브.
    """
    loop = asyncio.get_event_loop()

    sample_rate = config.AUDIO_SAMPLE_RATE
    channels = config.AUDIO_CHANNELS

    # 녹음 데이터를 청크 단위로 누적 (스트리밍 방식)
    chunks = []
    stop_flag = threading.Event()

    # stop_event 모니터링: asyncio Event를 threading Event로 다리 놓기
    async def _watch_stop():
        if stop_event is None:
            return
        await stop_event.wait()
        stop_flag.set()
        logger.info("녹음 중단 신호 수신")

    watch_task = asyncio.create_task(_watch_stop()) if stop_event else None

    def _record():
        """별도 스레드에서 녹음 + 음량 모니터링"""
        chunk_duration = 0.05  # 50ms 단위
        chunk_frames = int(sample_rate * chunk_duration)
        max_chunks = int(max_duration / chunk_duration)

        logger.info(f"녹음 시작 (최대 {max_duration}초)")

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                device=config.AUDIO_DEVICE_INDEX,
                blocksize=chunk_frames,
            ) as stream:
                for i in range(max_chunks):
                    if stop_flag.is_set():
                        logger.info(f"녹음 종료 (사용자 중단, {i * chunk_duration:.1f}초 수집)")
                        break

                    data, overflowed = stream.read(chunk_frames)
                    if overflowed:
                        logger.warning("오디오 버퍼 오버플로우")
                    chunks.append(data.copy())

                    # 음량 RMS 계산 → UI에 전달
                    if on_level:
                        rms = float(np.sqrt(np.mean(np.square(data))))
                        on_level(min(rms * 10, 1.0))
                else:
                    logger.info(f"녹음 종료 (최대 시간 {max_duration}초 도달)")

        except Exception as e:
            logger.exception(f"녹음 중 오류: {e}")
            raise

        if not chunks:
            return np.zeros(int(sample_rate * 0.5), dtype=np.float32)
        return np.concatenate(chunks).flatten()

    try:
        audio = await loop.run_in_executor(None, _record)
    finally:
        if watch_task is not None and not watch_task.done():
            watch_task.cancel()

    return audio


# ===========================================================
# Whisper 전사
# ===========================================================
async def transcribe(audio: np.ndarray) -> dict:
    """
    PCM float32 1D 오디오 → Whisper 전사 결과 dict
    """
    loop = asyncio.get_event_loop()

    def _transcribe():
        model = get_whisper_model()

        # 너무 짧은 오디오는 전사 불가 (Whisper는 최소 0.5초 정도 필요)
        if len(audio) < config.AUDIO_SAMPLE_RATE * 0.3:
            return {
                "text": "(음성이 너무 짧습니다)",
                "confidence": 0.0,
                "language": config.WHISPER_LANGUAGE,
                "duration": float(len(audio)) / config.AUDIO_SAMPLE_RATE,
            }

        result = model.transcribe(
            audio.astype(np.float32),
            language=config.WHISPER_LANGUAGE,
            fp16=(config.WHISPER_DEVICE == "cuda"),
            verbose=False,
        )

        segments = result.get("segments", [])
        if segments:
            avg_logprob = float(np.mean([s.get("avg_logprob", -1.0) for s in segments]))
            confidence = float(np.exp(avg_logprob))
        else:
            confidence = 0.0

        text = (result.get("text") or "").strip()

        if segments:
            duration = max((s.get("end", 0.0) for s in segments), default=0.0)
        else:
            duration = float(len(audio)) / config.AUDIO_SAMPLE_RATE

        return {
            "text": text or "(음성 인식 실패 - 다시 시도해 주세요)",
            "confidence": confidence,
            "language": result.get("language", config.WHISPER_LANGUAGE),
            "duration": duration,
        }

    logger.info("Whisper 전사 시작")
    result = await loop.run_in_executor(None, _transcribe)
    logger.info(f"전사 완료: '{result['text']}' (신뢰도 {result['confidence']:.2f})")
    return result


# ===========================================================
# 통합 헬퍼: 녹음 + 전사 한번에 (stop_event 지원)
# ===========================================================
async def record_and_transcribe(
    max_duration: float = config.RECORD_SECONDS,
    on_level: Optional[Callable[[float], None]] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> dict:
    audio = await record_audio(max_duration, on_level, stop_event)
    return await transcribe(audio)


# ===========================================================
# 단독 테스트
# ===========================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        print("=== ASR 단독 테스트 (OpenAI Whisper) ===")
        print(f"최대 {config.RECORD_SECONDS}초간 녹음합니다. 발화해 주세요...")
        result = await record_and_transcribe()
        print(f"\n전사 결과: {result['text']}")
        print(f"신뢰도: {result['confidence']:.2%}")

    asyncio.run(main())
