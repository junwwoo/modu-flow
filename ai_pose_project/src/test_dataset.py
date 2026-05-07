"""
test_dataset.py — manifest.csv 기반 일괄 검증 스크립트 (11주차)

사용법:
    python src/test_dataset.py                  # 전체 검증
    python src/test_dataset.py --exercise squat # 특정 운동만
    python src/test_dataset.py --verbose        # 통과 케이스도 상세 출력
    python src/test_dataset.py --fail-only      # 실패만 출력 (기본)

평가 항목:
    1. posture (good/bad/not_detected) 일치 여부
    2. expected_issue_key가 비었으면 통과, 있으면 feedback에 해당 메시지 포함 여부
    3. _generic은 person_not_detected 메시지 일치

출력:
    - 라벨별 통과/실패 카운트
    - 운동별 정확도
    - 실패 케이스의 actual vs expected 비교
    - 종료 코드: 실패 0건이면 0, 1건 이상이면 1
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

import cv2

# Windows 콘솔 한글 출력
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# test_pose_8.py가 모듈 로드 시점에 모델을 로드하므로 여기서만 import
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_pose_8 import analyze_pose, EXERCISE_REGISTRY, UnsupportedExerciseError  # noqa: E402
from feedback_messages import MESSAGES as MSG  # noqa: E402


PROJECT_ROOT = os.path.dirname(HERE)
TEST_IMAGES_DIR = os.path.join(PROJECT_ROOT, "test_images")
MANIFEST_PATH = os.path.join(TEST_IMAGES_DIR, "manifest.csv")


def read_manifest():
    """manifest.csv를 dict 리스트로 반환."""
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"manifest.csv 없음: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluate_row(row):
    """단일 행을 평가. (passed: bool, actual: dict, reason: str) 반환."""
    rel = row["file_path"]
    abs_path = os.path.join(TEST_IMAGES_DIR, rel)
    if not os.path.exists(abs_path):
        return False, {}, f"파일 없음: {abs_path}"

    img = cv2.imread(abs_path)
    if img is None:
        return False, {}, "cv2.imread 실패 (손상 파일?)"

    exercise = (row["exercise"] or "").strip()
    if exercise == "":
        # _generic: 어떤 운동으로 돌리든 person_not_detected 가 나와야 함
        exercise = "squat"

    try:
        actual = analyze_pose(img, exercise)
    except UnsupportedExerciseError as e:
        return False, {}, f"미지원 운동: {e.exercise}"
    except Exception as e:
        return False, {}, f"분석 예외: {type(e).__name__}: {e}"

    # 1) posture 일치
    expected_posture = row["expected_posture"]
    if expected_posture and actual["posture"] != expected_posture:
        return False, actual, f"posture 불일치: expected={expected_posture}, actual={actual['posture']}"

    # 2) _generic은 not_detected 메시지여야 함
    if row["label"] == "not_detected":
        if actual["feedback"] != MSG["person_not_detected"]:
            return False, actual, f"not_detected 메시지 아님: feedback={actual['feedback']!r}"
        return True, actual, "ok"

    # 3) expected_issue_key 가 있으면 해당 메시지가 feedback에 포함되어야 함
    expected_issue = (row["expected_issue_key"] or "").strip()
    if expected_issue:
        expected_msg = MSG.get(expected_issue)
        if expected_msg is None:
            return False, actual, f"manifest의 issue key가 MSG에 없음: {expected_issue}"
        if expected_msg not in actual["feedback"]:
            return (
                False,
                actual,
                f"expected_issue '{expected_issue}' 미발생: feedback={actual['feedback']!r}",
            )

    return True, actual, "ok"


def main():
    parser = argparse.ArgumentParser(description="manifest 기반 데이터셋 검증")
    parser.add_argument("--exercise", help="특정 운동만 검증 (squat/pushup/...)")
    parser.add_argument("--verbose", action="store_true", help="통과 케이스도 출력")
    parser.add_argument("--member", help="특정 멤버(m1/m2/...)만 검증")
    args = parser.parse_args()

    manifest = read_manifest()

    # 필터
    if args.exercise:
        manifest = [r for r in manifest if r["exercise"] == args.exercise]
    if args.member:
        manifest = [r for r in manifest if r["member"] == args.member]

    if not manifest:
        print("검증할 행이 없습니다.")
        return 0

    print(f"=== 데이터셋 검증 시작: {len(manifest)}개 ===\n")

    # 라벨별 통과/실패 카운트
    label_counts = defaultdict(lambda: {"pass": 0, "fail": 0})
    exercise_counts = defaultdict(lambda: {"pass": 0, "fail": 0})
    failures = []

    for row in manifest:
        passed, actual, reason = evaluate_row(row)
        key = (row["exercise"] or "_generic", row["label"])
        bucket = "pass" if passed else "fail"
        label_counts[key][bucket] += 1
        exercise_counts[row["exercise"] or "_generic"][bucket] += 1

        if not passed:
            failures.append((row, actual, reason))
            print(f"[FAIL] {row['file_path']}")
            print(f"       사유: {reason}")
            if actual:
                print(f"       actual.posture = {actual.get('posture')}")
                print(f"       actual.feedback = {actual.get('feedback')!r}")
                print(f"       actual.angles = {actual.get('angles')}")
        elif args.verbose:
            print(f"[PASS] {row['file_path']}")

    # 라벨별 요약
    print("\n=== 라벨별 결과 ===")
    print(f"{'운동':<10} {'라벨':<22} {'PASS':>6} {'FAIL':>6} {'정확도':>8}")
    for (ex, lbl), c in sorted(label_counts.items()):
        total = c["pass"] + c["fail"]
        acc = c["pass"] / total * 100 if total else 0
        print(f"{ex:<10} {lbl:<22} {c['pass']:>6} {c['fail']:>6} {acc:>7.1f}%")

    # 운동별 요약
    print("\n=== 운동별 결과 ===")
    print(f"{'운동':<10} {'PASS':>6} {'FAIL':>6} {'정확도':>8}")
    for ex, c in sorted(exercise_counts.items()):
        total = c["pass"] + c["fail"]
        acc = c["pass"] / total * 100 if total else 0
        print(f"{ex:<10} {c['pass']:>6} {c['fail']:>6} {acc:>7.1f}%")

    # 전체 요약
    total = len(manifest)
    n_fail = len(failures)
    n_pass = total - n_fail
    print(f"\n=== 전체: {n_pass}/{total} PASS ({n_pass / total * 100:.1f}%) ===")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
