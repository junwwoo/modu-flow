# Test Images — 자세 분석 검증용 데이터셋

`analyze_pose()` 검증과 임계값 튜닝에 사용하는 이미지 컬렉션이다.
**폴더 = 라벨, 파일명 = 메타데이터, `manifest.csv` = 그라운드 트루스**가 원칙.

## 폴더 구조

```
test_images/
├── _generic/                # 사람 미검출 케이스 (운동 무관)
├── squat/
│   ├── good_up/             # UP stage 정상 (기립)
│   ├── good_down/           # DOWN stage 정상 (낮은 스쿼트, 이슈 없음)
│   ├── left_knee_forward/   # squat.left_knee_forward
│   ├── right_knee_forward/  # squat.right_knee_forward
│   ├── left_knee_inward/    # (예약) 무릎 안쪽 모임 — 분석기 추가 시
│   ├── right_knee_inward/   # (예약)
│   ├── trunk_lean/          # squat.trunk_lean
│   └── knee_asymmetry/      # squat.knee_asymmetry
├── pushup/
│   ├── good_up/
│   ├── good_down/
│   ├── hip_sag/             # pushup.hip_sag
│   ├── hip_pike/            # pushup.hip_pike
│   └── camera_angle/        # pushup.camera_angle (정면 촬영 부적합)
├── lunge/
│   ├── good_up/             # 기립 (UP stage)
│   ├── good_down/           # 정상 런지 (DOWN stage, 이슈 없음)
│   ├── front_knee_forward/  # lunge.front_knee_forward
│   ├── trunk_lean/          # lunge.trunk_lean
│   └── unknown_front_leg/   # lunge.unknown_front_leg (앞다리 식별 실패 — 정면 촬영/직립 모호)
└── manifest.csv
```

- 폴더명 = `EXERCISE_REGISTRY` 키 (`squat`, `pushup`, ...)
- 하위 폴더명 = 이슈 키의 suffix (예: `pushup.hip_sag` → `hip_sag/`) 또는 `good_up`/`good_down`
- 새 운동 추가 시 폴더만 만들면 `test_dataset.py`가 자동 인식

## 파일명 컨벤션

```
<member><id>_<view>_<seq>.jpg
```

| 토큰 | 값 | 예시 |
|---|---|---|
| member | `m1`~`m4` (팀원 식별자) | `m1` |
| view | `side` / `front` / `angle` | `side` |
| seq | 2자리 순번 | `01` |

예: `m1_side_01.jpg`, `m3_front_02.jpg`

→ 그레핑/필터링 쉽고, 체형 편향 분석 시 photographer별 집계 가능

## manifest.csv

폴더·파일명만으로 부족한 메타데이터를 한 곳에 모은다.
`test_dataset.py`가 이 파일을 읽어 자동 평가한다.

| 컬럼 | 설명 |
|---|---|
| `file_path` | `test_images/` 기준 상대 경로 |
| `exercise` | `EXERCISE_REGISTRY` 키, generic은 빈 값 |
| `label` | 폴더명과 동일 (중복이지만 쿼리 편의) |
| `expected_posture` | `good` / `bad` |
| `expected_issue_key` | `analyze_pose` 반환의 이슈 식별자, good은 빈 값 |
| `expected_stage` | UP/DOWN/MID, stage 무관이면 빈 값 |
| `view` | side/front/angle (정면 의도 케이스 식별용) |
| `member` | 체형 편향 분석용 |
| `notes` | 자유 메모 |

## 표본 수량 가이드

운동당 권장 분량 (4명 분담 시):
- `good_up` / `good_down`: 각 4장 (멤버당 1장)
- 이슈별: 각 4장 (멤버당 1장)
- `front` 1장 (운동당 1장이면 충분, 정면 검출 검증용)

→ 운동 1종당 약 30장 × 10종 = 약 300장. 인당 약 75장.

## 촬영 가이드

### 환경
- 단색 배경 권장 (벽, 커튼). 다른 사람·사물 노출 최소화
- 충분한 조명 (역광 회피)
- 카메라는 삼각대 또는 고정 위치. 흔들림 없을 것
- 해상도: 720p 이상, 정사각형 자르기 불필요 (서버에서 처리)

### 측면(side) 촬영 — 기본
- 카메라 높이: 운동자의 골반 ~ 가슴 사이
- 거리: 전신이 프레임에 들어가는 최소 거리 (대략 2~3m)
- **side는 운동자의 좌측 또는 우측 어느 쪽이든 무방**, 다만 한 표본 안에서는 일관되게 유지
- 운동자의 정중선이 카메라에서 보았을 때 90°가 되도록
- **런지의 앞다리 식별은 측면 촬영에서 Z(깊이)가 선결 정보** — 정면이면 Z·Y 모두 ambiguous로 빠져 `unknown_front_leg`가 트리거되므로, 식별 실패 케이스를 제외하면 반드시 측면에서 촬영한다

### 정면(front) 촬영 — `camera_angle` 검증용
- 운동자가 카메라를 정면으로 바라보는 자세 (얼굴이 카메라 향함)
- pushup의 `camera_angle` 케이스 또는 squat의 기립 자세에서 사용

### 라벨링 원칙
- **good_up**: stage가 UP일 때 자세에 이슈가 없는 정상 케이스 (기립 또는 팔꿈치 신전)
- **good_down**: stage가 DOWN일 때 자세에 이슈가 없는 정상 케이스
- **이슈 폴더**: 해당 이슈가 *명확히* 발생하도록 의도적으로 자세를 잡는다
  - 예: `hip_sag/`는 엉덩이를 일부러 떨어뜨려 어깨-발목 중간선보다 아래로
  - 임계값 근처의 애매한 케이스는 `notes`에 명시 후 manifest 업데이트
- 한 사진이 여러 이슈를 동시에 만족할 수 있음 → 가장 *주된* 이슈 폴더에 배치, 부가 이슈는 `notes`에 기재

## 새 운동 추가 시 체크리스트

1. `src/test_pose_8.py`의 `EXERCISE_REGISTRY`에 분석기 등록
2. `test_images/<exercise>/` 폴더 생성, 이슈 키별 하위 폴더 생성
3. 팀원별 촬영 분담표 공유 (good_up/good_down + 각 이슈)
4. `manifest.csv`에 행 추가
5. `python src/test_dataset.py` 실행 → 라벨별 정확도 확인

## 유틸리티

- `_generate.py` — 더미 이미지 3종 자동 생성 (이미 `_generic/`에 마이그레이션됨)
- `_capture.py` — 웹캠으로 한 프레임씩 캡처 (SPACE 저장 / ESC 종료)

## 진행 현황 (2026-05-08)

| 운동 | 라벨 | 보유 표본 | 목표 |
|---|---|---|---|
| squat | good_up | 2 | 4 |
| squat | good_down | 0 | 4 |
| squat | left_knee_forward | 1 | 4 |
| squat | right_knee_forward | 0 | 4 |
| squat | trunk_lean | 0 | 4 |
| squat | knee_asymmetry | 0 | 4 |
| pushup | good_up | 1 | 4 |
| pushup | good_down | 1 | 4 |
| pushup | hip_sag | 1 | 4 |
| pushup | hip_pike | 1 | 4 |
| pushup | camera_angle | 1 | 1 |
| lunge | good_up | 0 | 4 |
| lunge | good_down | 0 | 4 |
| lunge | front_knee_forward | 0 | 4 |
| lunge | trunk_lean | 0 | 4 |
| lunge | unknown_front_leg | 0 | 2 |
| _generic | not_detected | 3 | 3 |
