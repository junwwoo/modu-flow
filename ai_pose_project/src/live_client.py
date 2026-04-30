"""
실시간 자세 분석 클라이언트.

웹캠 프레임을 WebSocket으로 pose_server에 전송하고,
서버가 반환한 posture/feedback/angles를 화면에 오버레이한다.

전제: pose_server가 ws://127.0.0.1:8000/ws 에서 실행 중이어야 함.
조작: ESC 종료
"""
import asyncio
import base64
import json
import time

import cv2
import websockets

WS_URL       = "ws://127.0.0.1:8000/ws"
JPEG_QUALITY = 70  # 네트워크 부하 절감을 위해 적당히 압축


def draw_overlay(frame, result, fps, latency_ms):
    h, w = frame.shape[:2]
    posture  = result.get("posture", "?")
    feedback = result.get("feedback", "")
    angles   = result.get("angles", {})

    color = (0, 200, 0) if posture == "good" else (0, 100, 255)

    # 상단 상태 패널
    cv2.rectangle(frame, (10, 10), (w - 10, 110), (30, 30, 30), -1)
    cv2.rectangle(frame, (10, 10), (w - 10, 110), color, 2)
    cv2.putText(frame, f"POSTURE: {posture.upper()}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.putText(frame, feedback[:90],
                (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(frame, f"FPS:{fps:.1f}  LATENCY:{latency_ms:.0f}ms",
                (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    # 좌하단 각도 패널
    if angles:
        y = h - 100
        for name, val in angles.items():
            cv2.putText(frame, f"{name:12s}: {val:6.1f}",
                        (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            y += 20


async def run():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] 웹캠을 열 수 없습니다.")
        return

    print(f"[연결 시도] {WS_URL}")
    try:
        ws = await websockets.connect(WS_URL, max_size=4 * 1024 * 1024)
    except Exception as e:
        print(f"[ERROR] 서버 연결 실패: {e}")
        cap.release()
        return

    print("[연결 OK]  ESC로 종료")
    fps    = 0.0
    last_t = time.time()
    n_recv = 0
    n_err  = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] 프레임 읽기 실패")
                break

            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                continue
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")

            t0 = time.time()
            await ws.send(json.dumps({"type": "frame", "image": b64}))
            data = json.loads(await ws.recv())
            latency_ms = (time.time() - t0) * 1000

            now    = time.time()
            dt     = now - last_t
            last_t = now
            inst_fps = 1.0 / dt if dt > 0 else 0.0
            fps = (0.85 * fps + 0.15 * inst_fps) if fps else inst_fps

            if data.get("type") == "result":
                n_recv += 1
                draw_overlay(frame, data, fps, latency_ms)
            else:
                n_err += 1
                cv2.putText(frame, f"ERROR: {data.get('message')}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 255), 2)

            cv2.imshow("Live Pose Analysis (ESC to quit)", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        await ws.close()
        cap.release()
        cv2.destroyAllWindows()
        print(f"\n[종료] 수신 결과 {n_recv}건 / 에러 {n_err}건")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[중단]")
