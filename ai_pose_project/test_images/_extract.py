"""
_extract.py — 영상에서 라벨별 프레임을 자동 추출하는 도구 (13~14주차 데이터셋 구축용).

(A) 방식: **영상 한 개 = 한 라벨**로 통제 촬영했다는 전제.
  - "어느 프레임을 뽑을지"(동작의 정점/바닥 = stage 극점)는 이 도구가 자동 판단한다.
  - "good 이냐 / 어떤 fault 냐"(그라운드 트루스 라벨)는 사람이 --label 로 지정한다.
    분석기(analyze_pose)로 라벨을 붙이면 자기 자신을 검증하는 순환이 되므로 라벨은 항상 사람이 준다.

동작:
  1. 영상 전 프레임(--step 간격)에 analyze_pose 를 돌려 primary 각도 시계열을 만든다.
  2. 시계열의 극점(최소=동작 바닥 / 최대=기립·신전)을 prominence 기준으로 검출.
  3. --label 에 맞는 극점(예: squat 바닥 = 최소각) 프레임을 골라 저장.
  4. test_images/<exercise>/<label>/<member>_<view>_<seq>.jpg 로 저장 + manifest.csv 행 추가.
  5. 저장한 프레임에 대한 analyze_pose 예측(posture/issues)을 함께 출력 → 임계값 튜닝 참고용
     (예측은 *참고*일 뿐 라벨이 아니다).

사용 예:
  # 정자세 스쿼트 영상 → 바닥(good_down) 프레임 추출
  python _extract.py squat_side_good.mp4 --exercise squat --label good_down --view side --member m1

  # 같은 영상에서 기립(good_up) 프레임도
  python _extract.py squat_side_good.mp4 --exercise squat --label good_up --view side --member m1

  # 일부러 상체 숙인 스쿼트 영상 → trunk_lean 프레임
  python _extract.py squat_side_lean.mp4 --exercise squat --label trunk_lean --view side --member m1

  # 미리보기(저장 안 함): 검출된 극점과 분석기 예측만 출력
  python _extract.py squat_side_lean.mp4 --exercise squat --label trunk_lean --view side --member m1 --dry-run

  # 세로 폰 영상이 옆으로 누워 디코딩되면 회전 보정
  python _extract.py clip.mp4 --exercise pushup --label hip_sag --view side --member m2 --rotate 90
"""
import argparse
import csv
import os
import sys

import cv2
import numpy as np

HERE    = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.normpath(os.path.join(HERE, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# analyze_pose 는 import 시 모델을 로드한다 (test_pose_8 의 모듈 전역 _landmarker)
from test_pose_8 import analyze_pose, EXERCISE_REGISTRY  # noqa: E402

MANIFEST = os.path.join(HERE, "manifest.csv")
MANIFEST_COLS = ["file_path", "exercise", "label", "expected_posture",
                 "expected_issue_key", "expected_stage", "view", "member", "notes"]

# 각 운동의 "active(폼 검사가 의미있는) 포즈"가 primary 각도의 최소(low)인지 최대(high)인지.
#   squat/pushup/lunge: 바닥(굽힘) = 최소각.  lateral_raise/shoulder_press: 든 상태 = 최대각.
#   pullup/situp: 정점(굽힘/말림) = 최소각.
ACTIVE_EXTREME = {
    "squat": "low", "pushup": "low", "lunge": "low",
    "lateral_raise": "high", "shoulder_press": "high",
    "pullup": "low", "situp": "low",
}
# 폼 검사가 DOWN 단계 게이팅인 운동 (manifest expected_stage 채움용)
DOWN_GATED = {"squat", "pushup", "lunge"}


def derive_expected(exercise: str, label: str) -> dict:
    """라벨 → (expected_posture, expected_issue_key, expected_stage, pick) 추론.

    pick = "low"/"high": 어느 극점 프레임을 뽑을지. good_up 은 active 의 반대 극점.
    """
    active = ACTIVE_EXTREME.get(exercise, "low")
    opposite = "high" if active == "low" else "low"
    if label == "good_up":
        return {"posture": "good", "issue_key": "", "stage": "UP", "pick": opposite}
    if label == "good_down":
        return {"posture": "good", "issue_key": "", "stage": "DOWN", "pick": active}
    # fault 라벨
    stage = "DOWN" if exercise in DOWN_GATED else ""
    return {"posture": "bad", "issue_key": f"{exercise}.{label}", "stage": stage, "pick": active}


def rotate_frame(frame, deg: int):
    if deg == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if deg == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if deg == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def median_smooth(vals, win):
    if win <= 1:
        return list(vals)
    out = []
    half = win // 2
    for i in range(len(vals)):
        seg = vals[max(0, i - half): i + half + 1]
        out.append(float(np.median(seg)))
    return out


def find_extrema(vals, prominence):
    """교대로 나타나는 극점을 prominence 기준으로 검출. [(index, 'min'|'max'), ...]."""
    if len(vals) < 2:
        return []
    ext = []
    direction = 0            # 1=상승(최대 탐색), -1=하강(최소 탐색), 0=미정
    cand_i, cand_v = 0, vals[0]
    for i in range(1, len(vals)):
        v = vals[i]
        if direction == 1:
            if v >= cand_v:
                cand_i, cand_v = i, v
            elif cand_v - v >= prominence:
                ext.append((cand_i, "max")); direction = -1; cand_i, cand_v = i, v
        elif direction == -1:
            if v <= cand_v:
                cand_i, cand_v = i, v
            elif v - cand_v >= prominence:
                ext.append((cand_i, "min")); direction = 1; cand_i, cand_v = i, v
        else:
            if v >= cand_v + prominence:
                direction = 1;  cand_i, cand_v = i, v
            elif v <= cand_v - prominence:
                direction = -1; cand_i, cand_v = i, v
            elif v > cand_v:
                cand_i, cand_v = i, v
    return ext


def next_seq(folder: str, member: str, view: str) -> int:
    """folder 안의 <member>_<view>_NN.jpg 중 가장 큰 NN + 1."""
    if not os.path.isdir(folder):
        return 1
    prefix = f"{member}_{view}_"
    mx = 0
    for f in os.listdir(folder):
        if f.startswith(prefix) and f.lower().endswith((".jpg", ".jpeg", ".png")):
            stem = os.path.splitext(f)[0]
            try:
                mx = max(mx, int(stem[len(prefix):]))
            except ValueError:
                pass
    return mx + 1


def load_manifest_paths() -> set:
    if not os.path.isfile(MANIFEST):
        return set()
    with open(MANIFEST, newline="", encoding="utf-8") as fp:
        return {row["file_path"] for row in csv.DictReader(fp)}


def main():
    ap = argparse.ArgumentParser(description="영상 → 라벨별 프레임 자동 추출")
    ap.add_argument("video", help="입력 영상 경로")
    ap.add_argument("--exercise", required=True, choices=sorted(EXERCISE_REGISTRY.keys()))
    ap.add_argument("--label", required=True,
                    help="폴더명 = 라벨 (good_up / good_down / <issue_key suffix>, 예: trunk_lean)")
    ap.add_argument("--view", default="side", choices=["side", "front", "angle"])
    ap.add_argument("--member", default="m1", help="m1~m4 (체형 편향 분석용)")
    ap.add_argument("--max-frames", type=int, default=6, help="저장할 최대 프레임 수")
    ap.add_argument("--step", type=int, default=3, help="N 프레임마다 1장 분석(속도)")
    ap.add_argument("--prominence", type=float, default=20.0, help="극점 인정 최소 각도 변화(도)")
    ap.add_argument("--smooth", type=int, default=5, help="각도 시계열 중앙값 스무딩 윈도")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                    help="프레임 회전 보정(세로 폰 영상 대응)")
    ap.add_argument("--pick", choices=["low", "high"], default=None,
                    help="극점 방향 강제(미지정 시 라벨로 자동)")
    ap.add_argument("--notes", default="", help="manifest notes 컬럼")
    ap.add_argument("--dry-run", action="store_true", help="저장/기입 없이 검출 결과만 출력")
    ap.add_argument("--no-manifest", action="store_true", help="manifest 기입 생략")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        print(f"[ERROR] 영상을 찾을 수 없습니다: {args.video}")
        sys.exit(1)

    meta = derive_expected(args.exercise, args.label)
    pick = args.pick or meta["pick"]
    want_kind = "min" if pick == "low" else "max"
    primary_keys = EXERCISE_REGISTRY[args.exercise].primary_angle_keys

    print(f"[설정] exercise={args.exercise} label={args.label} view={args.view} member={args.member}")
    print(f"       pick={pick}({want_kind}) primary={primary_keys} "
          f"posture={meta['posture']} issue_key={meta['issue_key'] or '-'}")

    # ── 1차 패스: primary 각도 시계열 ──────────────────────────
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"[ERROR] 영상을 열 수 없습니다: {args.video}")
        sys.exit(1)

    series = []   # (frame_idx, primary_angle)
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % args.step == 0:
            if args.rotate:
                frame = rotate_frame(frame, args.rotate)
            res = analyze_pose(frame, args.exercise)
            ang = res.get("angles", {})
            vals = [ang[k] for k in primary_keys if k in ang]
            if vals:
                series.append((idx, sum(vals) / len(vals)))
        idx += 1
    cap.release()

    if not series:
        print("[ERROR] 사람/관절이 검출된 프레임이 없습니다. 회전(--rotate)·촬영 구도를 확인하세요.")
        sys.exit(1)

    idxs = [i for i, _ in series]
    raw  = [a for _, a in series]
    smooth = median_smooth(raw, args.smooth)
    ext = find_extrema(smooth, args.prominence)
    cand = [(idxs[pos], smooth[pos]) for pos, kind in ext if kind == want_kind]

    if not cand:
        # 극점 미검출(정적/짧은 영상) → 전체 최소/최대 1장 폴백
        pos = int(np.argmin(smooth) if want_kind == "min" else np.argmax(smooth))
        cand = [(idxs[pos], smooth[pos])]
        print(f"[안내] {want_kind} 극점 미검출 → 전역 {want_kind} 1장으로 폴백")

    # 영상 전체에 고르게 분포하도록 다운샘플
    if len(cand) > args.max_frames:
        sel = np.linspace(0, len(cand) - 1, args.max_frames).round().astype(int)
        cand = [cand[i] for i in sorted(set(sel))]

    print(f"[검출] 분석 {len(series)}프레임 / {want_kind} 극점 {len(cand)}개 선택 "
          f"(각도 {min(a for _,a in cand):.0f}~{max(a for _,a in cand):.0f}°)")

    if args.dry_run:
        print("[DRY-RUN] 저장하지 않습니다. 아래는 선택 프레임의 분석기 예측(참고용):")

    # ── 2차 패스: 선택 프레임만 다시 읽어 저장 ──────────────────
    out_dir = os.path.join(HERE, args.exercise, args.label)
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)
    seq = next_seq(out_dir, args.member, args.view)
    existing = load_manifest_paths()

    cap = cv2.VideoCapture(args.video)
    new_rows, saved = [], 0
    for frame_idx, angle in cand:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        if args.rotate:
            frame = rotate_frame(frame, args.rotate)
        pred = analyze_pose(frame, args.exercise)
        tag = "✓" if pred["posture"] == meta["posture"] else "✗"
        line = (f"  frame {frame_idx:>5} angle {angle:5.0f}°  → "
                f"예측 posture={pred['posture']} issues={pred.get('issues', [])} {tag}")
        if args.dry_run:
            print(line); continue

        fname = f"{args.member}_{args.view}_{seq:02d}.jpg"
        rel = f"{args.exercise}/{args.label}/{fname}".replace("\\", "/")
        cv2.imwrite(os.path.join(out_dir, fname), frame)
        new_rows.append({
            "file_path": rel, "exercise": args.exercise, "label": args.label,
            "expected_posture": meta["posture"], "expected_issue_key": meta["issue_key"],
            "expected_stage": meta["stage"], "view": args.view, "member": args.member,
            "notes": args.notes,
        })
        dup = " (manifest 중복 — 기입 생략)" if rel in existing else ""
        print(line + f"  → 저장 {rel}{dup}")
        seq += 1
        saved += 1

    cap.release()

    if args.dry_run:
        return

    # ── manifest 기입 ────────────────────────────────────────
    if not args.no_manifest and new_rows:
        rows = [r for r in new_rows if r["file_path"] not in existing]
        write_header = not os.path.isfile(MANIFEST)
        with open(MANIFEST, "a", newline="", encoding="utf-8") as fp:
            w = csv.DictWriter(fp, fieldnames=MANIFEST_COLS)
            if write_header:
                w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"[manifest] {len(rows)}행 추가 (중복 {len(new_rows) - len(rows)}건 제외)")

    print(f"[완료] {saved}장 저장 → {out_dir}")
    print(f"       검증: python src/test_dataset.py --exercise {args.exercise}")


if __name__ == "__main__":
    main()
