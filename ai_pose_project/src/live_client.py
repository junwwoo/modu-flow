"""
실시간 자세 분석 클라이언트.

웹캠 프레임을 WebSocket으로 pose_server에 전송하고,
서버가 반환한 posture/feedback/angles/issues를 화면에 오버레이한다.

11주차 확장: 1/2/3 키로 운동 전환(squat/pushup/lunge),
클라이언트 측 ExerciseSessionManager로 운동별 카운트·이슈 통계를
우측 패널에 누적 표시한다. 운동 전환 시 각 운동의 누적 상태는 보존.

전제: pose_server가 ws://127.0.0.1:8000/ws 에서 실행 중이어야 함.
조작:
    ESC      종료
    1        squat
    2        pushup
    3        lunge
"""
import asyncio
import base64
import json
import os
import sys
import time

import cv2
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from session_state import ExerciseSessionManager  # noqa: E402

WS_URL       = "ws://127.0.0.1:8000/ws"
JPEG_QUALITY = 70  # 네트워크 부하 절감을 위해 적당히 압축

EXERCISES = ["squat", "pushup", "lunge"]
KEY_TO_EXERCISE = {ord("1"): "squat", ord("2"): "pushup", ord("3"): "lunge"}

PANEL_WIDTH = 220


def draw_status(frame, result, fps, latency_ms):
    """좌상단 상태 패널 (posture / feedback / FPS / latency)."""
    h, w = frame.shape[:2]
    posture  = result.get("posture", "?")
    feedback = result.get("feedback", "")

    color = (0, 200, 0) if posture == "good" else (0, 100, 255)

    # 우측 패널과 겹치지 않도록 너비 조정
    right = w - PANEL_WIDTH - 20
    cv2.rectangle(frame, (10, 10), (right, 110), (30, 30, 30), -1)
    cv2.rectangle(frame, (10, 10), (right, 110), color, 2)
    cv2.putText(frame, f"POSTURE: {posture.upper()}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.putText(frame, feedback[:80],
                (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(frame, f"FPS:{fps:.1f}  LATENCY:{latency_ms:.0f}ms",
                (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)


def draw_exercise_panel(frame, sm, current_exercise):
    """우측 패널: 운동 선택 / 운동별 rep 카운트 / Top 이슈."""
    h, w = frame.shape[:2]
    x0 = w - PANEL_WIDTH - 10
    y0 = 10
    x1 = w - 10
    y1 = h - 10

    cv2.rectangle(frame, (x0, y0), (x1, y1), (30, 30, 30), -1)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (90, 90, 90), 1)

    # 섹션 1: EXERCISE 셀렉터
    cv2.putText(frame, "EXERCISE  [1/2/3]",
                (x0 + 10, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
    y = y0 + 50
    for i, ex in enumerate(EXERCISES, start=1):
        if ex == current_exercise:
            color = (0, 255, 120)
            label = f"  {i} {ex.upper():8s}*"
        else:
            color = (170, 170, 170)
            label = f"  {i} {ex}"
        cv2.putText(frame, label, (x0 + 10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        y += 22

    # 섹션 2: REPS (운동별)
    y += 12
    cv2.putText(frame, "REPS",
                (x0 + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
    y += 22
    summary = sm.get_summary()
    for ex in EXERCISES:
        st = summary["exercises"].get(ex)
        cnt = st["count"] if st else 0
        stage = st["stage"] if st else "-"
        cv2.putText(frame, f"  {ex:8s}{cnt:>3} ({stage})",
                    (x0 + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        y += 20

    # 섹션 3: TOP ISSUES (전체 합산 상위 5개)
    y += 12
    cv2.putText(frame, "TOP ISSUES",
                (x0 + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
    y += 22

    issue_totals = {}
    for ex in EXERCISES:
        st = summary["exercises"].get(ex)
        if not st:
            continue
        for k, v in st["issue_counts"].items():
            issue_totals[k] = issue_totals.get(k, 0) + v
    top = sorted(issue_totals.items(), key=lambda kv: -kv[1])[:5]
    if not top:
        cv2.putText(frame, "  (none)", (x0 + 10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 140, 140), 1)
    else:
        for full_key, cnt in top:
            short = full_key[:20]
            cv2.putText(frame, f"  {short:20s}{cnt:>3}",
                        (x0 + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 100), 1)
            y += 18


def draw_angles(frame, angles):
    """좌하단 각도 패널."""
    if not angles:
        return
    h = frame.shape[0]
    y = h - 20 - 20 * len(angles)
    for name, val in angles.items():
        cv2.putText(frame, f"{name:14s}: {val:6.1f}",
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

    print("[연결 OK] 조작: ESC=종료 / 1=squat / 2=pushup / 3=lunge")
    fps    = 0.0
    last_t = time.time()
    n_recv = 0
    n_err  = 0

    sm = ExerciseSessionManager()
    current_exercise = "squat"

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
            await ws.send(json.dumps({
                "type":     "frame",
                "image":    b64,
                "exercise": current_exercise,
            }))
            data = json.loads(await ws.recv())
            latency_ms = (time.time() - t0) * 1000

            now    = time.time()
            dt     = now - last_t
            last_t = now
            inst_fps = 1.0 / dt if dt > 0 else 0.0
            fps = (0.85 * fps + 0.15 * inst_fps) if fps else inst_fps

            if data.get("type") == "result":
                n_recv += 1
                # 서버가 echo한 exercise 사용 (요청 시점 이후 토글했을 가능성 차단)
                ex_used = data.get("exercise", current_exercise)
                sm.update(ex_used, data)
                draw_status(frame, data, fps, latency_ms)
                draw_angles(frame, data.get("angles", {}))
            else:
                n_err += 1
                cv2.putText(frame, f"ERROR: {data.get('message', '')}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 255), 2)

            # 운동 패널은 항상 그린다 (에러 프레임에서도 누적 통계 노출)
            draw_exercise_panel(frame, sm, current_exercise)

            cv2.imshow("Live Pose Analysis (ESC: quit | 1/2/3: exercise)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:                          # ESC
                break
            elif key in KEY_TO_EXERCISE:
                new_ex = KEY_TO_EXERCISE[key]
                if new_ex != current_exercise:
                    current_exercise = new_ex
                    print(f"[전환] exercise → {current_exercise}")
    finally:
        await ws.close()
        cap.release()
        cv2.destroyAllWindows()
        print(f"\n[종료] 수신 {n_recv}건 / 에러 {n_err}건")
        # 세션 요약 출력 (세트 종료 상세 피드백)
        summary = sm.get_summary()
        print("\n===== 운동 요약 =====")
        any_ex = False
        for ex in EXERCISES:
            st = summary["exercises"].get(ex)
            if not st or st["count"] == 0:
                continue
            any_ex = True
            print(f"\n[{ex}] {st['assessment']}")
            for d in st["issues_detail"]:
                print(f"  - {d['message']} ({d['count']}회)")
                if d["tip"]:
                    print(f"      → {d['tip']}")
        if not any_ex:
            print("(완료된 운동이 없습니다.)")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[중단]")
