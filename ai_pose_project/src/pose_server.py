"""
FastAPI 자세 분석 서버

엔드포인트:
  POST /analyze
    요청 (JSON): { "image": "<base64>", "exercise": "squat"|"pushup" (생략 시 squat) }
    응답 (JSON): { "posture": "good"|"bad", "feedback": str, "angles": {...},
                  "exercise": "squat"|"pushup" }

  WS /ws
    클라이언트 → 서버: { "type": "frame", "image": "<base64>", "exercise": ... }
    서버 → 클라이언트: { "type": "result", "posture", "feedback", "angles", "exercise" }
                     { "type": "error",  "message": "..." }

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

from test_pose_8 import analyze_pose, UnsupportedExerciseError
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


def _process_frame_blocking(image_b64: str, exercise: str) -> dict:
    """디코딩 + 자세 분석 (CPU bound). 별도 스레드에서 실행됨."""
    image = _decode_image_safe(image_b64)
    return analyze_pose(image, exercise=exercise)


# ──────────────────────────────────────────────────────────────
# WebSocket 엔드포인트
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_analyze(websocket: WebSocket):
    """
    실시간 자세 분석용 WebSocket.

    수신: {"type": "frame", "image": "<base64>"}
    송신: {"type": "result", "posture": ..., "feedback": ..., "angles": {...}}
          {"type": "error",  "message": "..."}
    """
    await websocket.accept()
    client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
    logger.info("WS 연결: %s", client)

    try:
        while True:
            # 클라이언트로부터 JSON 수신 (연결 유지)
            try:
                msg = await websocket.receive_json()
            except ValueError:
                await websocket.send_json({
                    "type": "error",
                    "message": "JSON 파싱 실패",
                })
                continue

            msg_type = msg.get("type")
            if msg_type != "frame":
                await websocket.send_json({
                    "type": "error",
                    "message": f"지원하지 않는 type: {msg_type}",
                })
                continue

            image_b64 = msg.get("image", "")
            exercise  = msg.get("exercise", "squat")

            # CPU 바운드 작업(디코딩 + MediaPipe 추론)을 스레드로 보내
            # 이벤트 루프가 다른 연결을 처리할 수 있게 한다.
            try:
                result = await asyncio.to_thread(
                    _process_frame_blocking, image_b64, exercise,
                )
            except UnsupportedExerciseError:
                await websocket.send_json({
                    "type": "error",
                    "message": MSG["unsupported_exercise"],
                })
                continue
            except ValueError as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
                continue
            except Exception:
                logger.exception("자세 분석 중 예외 (exercise=%s)", exercise)
                await websocket.send_json({
                    "type": "error",
                    "message": MSG["inference_failed"],
                })
                continue

            await websocket.send_json({
                "type":     "result",
                "posture":  result["posture"],
                "feedback": result["feedback"],
                "angles":   result["angles"],
                "exercise": result["exercise"],
            })

    except WebSocketDisconnect:
        logger.info("WS 연결 해제: %s", client)
    except Exception as e:
        logger.exception("WS 처리 중 예기치 않은 예외: %s", e)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
