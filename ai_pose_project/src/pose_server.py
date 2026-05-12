"""
FastAPI 자세 분석 서버

엔드포인트:
  POST /analyze
    요청 (JSON): { "image": "<base64>", "exercise": "squat"|"pushup" (생략 시 squat) }
    응답 (JSON): { "posture": "good"|"bad", "feedback": str, "angles": {...},
                  "exercise": "squat"|"pushup" }

  WS /ws  (연결 단위: VIDEO 모드 랜드마커 LivePoseSession + rep 카운트·이슈 통계 누적)
    클라이언트 → 서버: { "type": "frame",   "image": "<base64>", "exercise": ... }
                     { "type": "reset",   "exercise": ... }   # 생략 시 세션 전체 초기화
                     { "type": "summary" }
    서버 → 클라이언트: { "type": "result",   "posture", "feedback", "angles", "issues",
                                            "exercise", "count", "stage", "rep_completed" }
                     { "type": "reset_ok", "exercise": ... }
                     { "type": "summary",  "summary": {...} }
                     { "type": "error",    "message": "..." }

실행:
  uvicorn pose_server:app --host 0.0.0.0 --port 8000 --reload
"""
import asyncio
import base64
import binascii
import io
import logging

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from test_pose_8 import (
    analyze_pose,
    LivePoseSession,
    UnsupportedExerciseError,
    EXERCISE_REGISTRY,
)
from session_state import ExerciseSessionManager
from feedback_messages import MESSAGES as MSG

logger = logging.getLogger("pose_server")
logging.basicConfig(level=logging.INFO)


# ──────────────────────────────────────────────────────────────
# FastAPI 앱 + CORS
# ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="ModuFlow Pose Analyzer",
    description="MediaPipe 기반 실시간 자세 분석 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 모바일/웹 어디서든 접근 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# 요청 / 응답 스키마
# ──────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    image: str = Field(..., description="base64 인코딩된 이미지 문자열")
    exercise: str = Field(
        default="squat",
        description='분석할 운동 종류 ("squat" | "pushup"). 생략 시 squat.',
    )


class AnalyzeResponse(BaseModel):
    posture: str
    feedback: str
    angles: dict
    exercise: str


# ──────────────────────────────────────────────────────────────
# base64 → numpy(BGR) 디코딩
# ──────────────────────────────────────────────────────────────
def decode_base64_image(image_b64: str) -> np.ndarray:
    """
    base64 문자열을 OpenCV BGR numpy 배열로 변환한다.
    실패 시 HTTPException(400)을 발생시킨다.
    """
    if not image_b64:
        raise HTTPException(status_code=400, detail="image 필드가 비어 있습니다.")

    # data URL 접두어 제거: "data:image/jpeg;base64,...."
    if image_b64.startswith("data:"):
        try:
            image_b64 = image_b64.split(",", 1)[1]
        except IndexError:
            raise HTTPException(status_code=400, detail="잘못된 data URL 형식입니다.")

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="base64 디코딩에 실패했습니다.")

    # PIL로 1차 디코딩 (JPEG/PNG 모두 지원, 색공간 정규화)
    try:
        pil_img = Image.open(io.BytesIO(raw)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="이미지 파일 형식을 인식할 수 없습니다.")

    rgb = np.array(pil_img)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr


# ──────────────────────────────────────────────────────────────
# 라우트
# ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "ModuFlow Pose Analyzer", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    image = decode_base64_image(req.image)

    try:
        result = analyze_pose(image, exercise=req.exercise)
    except UnsupportedExerciseError:
        raise HTTPException(status_code=400, detail=MSG["unsupported_exercise"])
    except Exception:
        logger.exception("자세 분석 중 예외 (exercise=%s)", req.exercise)
        raise HTTPException(status_code=500, detail=MSG["inference_failed"])

    return result


# ──────────────────────────────────────────────────────────────
# WebSocket 헬퍼
# ──────────────────────────────────────────────────────────────
def _decode_image_safe(image_b64: str) -> np.ndarray:
    """
    WebSocket 핸들러용 base64 디코더.
    HTTPException 대신 ValueError로 통일하여 위쪽에서 에러 메시지로 보낸다.
    """
    if not image_b64:
        raise ValueError("image 필드가 비어 있습니다.")

    if image_b64.startswith("data:"):
        try:
            image_b64 = image_b64.split(",", 1)[1]
        except IndexError:
            raise ValueError("잘못된 data URL 형식입니다.")

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("base64 디코딩에 실패했습니다.")

    try:
        pil_img = Image.open(io.BytesIO(raw)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise ValueError("이미지 파일 형식을 인식할 수 없습니다.")

    rgb = np.array(pil_img)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _process_frame_blocking(live: LivePoseSession, image_b64: str, exercise: str) -> dict:
    """디코딩 + (연결별 VIDEO 모드) 자세 분석 (CPU bound). 별도 스레드에서 실행됨."""
    image = _decode_image_safe(image_b64)
    return live.analyze(image, exercise=exercise)


# ──────────────────────────────────────────────────────────────
# WebSocket 엔드포인트
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_analyze(websocket: WebSocket):
    """
    실시간 자세 분석용 WebSocket.

    연결마다:
      - LivePoseSession (VIDEO 모드 랜드마커 + 연결별 분석기 인스턴스) — 프레임 간
        트래킹/스무딩으로 랜드마크 안정화. 종료 시 close().
      - ExerciseSessionManager — 운동별 rep 카운트·이슈 통계 누적.
    운동 전환 시에도 각 운동의 누적 상태는 보존된다. 연결이 끊기면 세션도 종료.

    수신:
      {"type": "frame",   "image": "<base64>", "exercise": "squat"}
      {"type": "reset",   "exercise": "squat"}   # exercise 생략 시 세션 전체 초기화
      {"type": "summary"}                          # 현재까지의 세션 요약 요청

    송신:
      {"type": "result",   "posture", "feedback", "angles", "issues",
                           "exercise", "count", "stage", "rep_completed"}
      {"type": "reset_ok", "exercise": <초기화한 운동명 또는 null>}
      {"type": "summary",  "summary": { ... ExerciseSessionManager.get_summary() ... }}
      {"type": "error",    "message": "..."}      # 개별 프레임 에러는 연결 유지
    """
    await websocket.accept()
    client  = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
    session = ExerciseSessionManager()
    try:
        live = LivePoseSession()
    except Exception:
        logger.exception("LivePoseSession 생성 실패")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return
    logger.info("WS 연결: %s (session=%s)", client, session.session_id)

    try:
        while True:
            # 클라이언트로부터 JSON 수신 (연결 유지)
            try:
                msg = await websocket.receive_json()
            except ValueError:
                await websocket.send_json({"type": "error", "message": "JSON 파싱 실패"})
                continue

            msg_type = msg.get("type")

            # ── 세션 초기화 ──────────────────────────────────
            if msg_type == "reset":
                ex = msg.get("exercise")
                if ex is not None and ex not in EXERCISE_REGISTRY:
                    await websocket.send_json({"type": "error", "message": MSG["unsupported_exercise"]})
                    continue
                session.reset(ex)
                await websocket.send_json({"type": "reset_ok", "exercise": ex})
                continue

            # ── 세션 요약 ────────────────────────────────────
            if msg_type == "summary":
                await websocket.send_json({"type": "summary", "summary": session.get_summary()})
                continue

            # ── 프레임 분석 ──────────────────────────────────
            if msg_type != "frame":
                await websocket.send_json({"type": "error", "message": f"지원하지 않는 type: {msg_type}"})
                continue

            image_b64 = msg.get("image", "")
            exercise  = msg.get("exercise", "squat")

            # CPU 바운드 작업(디코딩 + MediaPipe 추론)을 스레드로 보내
            # 이벤트 루프가 다른 연결을 처리할 수 있게 한다.
            try:
                result = await asyncio.to_thread(
                    _process_frame_blocking, live, image_b64, exercise,
                )
            except UnsupportedExerciseError:
                await websocket.send_json({"type": "error", "message": MSG["unsupported_exercise"]})
                continue
            except ValueError as e:
                await websocket.send_json({"type": "error", "message": str(e)})
                continue
            except Exception:
                logger.exception("자세 분석 중 예외 (exercise=%s)", exercise)
                await websocket.send_json({"type": "error", "message": MSG["inference_failed"]})
                continue

            # 세션 매니저에 결과 반영 → count / stage / rep_completed 부가.
            # 사람 미검출 등으로 angles 가 비어도 RepCounter 가 그대로 무시하므로 안전.
            # (exercise 는 analyze_pose 에서 이미 검증됨 → update 가 추가로 던지지 않음)
            enriched = session.update(exercise, result)

            await websocket.send_json({
                "type":          "result",
                "posture":       enriched["posture"],
                "feedback":      enriched["feedback"],
                "angles":        enriched["angles"],
                "issues":        enriched.get("issues", []),
                "exercise":      enriched["exercise"],
                "count":         enriched["count"],
                "stage":         enriched["stage"],
                "rep_completed": enriched["rep_completed"],
            })

    except WebSocketDisconnect:
        logger.info("WS 연결 해제: %s — summary=%s", client, session.get_summary())
    except Exception as e:
        logger.exception("WS 처리 중 예기치 않은 예외: %s", e)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        live.close()
