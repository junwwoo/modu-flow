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
from typing import Protocol

import feedback_messages
from feedback_messages import MESSAGES as MSG

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ──────────────────────────────────────────────────────────────
# MediaPipe 초기화 (모듈 로드 시 1회, 함수에서 재사용)
# ──────────────────────────────────────────────────────────────
# 모듈로 import 되는 경우 호출자의 CWD에 의존하지 않도록
# __file__ 기준 절대경로로 모델을 찾는다. (모델은 src의 부모 디렉토리에 위치)
model_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "pose_landmarker_lite.task",
)

BaseOptions          = python.BaseOptions
PoseLandmarker       = vision.PoseLandmarker
PoseLandmarkerOptions = vision.PoseLandmarkerOptions
VisionRunningMode    = vision.RunningMode

# 단일 프레임 분석에 적합한 IMAGE 모드 사용
_options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.IMAGE,
)
_landmarker = PoseLandmarker.create_from_options(_options)


# ──────────────────────────────────────────────────────────────
# 주요 관절 인덱스
# ──────────────────────────────────────────────────────────────
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

FEEDBACK_DISPLAY_SEC = 3.0

# ──────────────────────────────────────────────────────────────
# 백엔드 API 설정
# ──────────────────────────────────────────────────────────────
API_BASE_URL   = os.environ.get("MODUFLOW_API_URL", "http://localhost:8080")
API_USER_ID    = os.environ.get("MODUFLOW_USER_ID", "demo-user")
API_BATCH_SIZE = 30
API_TIMEOUT    = 2.0


# ──────────────────────────────────────────────────────────────
# 관절 각도 계산
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
# 피드백 메시지 매핑 (스쿼트 누적 상태 클래스 호환용 — prefix 없는 키)
# 한국어 문구 자체는 feedback_messages.py에서 관리한다.
# ──────────────────────────────────────────────────────────────
FEEDBACK_MESSAGES = {
    "left_knee_forward":  MSG["squat.left_knee_forward"],
    "right_knee_forward": MSG["squat.right_knee_forward"],
    "trunk_lean":         MSG["squat.trunk_lean"],
    "knee_asymmetry":     MSG["squat.knee_asymmetry"],
}


# ──────────────────────────────────────────────────────────────
# 스쿼트 자세 판별
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
# 스쿼트 횟수 카운터 (외부 호출자가 누적 상태 관리에 사용)
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
            self.stage = "UP"
        elif avg_knee < SQUAT_DOWN_THRESHOLD:
            self.stage = "DOWN"

        return self.count, self.stage


# ──────────────────────────────────────────────────────────────
# 피드백 관리자
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
            labels = [FEEDBACK_MESSAGES[k]
                      for k in self.current_rep_issues if k in FEEDBACK_MESSAGES]
            self.rep_summary = f"{rep_count}회차: {', '.join(labels)}"
        else:
            self.rep_summary = f"{rep_count}회차: 좋은 자세입니다."
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
            return "감지된 문제 없음"
        parts = []
        for key, cnt in self.session_stats.items():
            label = FEEDBACK_MESSAGES.get(key, key)
            parts.append(f"{label} ({cnt}회)")
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

        return filepath


# ──────────────────────────────────────────────────────────────
# Spring 백엔드 API 클라이언트
# ──────────────────────────────────────────────────────────────
class PoseAPIClient:
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

    def start_session(self):
        if not self._enabled:
            self.session_id = self._fallback_session_id()
            self.last_error = "requests 모듈 없음"
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
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            self.session_id = self._fallback_session_id()

        self._start_worker()

    def add_frame(self, frame_data):
        self._frame_buffer.append(frame_data.to_dict())
        if len(self._frame_buffer) >= self.batch_size:
            self.flush_frames()

    def flush_frames(self):
        if not self._frame_buffer:
            return
        batch = self._frame_buffer
        self._frame_buffer = []
        self._send_queue.put(("frames", {"frames": batch}))

    def send_rep(self, rep_record):
        self._send_queue.put(("rep", rep_record))

    def end_session(self, summary):
        self.flush_frames()
        self._send_queue.put(("end", summary))
        self._running = False
        if self._worker is not None:
            self._worker.join(timeout=5.0)

    def get_status(self):
        return {
            "enabled":   self._enabled,
            "connected": self.connected,
            "session":   self.session_id,
            "sent":      self.stats["sent"],
            "failed":    self.stats["failed"],
            "queued":    self._send_queue.qsize(),
        }

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
            return False


# ──────────────────────────────────────────────────────────────
# 운동별 분석기 (10주차: Strategy + Registry)
# ──────────────────────────────────────────────────────────────
class UnsupportedExerciseError(ValueError):
    """미지원 운동명에 대한 예외."""
    def __init__(self, exercise: str):
        self.exercise = exercise
        super().__init__(f"Unsupported exercise: {exercise}")


class ExerciseAnalyzer(Protocol):
    """운동별 분석기 인터페이스 (stateless).

    구현체는 입력 landmarks(MediaPipe pose_landmarks[0])로부터
    각도·자세·피드백을 계산하여 dict로 반환한다.
    rep 카운팅·이슈 누적 등 stateful 처리는 외부 호출자가 담당한다.
    """
    name: str
    def analyze(self, landmarks) -> dict: ...


class SquatAnalyzer:
    """스쿼트 분석기 (기존 judge_squat_pose 로직 캡슐화)."""
    name = "squat"

    def analyze(self, landmarks) -> dict:
        def xy(idx):
            lm = landmarks[idx]
            return (lm.x, lm.y)

        angle_lk = calculate_angle(xy(LEFT_HIP),       xy(LEFT_KNEE),  xy(LEFT_ANKLE))
        angle_rk = calculate_angle(xy(RIGHT_HIP),      xy(RIGHT_KNEE), xy(RIGHT_ANKLE))
        angle_lh = calculate_angle(xy(LEFT_SHOULDER),  xy(LEFT_HIP),   xy(LEFT_KNEE))
        angle_rh = calculate_angle(xy(RIGHT_SHOULDER), xy(RIGHT_HIP),  xy(RIGHT_KNEE))

        angles = {
            "left_knee":  angle_lk,
            "right_knee": angle_rk,
            "left_hip":   angle_lh,
            "right_hip":  angle_rh,
        }

        avg_knee = (angle_lk + angle_rk) / 2
        if avg_knee < SQUAT_DOWN_THRESHOLD:
            stage = "DOWN"
        elif avg_knee > SQUAT_UP_THRESHOLD:
            stage = "UP"
        else:
            stage = "MID"

        is_normal, issues = True, []
        if stage == "DOWN":
            is_normal, issues = judge_squat_pose(landmarks, angle_lk, angle_rk)

        posture = "good" if is_normal else "bad"

        if issues:
            msgs = [MSG.get(f"squat.{i['key']}", i["label"]) for i in issues]
            feedback_msg = " | ".join(msgs)
        elif stage == "DOWN":
            feedback_msg = MSG["squat.good_form"]
        else:
            feedback_msg = MSG["squat.standby"]

        return {
            "posture":  posture,
            "feedback": feedback_msg,
            "angles":   angles,
        }


# ──────────────────────────────────────────────────────────────
# 푸시업 임계값 (10주차, 5장 표본 1차 튜닝)
# ──────────────────────────────────────────────────────────────
PUSHUP_DOWN_THRESHOLD       = 100
PUSHUP_UP_THRESHOLD         = 160
PUSHUP_HIP_DEVIATION_MARGIN = 0.035  # 어깨-발목 중간 Y 대비 엉덩이 Y 편차 임계
PUSHUP_ELBOW_FLARE_RATIO    = 0.5    # 어깨 폭 대비 어깨-팔꿈치 X 거리 비율 (정면일 때만 사용)
PUSHUP_CAMERA_FRONTAL_RATIO = 0.4    # 어깨 X 거리 / 어깨-엉덩이 Y 거리 임계


class PushupAnalyzer:
    """푸시업 분석기 (10주차 신규).

    측면 촬영을 가정하며, 정면이 의심되면 `pushup.camera_angle` 이슈로 안내.
    """
    name = "pushup"

    def analyze(self, landmarks) -> dict:
        def xy(idx):
            lm = landmarks[idx]
            return (lm.x, lm.y)

        angle_le = calculate_angle(xy(LEFT_SHOULDER),  xy(LEFT_ELBOW),  xy(LEFT_WRIST))
        angle_re = calculate_angle(xy(RIGHT_SHOULDER), xy(RIGHT_ELBOW), xy(RIGHT_WRIST))
        angle_ls = calculate_angle(xy(LEFT_HIP),       xy(LEFT_SHOULDER),  xy(LEFT_ELBOW))
        angle_rs = calculate_angle(xy(RIGHT_HIP),      xy(RIGHT_SHOULDER), xy(RIGHT_ELBOW))

        angles = {
            "left_elbow":     angle_le,
            "right_elbow":    angle_re,
            "left_shoulder":  angle_ls,
            "right_shoulder": angle_rs,
        }

        avg_elbow = (angle_le + angle_re) / 2
        if avg_elbow < PUSHUP_DOWN_THRESHOLD:
            stage = "DOWN"
        elif avg_elbow > PUSHUP_UP_THRESHOLD:
            stage = "UP"
        else:
            stage = "MID"

        issues = self._check_form(landmarks)
        posture = "good" if not issues else "bad"

        if issues:
            msgs = [MSG.get(f"pushup.{k}", k) for k in issues]
            feedback_msg = " | ".join(msgs)
        elif stage == "DOWN":
            feedback_msg = MSG["pushup.good_form"]
        else:
            feedback_msg = MSG["pushup.standby"]

        return {
            "posture":  posture,
            "feedback": feedback_msg,
            "angles":   angles,
        }

    def _check_form(self, landmarks):
        ls = landmarks[LEFT_SHOULDER];  rs = landmarks[RIGHT_SHOULDER]
        le = landmarks[LEFT_ELBOW];     re_ = landmarks[RIGHT_ELBOW]
        lh = landmarks[LEFT_HIP];       rh = landmarks[RIGHT_HIP]
        la = landmarks[LEFT_ANKLE];     ra = landmarks[RIGHT_ANKLE]

        avg_sho_y   = (ls.y + rs.y) / 2
        avg_hip_y   = (lh.y + rh.y) / 2
        avg_ankle_y = (la.y + ra.y) / 2
        shoulder_x_dist = abs(ls.x - rs.x)
        torso_y_dist    = abs(avg_hip_y - avg_sho_y)

        # 카메라 각도: 정면 촬영이 의심되면 다른 폼 검사는 부정확하므로 스킵하고
        # camera_angle 안내만 반환 (사용자에게 측면 재촬영을 우선 요청).
        if torso_y_dist > 1e-6:
            if shoulder_x_dist / torso_y_dist > PUSHUP_CAMERA_FRONTAL_RATIO:
                return ["camera_angle"]

        issues = []

        # 엉덩이 처짐(hip_sag) / 솟음(hip_pike): 어깨-발목 중간선 대비 편차
        line_mid_y = (avg_sho_y + avg_ankle_y) / 2
        deviation  = avg_hip_y - line_mid_y
        if deviation > PUSHUP_HIP_DEVIATION_MARGIN:
            issues.append("hip_sag")
        elif deviation < -PUSHUP_HIP_DEVIATION_MARGIN:
            issues.append("hip_pike")

        # 팔꿈치 벌어짐(elbow_flare): 측면 촬영에서는 어깨 X 폭이 너무 작아
        # 비율이 폭발하므로 의미 있는 신호가 안 됨. 정면일 때만 동작시키지만
        # 정면이면 위에서 이미 return했으므로 여기 도달하지 않음.
        return issues


# ──────────────────────────────────────────────────────────────
# 운동 레지스트리 (분석기 dispatch)
# ──────────────────────────────────────────────────────────────
EXERCISE_REGISTRY: dict[str, ExerciseAnalyzer] = {
    "squat":  SquatAnalyzer(),
    "pushup": PushupAnalyzer(),
}


# ──────────────────────────────────────────────────────────────
# [8주차 핵심 / 10주차 확장] 단일 프레임 자세 분석 함수
# ──────────────────────────────────────────────────────────────
def analyze_pose(image, exercise: str = "squat"):
    """
    BGR numpy 이미지 한 장을 입력받아 자세 분석 결과를 dict로 반환한다.

    Args:
        image (np.ndarray): OpenCV BGR 이미지 (H x W x 3)
        exercise (str): 분석할 운동 종류. `EXERCISE_REGISTRY` 키 중 하나.
                        기본값 "squat" (9주차 클라이언트 하위 호환).

    Returns:
        dict: {
            "posture":  "good" | "bad",
            "feedback": 한국어 피드백 메시지,
            "angles":   { 운동별 각도 dict },
            "exercise": 분석에 사용한 운동명
        }

    Raises:
        UnsupportedExerciseError: `exercise`가 EXERCISE_REGISTRY에 없을 때
    """
    if exercise not in EXERCISE_REGISTRY:
        raise UnsupportedExerciseError(exercise)

    rgb_frame = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    result    = _landmarker.detect(mp_image)

    if not result.pose_landmarks:
        return {
            "posture":  "bad",
            "feedback": MSG["person_not_detected"],
            "angles":   {},
            "exercise": exercise,
        }

    landmarks = result.pose_landmarks[0]
    out = EXERCISE_REGISTRY[exercise].analyze(landmarks)
    out["exercise"] = exercise
    return out
