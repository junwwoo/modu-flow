"""
웹캠으로 테스트용 이미지를 캡처하는 헬퍼 스크립트.

조작:
  - SPACE : 현재 프레임을 test_images/ 디렉토리에 저장
  - ESC   : 종료

저장 파일명: person_capture_YYYYMMDD_HHMMSS.jpg
"""
import os
from datetime import datetime

import cv2

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] 웹캠을 열 수 없습니다.")
        return

    print("[안내] SPACE: 캡처 / ESC: 종료")
    saved_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] 프레임을 읽을 수 없습니다.")
            break

        display = frame.copy()
        cv2.putText(display, "SPACE: capture  |  ESC: quit",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(display, f"saved: {saved_count}",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imshow("Capture Test Image", display)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break
        elif key == 32:  # SPACE
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"person_capture_{ts}.jpg"
            path = os.path.join(OUT_DIR, filename)
            cv2.imwrite(path, frame)
            saved_count += 1
            print(f"[저장] {path}")

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n[완료] 총 {saved_count}장 저장")


if __name__ == "__main__":
    main()
