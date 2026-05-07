import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

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
LEFT_SHOULDER = 11 # 어깨
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13 # 팔꿈치
RIGHT_ELBOW = 14
LEFT_WRIST = 15 # 손목
RIGHT_WRIST = 16
LEFT_HIP = 23 # 엉덩이
RIGHT_HIP = 24
LEFT_KNEE = 25 # 무릎
RIGHT_KNEE = 26
LEFT_ANKLE = 27 # 발목
RIGHT_ANKLE = 28

cap = cv2.VideoCapture(0)

with PoseLandmarker.create_from_options(options) as landmarker:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
        result = landmarker.detect_for_video(mp_image, timestamp_ms)

        if result.pose_landmarks:
            landmarks = result.pose_landmarks[0]

            # 화면에 관절 점 표시
            for lm in landmarks:
                x = int(lm.x * frame.shape[1])
                y = int(lm.y * frame.shape[0])
                cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)

            # 주요 관절 좌표 출력
            ls = landmarks[LEFT_SHOULDER]
            rs = landmarks[RIGHT_SHOULDER]
            le = landmarks[LEFT_ELBOW]
            re = landmarks[RIGHT_ELBOW]
            lw = landmarks[LEFT_WRIST]
            rw = landmarks[RIGHT_WRIST]
            lh = landmarks[LEFT_HIP]
            rh = landmarks[RIGHT_HIP]
            lk = landmarks[LEFT_KNEE]
            rk = landmarks[RIGHT_KNEE]
            la = landmarks[LEFT_ANKLE]
            ra = landmarks[RIGHT_ANKLE]

            print(
                f"LS(왼쪽 어깨)=({ls.x:.3f}, {ls.y:.3f}) "
                f"RS(오른쪽 어깨)=({rs.x:.3f}, {rs.y:.3f}) "
                f"LE(왼쪽 팔꿈치)=({le.x:.3f}, {le.y:.3f}) "
                f"RE(오른쪽 팔꿈치)=({re.x:.3f}, {re.y:.3f}) "
                f"LW(왼쪽 손목)=({lw.x:.3f}, {lw.y:.3f}) "
                f"RW(오른쪽 손목)=({rw.x:.3f}, {rw.y:.3f}) "
                f"LH(왼쪽 엉덩이)=({lh.x:.3f}, {lh.y:.3f}) "
                f"RH(오른쪽 엉덩이)=({rh.x:.3f}, {rh.y:.3f}) "
                f"LK(왼쪽 무릎)=({lk.x:.3f}, {lk.y:.3f}) "
                f"RK(오른쪽 무릎)=({rk.x:.3f}, {rk.y:.3f})"
                f"LA(왼쪽 발목)=({la.x:.3f}, {la.y:.3f}) "
                f"RA(오른쪽 발목)=({ra.x:.3f}, {ra.y:.3f}) "
            )

        cv2.imshow("Pose Landmarker", frame)

        if cv2.waitKey(1) & 0xFF == 27:  # ESC 종료
            break

cap.release()
cv2.destroyAllWindows()
