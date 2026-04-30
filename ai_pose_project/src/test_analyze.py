"""
analyze_pose 모듈 단독 테스트.

test_images/ 디렉토리의 모든 이미지에 대해 analyze_pose()를 호출하고
반환 dict를 보기 좋게 출력한다.
"""
import json
import os
import sys

# test_pose_8 import 시점에 모델 경로(상대경로)가 로드되므로
# 반드시 src 디렉토리를 CWD로 만들고 import 해야 한다.
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

import cv2
from test_pose_8 import analyze_pose

TEST_DIR = os.path.normpath(os.path.join(HERE, "..", "test_images"))


def main():
    files = sorted(
        f for f in os.listdir(TEST_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
        and not f.startswith("_")
    )
    if not files:
        print("[ERROR] 테스트 이미지가 없습니다.")
        return

    print(f"[INFO] 테스트 디렉토리: {TEST_DIR}")
    print(f"[INFO] 대상 파일 {len(files)}개\n")

    for f in files:
        path = os.path.join(TEST_DIR, f)
        img = cv2.imread(path)
        if img is None:
            print(f"[SKIP] {f} - 읽기 실패")
            continue

        print("=" * 70)
        print(f"파일: {f}   ({img.shape[1]}x{img.shape[0]})")
        result = analyze_pose(img)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    main()
