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
# 관절 각도 계산 함수
# 세 관절 좌표(A, B, C)를 받아 B를 꼭짓점으로 하는 각도를 반환한다.
# NumPy의 arccos를 이용하여 벡터 사이각을 계산한다.
# ──────────────────────────────────────────────────────────────
def calculate_angle(a, b, c):
    """
    a, b, c : (x, y) 튜플
    b를 꼭짓점으로 하는 각도(도, degree)를 반환한다.
    """
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)

    ba = a - b   # b → a 벡터
    bc = c - b   # b → c 벡터

    # 내적 / (||ba|| * ||bc||) = cos(θ)
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    cosine = np.clip(cosine, -1.0, 1.0)   # arccos 정의역 범위 보정
    angle  = np.degrees(np.arccos(cosine))
    return round(angle, 1)


# ──────────────────────────────────────────────────────────────
# 화면에 각도 텍스트를 표시하는 헬퍼 함수
# ──────────────────────────────────────────────────────────────
def draw_angle(frame, landmark, angle, label):
    h, w = frame.shape[:2]
    x = int(landmark.x * w)
    y = int(landmark.y * h)
    cv2.putText(frame, f"{label}:{angle}", (x + 5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)


cap = cv2.VideoCapture(0)

with PoseLandmarker.create_from_options(options) as landmarker:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
        result = landmarker.detect_for_video(mp_image, timestamp_ms)

        if result.pose_landmarks:
            landmarks = result.pose_landmarks[0]

            # ── 관절 점 표시 ──────────────────────────────────
            for lm in landmarks:
                x = int(lm.x * frame.shape[1])
                y = int(lm.y * frame.shape[0])
                cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)

            # ── 좌표 추출 (x, y 튜플) ─────────────────────────
            def xy(idx):
                lm = landmarks[idx]
                return (lm.x, lm.y)

            # ── 각도 계산 (6개 관절) ──────────────────────────
            # 왼쪽 팔꿈치 : 어깨 - 팔꿈치 - 손목
            angle_le = calculate_angle(xy(LEFT_SHOULDER),  xy(LEFT_ELBOW),  xy(LEFT_WRIST))
            # 오른쪽 팔꿈치 : 어깨 - 팔꿈치 - 손목
            angle_re = calculate_angle(xy(RIGHT_SHOULDER), xy(RIGHT_ELBOW), xy(RIGHT_WRIST))
            # 왼쪽 무릎 : 엉덩이 - 무릎 - 발목
            angle_lk = calculate_angle(xy(LEFT_HIP),  xy(LEFT_KNEE),  xy(LEFT_ANKLE))
            # 오른쪽 무릎 : 엉덩이 - 무릎 - 발목
            angle_rk = calculate_angle(xy(RIGHT_HIP), xy(RIGHT_KNEE), xy(RIGHT_ANKLE))
            # 왼쪽 어깨 : 팔꿈치 - 어깨 - 엉덩이
            angle_ls = calculate_angle(xy(LEFT_ELBOW),  xy(LEFT_SHOULDER),  xy(LEFT_HIP))
            # 오른쪽 어깨 : 팔꿈치 - 어깨 - 엉덩이
            angle_rs = calculate_angle(xy(RIGHT_ELBOW), xy(RIGHT_SHOULDER), xy(RIGHT_HIP))

            # ── 화면에 각도 표시 ──────────────────────────────
            # 한글은 ???로 나와서 영어로 수정
            # draw_angle(frame, landmarks[LEFT_ELBOW],    angle_le, "L팔꿈치")
            # draw_angle(frame, landmarks[RIGHT_ELBOW],   angle_re, "R팔꿈치")
            # draw_angle(frame, landmarks[LEFT_KNEE],     angle_lk, "L무릎")
            # draw_angle(frame, landmarks[RIGHT_KNEE],    angle_rk, "R무릎")
            # draw_angle(frame, landmarks[LEFT_SHOULDER], angle_ls, "L어깨")
            # draw_angle(frame, landmarks[RIGHT_SHOULDER],angle_rs, "R어깨")

            draw_angle(frame, landmarks[LEFT_ELBOW],    angle_le, "L_Elbow")
            draw_angle(frame, landmarks[RIGHT_ELBOW],   angle_re, "R_Elbow")
            draw_angle(frame, landmarks[LEFT_KNEE],     angle_lk, "L_Knee")
            draw_angle(frame, landmarks[RIGHT_KNEE],    angle_rk, "R_Knee")
            draw_angle(frame, landmarks[LEFT_SHOULDER], angle_ls, "L_Shoulder")
            draw_angle(frame, landmarks[RIGHT_SHOULDER],angle_rs, "R_Shoulder")

            # ── 터미널 출력 ───────────────────────────────────
            print(
                f"[각도] "
                f"L팔꿈치={angle_le:6.1f}° "
                f"R팔꿈치={angle_re:6.1f}° "
                f"L무릎={angle_lk:6.1f}° "
                f"R무릎={angle_rk:6.1f}° "
                f"L어깨={angle_ls:6.1f}° "
                f"R어깨={angle_rs:6.1f}°"
            )

        cv2.imshow("Pose – Angle Calculation", frame)
        if cv2.waitKey(1) & 0xFF == 27:   # ESC 종료
            break

cap.release()
cv2.destroyAllWindows()