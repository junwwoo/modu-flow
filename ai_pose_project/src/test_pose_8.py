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
from collections import deque
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
# 스쿼트 폼 검사 임계값 (stage 임계값은 SquatAnalyzer 클래스 속성으로 이전)
# ──────────────────────────────────────────────────────────────
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
# 횟수 카운터 (외부 호출자가 누적 상태 관리에 사용)
# 11주차: 운동별 분석기에서 임계값/key를 끌어다 쓰는 일반화 구조로 전환.
# 12주차: 프레임 단위 각도 노이즈에 대한 시간적 안정화(중앙값 스무딩 + 전환 디바운스) 추가.
# ──────────────────────────────────────────────────────────────
class RepCounter:
    """운동 무관 횟수 카운터 + 시간적 안정화.

    프레임 1장씩 독립 분석한 각도는 출렁이므로:
      (1) 최근 `smooth_window`개 프레임의 **중앙값**으로 각도를 스무딩 (단발 스파이크 제거),
      (2) 스무딩된 각도가 임계값 너머 zone 을 가리키는 상태가 `debounce_frames`만큼
          연속될 때만 stage 를 전환 (짧은 글리치 무시).
    `(down_thr, up_thr)` 구간은 그대로 데드밴드(히스테리시스)로 동작하며,
    그 안에서는 직전 stage 를 유지한다. DOWN → UP 전이 시 count 1 증가.

    Args:
        up_thr:   스무딩 각도 > up_thr   → UP zone
        down_thr: 스무딩 각도 < down_thr → DOWN zone
        primary_angle_keys: 평균을 계산할 angles dict의 키 목록 (예: ["left_knee", "right_knee"])
        smooth_window:   중앙값 스무딩 윈도 크기(프레임). 1이면 스무딩 없음.
        debounce_frames: stage 전환을 확정하기 위해 필요한 연속 프레임 수.
    """
    def __init__(self, up_thr: float, down_thr: float,
                 primary_angle_keys: list[str],
                 smooth_window: int = 5, debounce_frames: int = 2):
        self.up_thr  = up_thr
        self.down_thr = down_thr
        self.keys = list(primary_angle_keys)
        self.smooth_window   = max(1, smooth_window)
        self.debounce_frames = max(1, debounce_frames)
        self.count = 0
        self.stage = "UP"
        self._angle_buf: deque = deque(maxlen=self.smooth_window)
        self._pending_zone = None   # 전환 대기 중인 zone ("UP"/"DOWN") 또는 None
        self._pending_n    = 0      # 그 zone 이 연속된 프레임 수

    def update(self, angles: dict) -> tuple[int, str]:
        vals = [angles[k] for k in self.keys if k in angles]
        if not vals:
            # 관절 미검출 프레임 — 스무딩 버퍼/디바운스 상태를 깨지 않고 현 상태 유지
            return self.count, self.stage

        self._angle_buf.append(sum(vals) / len(vals))
        ordered = sorted(self._angle_buf)
        smoothed = ordered[len(ordered) // 2]   # 중앙값 (윈도가 짧을 땐 자동으로 가벼운 스무딩)

        if smoothed > self.up_thr:
            zone = "UP"
        elif smoothed < self.down_thr:
            zone = "DOWN"
        else:
            zone = None   # 데드밴드 — 직전 stage 유지

        if zone is None or zone == self.stage:
            self._pending_zone = None
            self._pending_n    = 0
            return self.count, self.stage

        # 현재 stage 와 다른 zone 후보 — 연속 프레임 누적
        if zone == self._pending_zone:
            self._pending_n += 1
        else:
            self._pending_zone = zone
            self._pending_n    = 1

        if self._pending_n >= self.debounce_frames:
            if zone == "UP" and self.stage == "DOWN":
                self.count += 1
            self.stage = zone
            self._pending_zone = None
            self._pending_n    = 0

        return self.count, self.stage


def make_rep_counter(exercise: str) -> RepCounter:
    """EXERCISE_REGISTRY의 분석기에서 임계값을 끌어와 RepCounter 생성."""
    if exercise not in EXERCISE_REGISTRY:
        raise UnsupportedExerciseError(exercise)
    a = EXERCISE_REGISTRY[exercise]
    return RepCounter(a.up_thr, a.down_thr, a.primary_angle_keys)


class SquatCounter:
    """8주차 호환 카운터 — 내부적으로 RepCounter("squat") 사용.

    기존 호출 코드(`SquatCounter().update(angle_lk, angle_rk)`)와의
    호환을 위해 시그니처만 보존하고 로직은 RepCounter에 위임한다.
    """
    def __init__(self):
        a = SquatAnalyzer
        self._inner = RepCounter(a.up_thr, a.down_thr, a.primary_angle_keys)

    @property
    def count(self) -> int:
        return self._inner.count

    @property
    def stage(self) -> str:
        return self._inner.stage

    def update(self, angle_lk, angle_rk):
        return self._inner.update({
            "left_knee":  angle_lk,
            "right_knee": angle_rk,
        })


# ──────────────────────────────────────────────────────────────
# 피드백 관리자
# 11주차: 모든 내부 키를 운동 prefix 포함 full key (`<exercise>.<issue>`)로 통일.
# 한국어 문구는 `feedback_messages.MESSAGES`에서 직접 조회.
# ──────────────────────────────────────────────────────────────
class FeedbackManager:
    """rep 단위 피드백 누적 관리.

    내부 저장(active_feedbacks / current_rep_issues / session_stats)의 키는
    모두 `<exercise>.<issue>` 형태의 full key로 통일되어, 다중 운동 세션에서도
    이슈 통계가 운동별로 분리된다.
    """
    def __init__(self):
        self.active_feedbacks: dict[str, tuple[str, float]] = {}  # full_key → (msg, expire_at)
        self.current_rep_issues: set[str] = set()                  # full_keys
        self.session_stats: dict[str, int] = {}                    # full_key → 누적 발생 횟수
        self.rep_summary = ""
        self.rep_summary_expire = 0.0

    def update(self, issues, exercise: str):
        """이슈 리스트를 받아 통계·활성 피드백 갱신.

        Args:
            issues:   이슈 키 리스트. 두 형식 모두 지원:
                      - `["left_knee_forward", ...]` (analyze_pose 의 "issues" 그대로)
                      - `[{"key": "left_knee_forward", "label": ...}, ...]` (legacy)
            exercise: 운동명. full_key prefix로 prepend 됨.
        """
        now = time.time()
        for issue in issues:
            key = issue["key"] if isinstance(issue, dict) else issue
            if not key:
                continue
            full_key = f"{exercise}.{key}"
            self.current_rep_issues.add(full_key)
            self.session_stats[full_key] = self.session_stats.get(full_key, 0) + 1
            msg = MSG.get(full_key, "")
            if msg:
                self.active_feedbacks[full_key] = (msg, now + FEEDBACK_DISPLAY_SEC)

        expired = [k for k, (_, t) in self.active_feedbacks.items() if now > t]
        for k in expired:
            del self.active_feedbacks[k]

    def on_rep_complete(self, rep_count):
        if self.current_rep_issues:
            labels = [MSG[k] for k in self.current_rep_issues if k in MSG]
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
        for full_key, cnt in self.session_stats.items():
            label = MSG.get(full_key, full_key)
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
    """운동별 분석기 인터페이스 (stateless 권장).

    구현체는 입력 landmarks(MediaPipe pose_landmarks[0])로부터
    각도·자세·피드백·이슈 키를 계산하여 dict로 반환한다.
    rep 카운팅·이슈 누적 등 stateful 처리는 외부 호출자(`ExerciseSessionManager`)가 담당한다.

    반환 dict schema:
        - "posture":  "good" | "bad"
        - "feedback": 사용자에게 표시할 한국어 메시지 (이슈 메시지 결합)
        - "angles":   {각도 키 → 값 (도 단위)}
        - "issues":   list[str] — exercise prefix 없는 이슈 키 (예: ["hip_sag"])

    11주차: stage 판정 임계값과 카운터용 key를 클래스 속성으로 노출하여
    `RepCounter`/`make_rep_counter`가 단일 출처를 참조하도록 한다.
    """
    name: str
    up_thr: float
    down_thr: float
    primary_angle_keys: list[str]
    def analyze(self, landmarks) -> dict: ...


class SquatAnalyzer:
    """스쿼트 분석기 (기존 judge_squat_pose 로직 캡슐화)."""
    name = "squat"

    # stage 판정 + RepCounter 공용 임계값
    up_thr             = 160
    down_thr           = 120
    primary_angle_keys = ["left_knee", "right_knee"]

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
        if avg_knee < self.down_thr:
            stage = "DOWN"
        elif avg_knee > self.up_thr:
            stage = "UP"
        else:
            stage = "MID"

        is_normal, issue_dicts = True, []
        if stage == "DOWN":
            is_normal, issue_dicts = judge_squat_pose(landmarks, angle_lk, angle_rk)

        issue_keys = [i["key"] for i in issue_dicts]
        posture = "good" if is_normal else "bad"

        if issue_dicts:
            msgs = [MSG.get(f"squat.{i['key']}", i["label"]) for i in issue_dicts]
            feedback_msg = " | ".join(msgs)
        elif stage == "DOWN":
            feedback_msg = MSG["squat.good_form"]
        else:
            feedback_msg = MSG["squat.standby"]

        return {
            "posture":  posture,
            "feedback": feedback_msg,
            "angles":   angles,
            "issues":   issue_keys,
        }


# ──────────────────────────────────────────────────────────────
# 푸시업 폼 검사 임계값 (10주차, 5장 표본 1차 튜닝)
# stage 임계값(up/down)은 PushupAnalyzer 클래스 속성으로 이전 (11주차)
# ──────────────────────────────────────────────────────────────
PUSHUP_HIP_DEVIATION_MARGIN = 0.035  # 어깨-발목 중간 Y 대비 엉덩이 Y 편차 임계
PUSHUP_ELBOW_FLARE_RATIO    = 0.5    # 어깨 폭 대비 어깨-팔꿈치 X 거리 비율 (정면일 때만 사용)
PUSHUP_CAMERA_FRONTAL_RATIO = 0.4    # 어깨 X 거리 / 어깨-엉덩이 Y 거리 임계


class PushupAnalyzer:
    """푸시업 분석기 (10주차 신규).

    측면 촬영을 가정하며, 정면이 의심되면 `pushup.camera_angle` 이슈로 안내.
    """
    name = "pushup"

    # stage 판정 + RepCounter 공용 임계값
    up_thr             = 160
    down_thr           = 100
    primary_angle_keys = ["left_elbow", "right_elbow"]

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
        if avg_elbow < self.down_thr:
            stage = "DOWN"
        elif avg_elbow > self.up_thr:
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
            "issues":   issues,
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
# 런지 분석기 (11주차 신규)
# ──────────────────────────────────────────────────────────────
LUNGE_FRONT_LEG_Z_MARGIN  = 0.05  # |Δz| 이하면 Y로 폴백
LUNGE_FRONT_LEG_Y_MARGIN  = 0.05  # |Δy(knee)| 이하면 히스테리시스로 폴백
LUNGE_KNEE_FORWARD_MARGIN = 0.05  # 앞다리 무릎 X가 발목보다 전방 (squat과 동일 규약)
LUNGE_TRUNK_LEAN_MARGIN   = 0.10  # 어깨-엉덩이 Y 차이 임계


class LungeAnalyzer:
    """런지 분석기.

    앞다리 식별 휴리스틱 (Z → Y → 히스테리시스):
      1) **Z (깊이)** — 측면 촬영에서 카메라에 더 가까운 발목(Z 작음)이 앞다리.
         |Δz| > Z_MARGIN 이면 Z 단독으로 결정.
      2) **Y (높이) 폴백** — Z가 ambiguous할 때 무릎 Y 비교. 뒷다리 무릎은
         바닥쪽으로 내려가므로 Y가 크다 → 앞다리는 무릎 Y가 더 작은 쪽.
      3) **히스테리시스** — Z, Y 모두 ambiguous하면 이전 프레임 결정 유지.
         첫 프레임에서 모두 ambiguous면 식별 불가(`unknown_front_leg`).

    주의: 다른 분석기와 달리 앞다리 식별 결과를 인스턴스 상태로 보존한다.
    `EXERCISE_REGISTRY`의 단일 인스턴스 공유는 단일 세션을 가정한다.
    멀티 클라이언트(WebSocket 다중 연결) 환경에서는 클라이언트별 인스턴스를
    생성하거나 매 세션 시작 시 `reset()`을 호출해야 한다.
    """
    name = "lunge"

    # stage 판정 + RepCounter 공용 임계값 (squat과 동일 — 양 무릎 평균 기반)
    up_thr             = 160
    down_thr           = 120
    primary_angle_keys = ["left_knee", "right_knee"]

    def __init__(self):
        self._prev_front: str | None = None  # "left" | "right" | None

    def reset(self) -> None:
        """앞다리 식별 히스테리시스 상태 초기화."""
        self._prev_front = None

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
        if avg_knee < self.down_thr:
            stage = "DOWN"
        elif avg_knee > self.up_thr:
            stage = "UP"
        else:
            stage = "MID"

        front_leg = self._identify_front_leg(landmarks)

        issues: list[str] = []
        if stage == "DOWN":
            if front_leg is None:
                issues.append("unknown_front_leg")
            else:
                issues.extend(self._check_form(landmarks, front_leg))

        posture = "good" if not issues else "bad"

        if issues:
            msgs = [MSG.get(f"lunge.{k}", k) for k in issues]
            feedback_msg = " | ".join(msgs)
        elif stage == "DOWN":
            feedback_msg = MSG["lunge.good_form"]
        else:
            feedback_msg = MSG["lunge.standby"]

        return {
            "posture":  posture,
            "feedback": feedback_msg,
            "angles":   angles,
            "issues":   issues,
        }

    def _identify_front_leg(self, landmarks) -> str | None:
        """앞다리 ('left' / 'right') 식별. 모두 ambiguous하면 None."""
        la = landmarks[LEFT_ANKLE];  ra = landmarks[RIGHT_ANKLE]
        # 1) Z: 더 작은(카메라 가까운) 쪽이 앞다리
        z_diff = la.z - ra.z
        if abs(z_diff) > LUNGE_FRONT_LEG_Z_MARGIN:
            front = "left" if z_diff < 0 else "right"
            self._prev_front = front
            return front

        # 2) Y 폴백: 무릎 Y가 더 작은(이미지 위쪽) 쪽이 앞다리
        lk = landmarks[LEFT_KNEE];  rk = landmarks[RIGHT_KNEE]
        y_diff = lk.y - rk.y
        if abs(y_diff) > LUNGE_FRONT_LEG_Y_MARGIN:
            front = "left" if y_diff < 0 else "right"
            self._prev_front = front
            return front

        # 3) 히스테리시스: 이전 결정 유지 (첫 프레임이면 None)
        return self._prev_front

    def _check_form(self, landmarks, front_leg: str) -> list[str]:
        if front_leg == "left":
            knee, ankle = landmarks[LEFT_KNEE], landmarks[LEFT_ANKLE]
        else:
            knee, ankle = landmarks[RIGHT_KNEE], landmarks[RIGHT_ANKLE]

        issues: list[str] = []

        # 앞다리 무릎이 발목보다 X 전방 (squat의 knee_forward와 동일 규약)
        if knee.x - ankle.x > LUNGE_KNEE_FORWARD_MARGIN:
            issues.append("front_knee_forward")

        # 상체 기울임 (어깨가 엉덩이보다 충분히 위에 있지 않음)
        ls = landmarks[LEFT_SHOULDER];  rs = landmarks[RIGHT_SHOULDER]
        lh = landmarks[LEFT_HIP];       rh = landmarks[RIGHT_HIP]
        avg_sho_y = (ls.y + rs.y) / 2
        avg_hip_y = (lh.y + rh.y) / 2
        if avg_hip_y - avg_sho_y > LUNGE_TRUNK_LEAN_MARGIN:
            issues.append("trunk_lean")

        return issues


# ──────────────────────────────────────────────────────────────
# 운동 레지스트리 (분석기 dispatch)
# ──────────────────────────────────────────────────────────────
EXERCISE_REGISTRY: dict[str, ExerciseAnalyzer] = {
    "squat":  SquatAnalyzer(),
    "pushup": PushupAnalyzer(),
    "lunge":  LungeAnalyzer(),
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
            "issues":   [],
            "exercise": exercise,
        }

    landmarks = result.pose_landmarks[0]
    out = EXERCISE_REGISTRY[exercise].analyze(landmarks)
    out["exercise"] = exercise
    return out
