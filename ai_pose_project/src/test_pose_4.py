import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np

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
# [공통] 관절 각도 계산 함수 (3주차에서 이어받음)
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
# [4주차 신규] 스쿼트 자세 판별 함수
# ──────────────────────────────────────────────────────────────
def judge_squat_pose(landmarks, angle_lk, angle_rk):
    """
    스쿼트 자세의 정상/비정상 여부를 판별한다.

    판별 기준:
      1) 무릎 전방 이탈 : 무릎 x좌표가 발목 x좌표보다 KNEE_FORWARD_MARGIN 이상 앞이면 비정상
      2) 상체 과도 전경 : 엉덩이-어깨 y좌표 차이가 TRUNK_LEAN_MARGIN 초과이면 비정상
      3) 좌우 무릎 각도 비대칭 : 좌우 무릎 각도 차이가 15deg 이상이면 비정상

    반환값:
      is_normal (bool)   : 전체 자세 정상 여부
      issues (list[str]) : 감지된 문제 목록
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
        issues.append("왼쪽 무릎 전방 이탈")
    if rk.x - ra.x > KNEE_FORWARD_MARGIN:
        issues.append("오른쪽 무릎 전방 이탈")

    # 2) 상체 과도 전경 검사
    avg_hip_y = (lh.y + rh.y) / 2
    avg_sho_y = (ls.y + rs.y) / 2
    if avg_hip_y - avg_sho_y > TRUNK_LEAN_MARGIN:
        issues.append("상체 과도 전경")

    # 3) 좌우 무릎 비대칭 검사
    if abs(angle_lk - angle_rk) > 15:
        issues.append(f"무릎 좌우 비대칭 ({abs(angle_lk - angle_rk):.1f}deg)")

    is_normal = (len(issues) == 0)
    return is_normal, issues


# ──────────────────────────────────────────────────────────────
# [4주차 신규] 스쿼트 횟수 카운터 클래스
# ──────────────────────────────────────────────────────────────
class SquatCounter:
    """
    무릎 각도의 상태 전이(UP -> DOWN -> UP)를 감지하여 스쿼트 횟수를 카운팅한다.

    상태 정의:
      "UP"   : 무릎 각도 > SQUAT_UP_THRESHOLD   (서 있는 상태)
      "DOWN" : 무릎 각도 < SQUAT_DOWN_THRESHOLD  (앉은 상태)
      "MID"  : 그 사이 구간 (전이 중)

    카운팅 로직:
      UP -> DOWN 전이 시 : stage = "DOWN" 기록
      DOWN -> UP 전이 시 : count += 1,  stage = "UP" 기록
    """

    def __init__(self):
        self.count = 0
        self.stage = "UP"

    def update(self, angle_lk, angle_rk):
        """
        좌우 무릎 평균 각도를 기반으로 상태를 갱신하고 카운트를 업데이트한다.
        반환값: (count, stage)
        """
        avg_knee = (angle_lk + angle_rk) / 2

        if avg_knee > SQUAT_UP_THRESHOLD:
            if self.stage == "DOWN":
                self.count += 1
                print(f"[스쿼트] {self.count}회 완료  (복귀 각도: {avg_knee:.1f}deg)")
            self.stage = "UP"

        elif avg_knee < SQUAT_DOWN_THRESHOLD:
            self.stage = "DOWN"

        return self.count, self.stage


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
    """화면 좌상단에 스쿼트 상태 패널을 오버레이로 표시한다."""
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

    # 문제점 목록 (화면 하단)
    for i, issue in enumerate(issues):
        cv2.putText(frame, f"! {issue}",
                    (10, frame.shape[0] - 20 - i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────
# 메인 루프
# ──────────────────────────────────────────────────────────────
cap     = cv2.VideoCapture(0)
counter = SquatCounter()

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
            angle_lk = calculate_angle(xy(LEFT_HIP),      xy(LEFT_KNEE),  xy(LEFT_ANKLE))
            angle_rk = calculate_angle(xy(RIGHT_HIP),     xy(RIGHT_KNEE), xy(RIGHT_ANKLE))
            angle_lh = calculate_angle(xy(LEFT_SHOULDER), xy(LEFT_HIP),   xy(LEFT_KNEE))
            angle_rh = calculate_angle(xy(RIGHT_SHOULDER),xy(RIGHT_HIP),  xy(RIGHT_KNEE))

            # 각도 화면 표시
            # draw_angle(frame, landmarks[LEFT_KNEE],  angle_lk, "L무릎")
            # draw_angle(frame, landmarks[RIGHT_KNEE], angle_rk, "R무릎")
            # draw_angle(frame, landmarks[LEFT_HIP],   angle_lh, "L엉덩이")
            # draw_angle(frame, landmarks[RIGHT_HIP],  angle_rh, "R엉덩이")
            # 카메라 한글 깨짐 현상 발생, 영어로 변경
            draw_angle(frame, landmarks[LEFT_KNEE],  angle_lk, "L_Knee")
            draw_angle(frame, landmarks[RIGHT_KNEE], angle_rk, "R_Knee")
            draw_angle(frame, landmarks[LEFT_HIP],   angle_lh, "L_Hip")
            draw_angle(frame, landmarks[RIGHT_HIP],  angle_rh, "R_Hip")

            # [4주차] 스쿼트 횟수 카운팅
            count, stage = counter.update(angle_lk, angle_rk)

            # [4주차] 스쿼트 자세 판별 (하강 단계에서만 검사)
            is_normal, issues = True, []
            if stage == "DOWN":
                is_normal, issues = judge_squat_pose(landmarks, angle_lk, angle_rk)

            # 상태 패널 표시
            draw_status_panel(frame, count, stage, is_normal, issues)

            # 터미널 출력
            print(
                f"[4주차] "
                f"L무릎={angle_lk:6.1f}deg  R무릎={angle_rk:6.1f}deg  "
                f"stage={stage:<4}  count={count}  "
                f"normal={is_normal}  issues={issues}"
            )

        cv2.imshow("Pose - Squat Judge", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

cap.release()
cv2.destroyAllWindows()