import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np
import time
import json
import os
import queue
import threading
from datetime import datetime

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("[경고] requests 모듈이 설치되어 있지 않습니다. (pip install requests)")
    print("       서버 전송 없이 로컬 모드로 실행됩니다.")

model_path = "pose_landmarker_lite.task"

BaseOptions = python.BaseOptions
PoseLandmarker = vision.PoseLandmarker
PoseLandmarkerOptions = vision.PoseLandmarkerOptions
VisionRunningMode = vision.RunningMode

options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.VIDEO,
)

# 주요 관절 인덱스
LEFT_SHOULDER  = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW     = 13
RIGHT_ELBOW    = 14
LEFT_WRIST     = 15
RIGHT_WRIST    = 16
LEFT_HIP       = 23
RIGHT_HIP      = 24
LEFT_KNEE      = 25
RIGHT_KNEE     = 26
LEFT_ANKLE     = 27
RIGHT_ANKLE    = 28

# 주요 관절 이름 매핑
JOINT_NAMES = {
    LEFT_SHOULDER:  "left_shoulder",
    RIGHT_SHOULDER: "right_shoulder",
    LEFT_ELBOW:     "left_elbow",
    RIGHT_ELBOW:    "right_elbow",
    LEFT_WRIST:     "left_wrist",
    RIGHT_WRIST:    "right_wrist",
    LEFT_HIP:       "left_hip",
    RIGHT_HIP:      "right_hip",
    LEFT_KNEE:      "left_knee",
    RIGHT_KNEE:     "right_knee",
    LEFT_ANKLE:     "left_ankle",
    RIGHT_ANKLE:    "right_ankle",
}

# ──────────────────────────────────────────────────────────────
# 스쿼트 판별 임계값
# ──────────────────────────────────────────────────────────────
SQUAT_DOWN_THRESHOLD = 120
SQUAT_UP_THRESHOLD   = 160

KNEE_FORWARD_MARGIN  = 0.05
TRUNK_LEAN_MARGIN    = 0.10

# ──────────────────────────────────────────────────────────────
# 피드백 설정
# ──────────────────────────────────────────────────────────────
FEEDBACK_DISPLAY_SEC = 3.0

# ──────────────────────────────────────────────────────────────
# [7주차 신규] 백엔드 API 설정
# ──────────────────────────────────────────────────────────────
API_BASE_URL   = os.environ.get("MODUFLOW_API_URL", "http://localhost:8080")
API_USER_ID    = os.environ.get("MODUFLOW_USER_ID", "demo-user")
API_BATCH_SIZE = 30        # 30프레임마다 일괄 전송
API_TIMEOUT    = 2.0       # HTTP 요청 타임아웃 (초)


# ──────────────────────────────────────────────────────────────
# [공통] 관절 각도 계산 함수
# ──────────────────────────────────────────────────────────────
def calculate_angle(a, b, c):
    """세 관절 좌표(a, b, c)를 받아 꼭짓점 b의 각도(degree)를 반환한다."""
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)
    ba = a - b
    bc = c - b
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    cosine = np.clip(cosine, -1.0, 1.0)
    return round(np.degrees(np.arccos(cosine)), 1)


# ──────────────────────────────────────────────────────────────
# 피드백 메시지 매핑
# ──────────────────────────────────────────────────────────────
FEEDBACK_MESSAGES = {
    "left_knee_forward":  "Tip: Push LEFT knee back, align over ankle",
    "right_knee_forward": "Tip: Push RIGHT knee back, align over ankle",
    "trunk_lean":         "Tip: Lift your chest, keep torso upright",
    "knee_asymmetry":     "Tip: Balance both knees evenly",
}


# ──────────────────────────────────────────────────────────────
# 스쿼트 자세 판별 함수
# ──────────────────────────────────────────────────────────────
def judge_squat_pose(landmarks, angle_lk, angle_rk):
    issues = []

    lk = landmarks[LEFT_KNEE]
    rk = landmarks[RIGHT_KNEE]
    la = landmarks[LEFT_ANKLE]
    ra = landmarks[RIGHT_ANKLE]
    lh = landmarks[LEFT_HIP]
    rh = landmarks[RIGHT_HIP]
    ls = landmarks[LEFT_SHOULDER]
    rs = landmarks[RIGHT_SHOULDER]

    if lk.x - la.x > KNEE_FORWARD_MARGIN:
        issues.append({"key": "left_knee_forward", "label": "L Knee Forward"})
    if rk.x - ra.x > KNEE_FORWARD_MARGIN:
        issues.append({"key": "right_knee_forward", "label": "R Knee Forward"})

    avg_hip_y = (lh.y + rh.y) / 2
    avg_sho_y = (ls.y + rs.y) / 2
    if avg_hip_y - avg_sho_y > TRUNK_LEAN_MARGIN:
        issues.append({"key": "trunk_lean", "label": "Trunk Lean"})

    diff = abs(angle_lk - angle_rk)
    if diff > 15:
        issues.append({"key": "knee_asymmetry", "label": f"Knee Asymmetry ({diff:.1f}deg)"})

    is_normal = (len(issues) == 0)
    return is_normal, issues


# ──────────────────────────────────────────────────────────────
# 스쿼트 횟수 카운터 클래스
# ──────────────────────────────────────────────────────────────
class SquatCounter:
    def __init__(self):
        self.count = 0
        self.stage = "UP"

    def update(self, angle_lk, angle_rk):
        avg_knee = (angle_lk + angle_rk) / 2

        if avg_knee > SQUAT_UP_THRESHOLD:
            if self.stage == "DOWN":
                self.count += 1
                print(f"[Squat] {self.count} reps  (return angle: {avg_knee:.1f}deg)")
            self.stage = "UP"
        elif avg_knee < SQUAT_DOWN_THRESHOLD:
            self.stage = "DOWN"

        return self.count, self.stage


# ──────────────────────────────────────────────────────────────
# 피드백 관리자 클래스
# ──────────────────────────────────────────────────────────────
class FeedbackManager:
    def __init__(self):
        self.active_feedbacks = {}
        self.current_rep_issues = set()
        self.session_stats = {}
        self.rep_summary = ""
        self.rep_summary_expire = 0.0

    def update(self, issues, stage):
        now = time.time()
        for issue in issues:
            key = issue["key"]
            self.current_rep_issues.add(key)
            self.session_stats[key] = self.session_stats.get(key, 0) + 1
            msg = FEEDBACK_MESSAGES.get(key, "")
            if msg:
                self.active_feedbacks[key] = (msg, now + FEEDBACK_DISPLAY_SEC)

        expired = [k for k, (_, t) in self.active_feedbacks.items() if now > t]
        for k in expired:
            del self.active_feedbacks[k]

    def on_rep_complete(self, rep_count):
        if self.current_rep_issues:
            labels = [FEEDBACK_MESSAGES[k].replace("Tip: ", "")
                      for k in self.current_rep_issues if k in FEEDBACK_MESSAGES]
            self.rep_summary = f"Rep {rep_count}: {', '.join(labels)}"
        else:
            self.rep_summary = f"Rep {rep_count}: Good form!"
        self.rep_summary_expire = time.time() + FEEDBACK_DISPLAY_SEC
        self.current_rep_issues.clear()

    def get_active_messages(self):
        now = time.time()
        return [msg for msg, t in self.active_feedbacks.values() if now <= t]

    def get_rep_summary(self):
        if time.time() <= self.rep_summary_expire:
            return self.rep_summary
        return ""

    def get_session_summary(self):
        if not self.session_stats:
            return "No issues detected"
        parts = []
        for key, cnt in self.session_stats.items():
            label = key.replace("_", " ").title()
            parts.append(f"{label}: {cnt}")
        return " | ".join(parts)


# ──────────────────────────────────────────────────────────────
# 프레임 데이터 구조
# ──────────────────────────────────────────────────────────────
class FrameData:
    def __init__(self, frame_number, timestamp_ms, landmarks, angles, squat_state):
        self.frame_number = frame_number
        self.timestamp_ms = timestamp_ms
        self.joints = self._extract_joints(landmarks)
        self.angles = angles
        self.squat_state = squat_state

    def _extract_joints(self, landmarks):
        joints = {}
        for idx, name in JOINT_NAMES.items():
            lm = landmarks[idx]
            joints[name] = {
                "x": round(lm.x, 5),
                "y": round(lm.y, 5),
                "z": round(lm.z, 5),
                "visibility": round(lm.visibility, 4),
            }
        return joints

    def to_dict(self):
        return {
            "frame_number": self.frame_number,
            "timestamp_ms": self.timestamp_ms,
            "joints": self.joints,
            "angles": self.angles,
            "squat_state": self.squat_state,
        }


# ──────────────────────────────────────────────────────────────
# 세션 데이터 관리자
# ──────────────────────────────────────────────────────────────
class SessionDataManager:
    def __init__(self):
        self.start_time = datetime.now()
        self.frames = []
        self.rep_records = []
        self._rep_start_frame = 0

    def add_frame(self, frame_data):
        self.frames.append(frame_data)

    def on_rep_complete(self, rep_count, issues, frame_number):
        record = {
            "rep": rep_count,
            "start_frame": self._rep_start_frame,
            "end_frame": frame_number,
            "issues": list(issues),
        }
        self.rep_records.append(record)
        self._rep_start_frame = frame_number + 1
        return record

    def get_session_info(self):
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "total_frames": len(self.frames),
            "total_reps": len(self.rep_records),
        }

    def get_frame_count(self):
        return len(self.frames)

    def export_json(self, output_dir="data"):
        os.makedirs(output_dir, exist_ok=True)
        filename = f"session_{self.start_time.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(output_dir, filename)

        data = {
            "session_info": self.get_session_info(),
            "rep_records": self.rep_records,
            "frames": [f.to_dict() for f in self.frames],
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[7주차] 세션 데이터 저장 완료: {filepath}")
        print(f"        총 {len(self.frames)} 프레임, {len(self.rep_records)} reps 기록")
        return filepath


# ──────────────────────────────────────────────────────────────
# [7주차 신규] Spring 백엔드 API 클라이언트
# ──────────────────────────────────────────────────────────────
class PoseAPIClient:
    """
    Spring 백엔드 API와 통신하는 클라이언트.

    엔드포인트 가정 (Spring 서버 측에서 구현):
      POST /api/sessions/start              -> { sessionId }
      POST /api/sessions/{id}/frames        (배치 프레임 데이터)
      POST /api/sessions/{id}/reps          (rep 완료 정보)
      POST /api/sessions/{id}/end           (세션 종료 요약)

    설계 포인트:
      - 백그라운드 워커 스레드 + 큐로 비동기 전송
        → 실시간 포즈 처리 루프가 네트워크 I/O로 블로킹되지 않음
      - 서버 미기동 / 네트워크 장애 시에도 메인 동작은 정상 진행
        → 로컬 JSON 저장은 항상 보장
      - 프레임 데이터는 BATCH_SIZE 단위로 묶어서 전송 (네트워크 부하 절감)
    """

    def __init__(self, base_url=API_BASE_URL, user_id=API_USER_ID,
                 batch_size=API_BATCH_SIZE, timeout=API_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.batch_size = batch_size
        self.timeout = timeout

        self.session_id = None
        self.connected = False
        self.last_error = ""
        self.stats = {"sent": 0, "failed": 0}

        self._frame_buffer = []
        self._send_queue = queue.Queue()
        self._worker = None
        self._running = False
        self._enabled = HAS_REQUESTS

    # ── 공개 API ──────────────────────────────────────────────
    def start_session(self):
        """세션 시작을 백엔드에 알리고, sessionId 발급 시도."""
        if not self._enabled:
            self.session_id = self._fallback_session_id()
            self.last_error = "requests 모듈 없음"
            print(f"[API] 비활성화 모드: {self.session_id}")
            return

        payload = {
            "userId": self.user_id,
            "startedAt": datetime.now().isoformat(),
            "exerciseType": "squat",
        }
        try:
            r = requests.post(
                f"{self.base_url}/api/sessions/start",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            body = r.json() if r.content else {}
            self.session_id = body.get("sessionId") or body.get("session_id") \
                              or self._fallback_session_id()
            self.connected = True
            print(f"[API] 세션 시작 OK: sessionId={self.session_id}")
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            self.session_id = self._fallback_session_id()
            print(f"[API] 서버 연결 실패 → 로컬 폴백 모드: {e}")

        self._start_worker()

    def add_frame(self, frame_data):
        """프레임을 버퍼에 추가, 임계값 도달 시 큐로 플러시."""
        self._frame_buffer.append(frame_data.to_dict())
        if len(self._frame_buffer) >= self.batch_size:
            self.flush_frames()

    def flush_frames(self):
        """현재 버퍼를 비우고 전송 큐로 넘긴다."""
        if not self._frame_buffer:
            return
        batch = self._frame_buffer
        self._frame_buffer = []
        self._send_queue.put(("frames", {"frames": batch}))

    def send_rep(self, rep_record):
        """rep(1회 스쿼트) 완료 즉시 전송."""
        self._send_queue.put(("rep", rep_record))

    def end_session(self, summary):
        """세션 종료 알림 + 워커 종료."""
        self.flush_frames()
        self._send_queue.put(("end", summary))
        self._running = False
        if self._worker is not None:
            self._worker.join(timeout=5.0)
        print(f"[API] 종료 - 전송 성공 {self.stats['sent']} / 실패 {self.stats['failed']}")

    def get_status(self):
        return {
            "enabled":   self._enabled,
            "connected": self.connected,
            "session":   self.session_id,
            "sent":      self.stats["sent"],
            "failed":    self.stats["failed"],
            "queued":    self._send_queue.qsize(),
        }

    # ── 내부 구현 ─────────────────────────────────────────────
    def _fallback_session_id(self):
        return f"local-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _start_worker(self):
        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="PoseAPIWorker",
            daemon=True,
        )
        self._worker.start()

    def _worker_loop(self):
        while self._running or not self._send_queue.empty():
            try:
                kind, data = self._send_queue.get(timeout=0.3)
            except queue.Empty:
                continue

            path = self._path_for(kind)
            ok = self._post(path, data)
            if ok:
                self.stats["sent"] += 1
            else:
                self.stats["failed"] += 1

    def _path_for(self, kind):
        sid = self.session_id
        if kind == "frames":
            return f"/api/sessions/{sid}/frames"
        if kind == "rep":
            return f"/api/sessions/{sid}/reps"
        if kind == "end":
            return f"/api/sessions/{sid}/end"
        return f"/api/sessions/{sid}/unknown"

    def _post(self, path, payload):
        if not self._enabled or not self.connected:
            return False
        url = f"{self.base_url}{path}"
        try:
            r = requests.post(url, json=payload, timeout=self.timeout)
            r.raise_for_status()
            return True
        except Exception as e:
            self.last_error = str(e)
            # 서버가 도중에 끊겨도 다음 요청은 다시 시도하도록 connected 유지
            return False


# ──────────────────────────────────────────────────────────────
# 화면 표시 헬퍼
# ──────────────────────────────────────────────────────────────
def draw_angle(frame, landmark, angle, label):
    h, w = frame.shape[:2]
    x = int(landmark.x * w)
    y = int(landmark.y * h)
    cv2.putText(frame, f"{label}:{angle}",
                (x + 5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)


def draw_status_panel(frame, count, stage, is_normal, issues):
    panel_color = (0, 180, 0) if is_normal else (0, 0, 200)
    cv2.rectangle(frame, (10, 10), (360, 130), (30, 30, 30), -1)
    cv2.rectangle(frame, (10, 10), (360, 130), panel_color, 2)

    cv2.putText(frame, f"SQUAT COUNT : {count}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    stage_text = "[ DOWN ]" if stage == "DOWN" else "[ UP ]  "
    cv2.putText(frame, f"STAGE : {stage_text}",
                (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

    pose_text  = "POSE : GOOD"  if is_normal else "POSE : CHECK"
    pose_color = (0, 255, 0)   if is_normal else (0, 100, 255)
    cv2.putText(frame, pose_text,
                (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, pose_color, 2)

    for i, issue in enumerate(issues):
        label = issue["label"] if isinstance(issue, dict) else str(issue)
        cv2.putText(frame, f"! {label}",
                    (10, frame.shape[0] - 20 - i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 1, cv2.LINE_AA)


def draw_feedback_panel(frame, feedback_msgs, rep_summary):
    h, w = frame.shape[:2]
    if not feedback_msgs and not rep_summary:
        return

    panel_x = w - 420
    panel_y = 10
    panel_h = 30 + len(feedback_msgs) * 30 + (35 if rep_summary else 0)
    cv2.rectangle(frame, (panel_x, panel_y), (w - 10, panel_y + panel_h),
                  (40, 40, 40), -1)
    cv2.rectangle(frame, (panel_x, panel_y), (w - 10, panel_y + panel_h),
                  (0, 200, 255), 2)

    cv2.putText(frame, "FEEDBACK",
                (panel_x + 10, panel_y + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

    for i, msg in enumerate(feedback_msgs):
        y_pos = panel_y + 50 + i * 30
        cv2.putText(frame, msg,
                    (panel_x + 10, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    if rep_summary:
        y_pos = panel_y + 50 + len(feedback_msgs) * 30
        color = (0, 255, 150) if "Good" in rep_summary else (100, 180, 255)
        cv2.putText(frame, rep_summary,
                    (panel_x + 10, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def draw_session_stats(frame, stats_text):
    h, w = frame.shape[:2]
    cv2.putText(frame, f"Session: {stats_text}",
                (10, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)


def draw_data_panel(frame, frame_count, rep_count):
    h, w = frame.shape[:2]
    panel_y = h - 70
    cv2.rectangle(frame, (10, panel_y), (280, h - 15), (30, 30, 30), -1)
    cv2.rectangle(frame, (10, panel_y), (280, h - 15), (200, 200, 0), 1)

    cv2.putText(frame, f"[DATA] Frames: {frame_count}",
                (20, panel_y + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 0), 1, cv2.LINE_AA)
    cv2.putText(frame, f"[DATA] Reps recorded: {rep_count}",
                (20, panel_y + 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 0), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────
# [7주차 신규] API 통신 상태 패널
# ──────────────────────────────────────────────────────────────
def draw_api_panel(frame, status):
    """화면 우하단에 API 연결/전송 상태를 표시한다."""
    h, w = frame.shape[:2]
    panel_x = w - 280
    panel_y = h - 90
    panel_color = (0, 200, 0) if status["connected"] else (0, 100, 200)

    cv2.rectangle(frame, (panel_x, panel_y), (w - 10, h - 15), (30, 30, 30), -1)
    cv2.rectangle(frame, (panel_x, panel_y), (w - 10, h - 15), panel_color, 2)

    state_text = "ONLINE" if status["connected"] else "OFFLINE"
    cv2.putText(frame, f"[API] {state_text}",
                (panel_x + 10, panel_y + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, panel_color, 2, cv2.LINE_AA)

    sid_short = (status["session"] or "-")[-12:]
    cv2.putText(frame, f"sid: {sid_short}",
                (panel_x + 10, panel_y + 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

    cv2.putText(frame,
                f"sent:{status['sent']}  fail:{status['failed']}  q:{status['queued']}",
                (panel_x + 10, panel_y + 64),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────
# 메인 루프
# ──────────────────────────────────────────────────────────────
cap      = cv2.VideoCapture(0)
counter  = SquatCounter()
feedback = FeedbackManager()
session  = SessionDataManager()
api      = PoseAPIClient()                    # [7주차] API 클라이언트

# [7주차] 세션 시작을 백엔드에 알림
api.start_session()

prev_count   = 0
frame_number = 0

with PoseLandmarker.create_from_options(options) as landmarker:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image     = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
        result       = landmarker.detect_for_video(mp_image, timestamp_ms)

        if result.pose_landmarks:
            landmarks = result.pose_landmarks[0]

            # 관절 점 표시
            for lm in landmarks:
                px = int(lm.x * frame.shape[1])
                py = int(lm.y * frame.shape[0])
                cv2.circle(frame, (px, py), 4, (0, 255, 0), -1)

            def xy(idx):
                lm = landmarks[idx]
                return (lm.x, lm.y)

            # 주요 관절 각도 계산
            angle_lk = calculate_angle(xy(LEFT_HIP),       xy(LEFT_KNEE),  xy(LEFT_ANKLE))
            angle_rk = calculate_angle(xy(RIGHT_HIP),      xy(RIGHT_KNEE), xy(RIGHT_ANKLE))
            angle_lh = calculate_angle(xy(LEFT_SHOULDER),  xy(LEFT_HIP),   xy(LEFT_KNEE))
            angle_rh = calculate_angle(xy(RIGHT_SHOULDER), xy(RIGHT_HIP),  xy(RIGHT_KNEE))

            # 각도 화면 표시
            draw_angle(frame, landmarks[LEFT_KNEE],  angle_lk, "L_Knee")
            draw_angle(frame, landmarks[RIGHT_KNEE], angle_rk, "R_Knee")
            draw_angle(frame, landmarks[LEFT_HIP],   angle_lh, "L_Hip")
            draw_angle(frame, landmarks[RIGHT_HIP],  angle_rh, "R_Hip")

            # 스쿼트 횟수 카운팅
            count, stage = counter.update(angle_lk, angle_rk)

            # 스쿼트 자세 판별
            is_normal, issues = True, []
            if stage == "DOWN":
                is_normal, issues = judge_squat_pose(landmarks, angle_lk, angle_rk)

            # 피드백 갱신
            feedback.update(issues, stage)

            # rep 완료 감지 → 피드백 요약 + 데이터 기록 + API 전송
            if count > prev_count:
                feedback.on_rep_complete(count)
                rep_record = session.on_rep_complete(
                    count,
                    feedback.current_rep_issues | set(i["key"] for i in issues),
                    frame_number,
                )
                # [7주차] rep 완료 즉시 백엔드로 전송
                api.send_rep(rep_record)
                prev_count = count

            # 프레임 데이터 수집
            angles_dict = {
                "left_knee":  angle_lk,
                "right_knee": angle_rk,
                "left_hip":   angle_lh,
                "right_hip":  angle_rh,
            }
            squat_state = {
                "stage":     stage,
                "count":     count,
                "is_normal": is_normal,
                "issues":    [i["key"] for i in issues],
            }
            frame_data = FrameData(
                frame_number=frame_number,
                timestamp_ms=timestamp_ms,
                landmarks=landmarks,
                angles=angles_dict,
                squat_state=squat_state,
            )
            session.add_frame(frame_data)

            # [7주차] API 클라이언트에도 프레임 누적 (배치 자동 전송)
            api.add_frame(frame_data)

            # 상태 / 피드백 / 세션통계 / 데이터 / API 패널 표시
            draw_status_panel(frame, count, stage, is_normal, issues)
            feedback_msgs = feedback.get_active_messages()
            rep_summary   = feedback.get_rep_summary()
            draw_feedback_panel(frame, feedback_msgs, rep_summary)
            draw_session_stats(frame, feedback.get_session_summary())
            draw_data_panel(frame, session.get_frame_count(), len(session.rep_records))
            draw_api_panel(frame, api.get_status())

            # 터미널 출력
            api_status = api.get_status()
            print(
                f"[7주차] frame={frame_number:>5}  "
                f"L_Knee={angle_lk:6.1f}  R_Knee={angle_rk:6.1f}  "
                f"stage={stage:<4}  count={count}  "
                f"api[{('ON' if api_status['connected'] else 'OFF')}]"
                f" sent={api_status['sent']} q={api_status['queued']}"
            )

        frame_number += 1
        cv2.imshow("Pose - Spring API Integration", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

# ──────────────────────────────────────────────────────────────
# [7주차] 세션 종료 처리
# ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  SESSION SUMMARY")
print("=" * 60)
print(f"  Total Reps   : {counter.count}")
print(f"  Total Frames : {session.get_frame_count()}")
print(f"  Stats        : {feedback.get_session_summary()}")
print("=" * 60)

# 로컬 JSON 저장 (백엔드 장애와 무관하게 항상 보장)
saved_path = None
if session.get_frame_count() > 0:
    saved_path = session.export_json()
    print(f"\n  >> 데이터 파일: {saved_path}")
else:
    print("\n  >> 수집된 프레임이 없어 파일을 저장하지 않았습니다.")

# [7주차] 백엔드에 세션 종료 알림 + 요약 전송
end_summary = {
    "sessionInfo":  session.get_session_info(),
    "totalReps":    counter.count,
    "totalFrames":  session.get_frame_count(),
    "issueStats":   feedback.session_stats,
    "localFile":    saved_path,
}
api.end_session(end_summary)

api_status = api.get_status()
print("=" * 60)
print(f"  API 전송 결과: 성공 {api_status['sent']} / 실패 {api_status['failed']}")
print(f"  세션 ID      : {api_status['session']}")
print("=" * 60)

cap.release()
cv2.destroyAllWindows()
