import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np
import time

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

# ──────────────────────────────────────────────────────────────
# 스쿼트 판별 임계값
# ──────────────────────────────────────────────────────────────
SQUAT_DOWN_THRESHOLD = 120   # 무릎 각도가 이 값 미만이면 "하강(DOWN)" 상태로 판정
SQUAT_UP_THRESHOLD   = 160   # 무릎 각도가 이 값 초과이면 "상승(UP)" 상태로 판정

# 스쿼트 자세 판별 기준 (올바른 자세 범위)
KNEE_FORWARD_MARGIN  = 0.05  # 무릎 x좌표가 발목 x좌표보다 이 값 이상 앞이면 비정상
TRUNK_LEAN_MARGIN    = 0.10  # 엉덩이-어깨 y좌표 차이 임계 (정규화 좌표 기준)

# ──────────────────────────────────────────────────────────────
# [5주차] 피드백 설정
# ──────────────────────────────────────────────────────────────
FEEDBACK_DISPLAY_SEC = 3.0   # 피드백 메시지 화면 유지 시간(초)


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
# [5주차 신규] 피드백 메시지 매핑
# ──────────────────────────────────────────────────────────────
# 각 문제 유형에 대한 교정 가이드 메시지
FEEDBACK_MESSAGES = {
    "left_knee_forward":  "Tip: Push LEFT knee back, align over ankle",
    "right_knee_forward": "Tip: Push RIGHT knee back, align over ankle",
    "trunk_lean":         "Tip: Lift your chest, keep torso upright",
    "knee_asymmetry":     "Tip: Balance both knees evenly",
}


# ──────────────────────────────────────────────────────────────
# [4주차] 스쿼트 자세 판별 함수 (5주차에서 issue 키 추가)
# ──────────────────────────────────────────────────────────────
def judge_squat_pose(landmarks, angle_lk, angle_rk):
    """
    스쿼트 자세의 정상/비정상 여부를 판별한다.
    반환값:
      is_normal (bool)       : 전체 자세 정상 여부
      issues (list[dict])    : 감지된 문제 목록 (key, label 포함)
    """
    issues = []

    lk = landmarks[LEFT_KNEE]
    rk = landmarks[RIGHT_KNEE]
    la = landmarks[LEFT_ANKLE]
    ra = landmarks[RIGHT_ANKLE]
    lh = landmarks[LEFT_HIP]
    rh = landmarks[RIGHT_HIP]
    ls = landmarks[LEFT_SHOULDER]
    rs = landmarks[RIGHT_SHOULDER]

    # 1) 무릎 전방 이탈 검사
    if lk.x - la.x > KNEE_FORWARD_MARGIN:
        issues.append({"key": "left_knee_forward", "label": "L Knee Forward"})
    if rk.x - ra.x > KNEE_FORWARD_MARGIN:
        issues.append({"key": "right_knee_forward", "label": "R Knee Forward"})

    # 2) 상체 과도 전경 검사
    avg_hip_y = (lh.y + rh.y) / 2
    avg_sho_y = (ls.y + rs.y) / 2
    if avg_hip_y - avg_sho_y > TRUNK_LEAN_MARGIN:
        issues.append({"key": "trunk_lean", "label": "Trunk Lean"})

    # 3) 좌우 무릎 비대칭 검사
    diff = abs(angle_lk - angle_rk)
    if diff > 15:
        issues.append({"key": "knee_asymmetry", "label": f"Knee Asymmetry ({diff:.1f}deg)"})

    is_normal = (len(issues) == 0)
    return is_normal, issues


# ──────────────────────────────────────────────────────────────
# [4주차] 스쿼트 횟수 카운터 클래스
# ──────────────────────────────────────────────────────────────
class SquatCounter:
    """UP -> DOWN -> UP 전이를 감지하여 스쿼트 횟수를 카운팅한다."""

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
# [5주차 신규] 피드백 관리자 클래스
# ──────────────────────────────────────────────────────────────
class FeedbackManager:
    """
    감지된 문제(issue)를 누적 추적하고, 실시간 교정 피드백 메시지를 관리한다.

    기능:
      - 문제가 감지되면 해당 교정 메시지를 FEEDBACK_DISPLAY_SEC 동안 화면에 유지
      - 1회 스쿼트 완료 시 해당 세트의 문제 요약(rep summary)을 생성
      - 전체 세션 통계(총 문제 발생 횟수)를 집계
    """

    def __init__(self):
        # 현재 화면에 표시 중인 피드백: {key: (message, expire_time)}
        self.active_feedbacks = {}
        # 현재 1회(rep) 동안 발생한 문제 key 집합
        self.current_rep_issues = set()
        # 전체 세션 문제 발생 횟수: {key: count}
        self.session_stats = {}
        # 마지막 rep 완료 시 요약 메시지
        self.rep_summary = ""
        self.rep_summary_expire = 0.0

    def update(self, issues, stage):
        """매 프레임 호출: 감지된 문제를 반영하여 피드백 상태를 갱신한다."""
        now = time.time()

        for issue in issues:
            key = issue["key"]
            # 현재 rep 문제 기록
            self.current_rep_issues.add(key)
            # 세션 통계 갱신
            self.session_stats[key] = self.session_stats.get(key, 0) + 1
            # 피드백 메시지 활성화 (타이머 갱신)
            msg = FEEDBACK_MESSAGES.get(key, "")
            if msg:
                self.active_feedbacks[key] = (msg, now + FEEDBACK_DISPLAY_SEC)

        # 만료된 피드백 제거
        expired = [k for k, (_, t) in self.active_feedbacks.items() if now > t]
        for k in expired:
            del self.active_feedbacks[k]

    def on_rep_complete(self, rep_count):
        """1회 스쿼트 완료 시 호출: rep 요약을 생성하고 다음 rep을 위해 초기화한다."""
        if self.current_rep_issues:
            labels = [FEEDBACK_MESSAGES[k].replace("Tip: ", "")
                      for k in self.current_rep_issues if k in FEEDBACK_MESSAGES]
            self.rep_summary = f"Rep {rep_count}: {', '.join(labels)}"
        else:
            self.rep_summary = f"Rep {rep_count}: Good form!"
        self.rep_summary_expire = time.time() + FEEDBACK_DISPLAY_SEC
        self.current_rep_issues.clear()

    def get_active_messages(self):
        """현재 표시해야 할 피드백 메시지 리스트를 반환한다."""
        now = time.time()
        return [msg for msg, t in self.active_feedbacks.values() if now <= t]

    def get_rep_summary(self):
        """rep 요약 메시지를 반환한다 (표시 시간 내이면)."""
        if time.time() <= self.rep_summary_expire:
            return self.rep_summary
        return ""

    def get_session_summary(self):
        """전체 세션 통계 문자열을 반환한다."""
        if not self.session_stats:
            return "No issues detected"
        parts = []
        for key, cnt in self.session_stats.items():
            label = key.replace("_", " ").title()
            parts.append(f"{label}: {cnt}")
        return " | ".join(parts)


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
    """화면 좌상단에 스쿼트 상태 패널을 표시한다."""
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

    # 문제점 목록 표시 (좌하단)
    for i, issue in enumerate(issues):
        label = issue["label"] if isinstance(issue, dict) else str(issue)
        cv2.putText(frame, f"! {label}",
                    (10, frame.shape[0] - 20 - i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────
# [5주차 신규] 피드백 메시지 화면 표시
# ──────────────────────────────────────────────────────────────
def draw_feedback_panel(frame, feedback_msgs, rep_summary):
    """화면 우측에 교정 피드백 메시지를 표시한다."""
    h, w = frame.shape[:2]

    if not feedback_msgs and not rep_summary:
        return

    # 피드백 패널 배경 (우상단)
    panel_x = w - 420
    panel_y = 10
    panel_h = 30 + len(feedback_msgs) * 30 + (35 if rep_summary else 0)
    cv2.rectangle(frame, (panel_x, panel_y), (w - 10, panel_y + panel_h),
                  (40, 40, 40), -1)
    cv2.rectangle(frame, (panel_x, panel_y), (w - 10, panel_y + panel_h),
                  (0, 200, 255), 2)

    # 패널 제목
    cv2.putText(frame, "FEEDBACK",
                (panel_x + 10, panel_y + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

    # 교정 메시지 표시
    for i, msg in enumerate(feedback_msgs):
        y_pos = panel_y + 50 + i * 30
        cv2.putText(frame, msg,
                    (panel_x + 10, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    # rep 요약 메시지 표시
    if rep_summary:
        y_pos = panel_y + 50 + len(feedback_msgs) * 30
        color = (0, 255, 150) if "Good" in rep_summary else (100, 180, 255)
        cv2.putText(frame, rep_summary,
                    (panel_x + 10, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def draw_session_stats(frame, stats_text):
    """화면 최하단에 세션 통계를 표시한다."""
    h, w = frame.shape[:2]
    cv2.putText(frame, f"Session: {stats_text}",
                (10, h - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────
# 메인 루프
# ──────────────────────────────────────────────────────────────
cap      = cv2.VideoCapture(0)
counter  = SquatCounter()
feedback = FeedbackManager()
prev_count = 0

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

            # 스쿼트 자세 판별 (하강 단계에서만 검사)
            is_normal, issues = True, []
            if stage == "DOWN":
                is_normal, issues = judge_squat_pose(landmarks, angle_lk, angle_rk)

            # [5주차] 피드백 갱신
            feedback.update(issues, stage)

            # [5주차] rep 완료 감지 -> 피드백 요약 생성
            if count > prev_count:
                feedback.on_rep_complete(count)
                prev_count = count

            # 상태 패널 표시
            draw_status_panel(frame, count, stage, is_normal, issues)

            # [5주차] 피드백 패널 표시
            feedback_msgs = feedback.get_active_messages()
            rep_summary   = feedback.get_rep_summary()
            draw_feedback_panel(frame, feedback_msgs, rep_summary)

            # [5주차] 세션 통계 표시
            draw_session_stats(frame, feedback.get_session_summary())

            # 터미널 출력
            print(
                f"[5주차] "
                f"L_Knee={angle_lk:6.1f}deg  R_Knee={angle_rk:6.1f}deg  "
                f"stage={stage:<4}  count={count}  "
                f"normal={is_normal}  feedback={[m for m in feedback_msgs]}"
            )

        cv2.imshow("Pose - Squat Feedback", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

# [5주차] 종료 시 세션 요약 출력
print("\n" + "=" * 60)
print("  SESSION SUMMARY")
print("=" * 60)
print(f"  Total Reps : {counter.count}")
print(f"  Stats      : {feedback.get_session_summary()}")
print("=" * 60)

cap.release()
cv2.destroyAllWindows()
