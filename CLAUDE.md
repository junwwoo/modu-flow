# ModuFlow Project

## Overview

MediaPipe PoseLandmarker를 활용한 실시간 포즈 추정 프로젝트.
웹캠 영상에서 인체 관절을 감지하고 각도를 계산하여 시각화한다.
추후에 모바일 안드로이드 환경으로 변경하고 운동 자세 분석과
자세 피드백을 시각화하는 기능을 제공한다.

## Team

4인 팀 프로젝트로 진행 중이며, 각 팀원의 담당 영역은 다음과 같다.

- **팀원 1 (본인)** — AI 자세 인식 (MediaPipe 기반 포즈 추정 / 자세 분석 모듈 / FastAPI 서버)
- **팀원 2** — 백엔드 개발 (Spring)
- **팀원 3** — 안드로이드 앱 개발
- **팀원 4** — 웹 앱 개발 (React PWA)

본 저장소는 팀원 1이 담당하는 AI 자세 인식 파트의 코드만 포함한다.
다른 팀원들의 컴포넌트(Spring 서버, Android, React PWA)는 별도 저장소에서 관리된다.

### 통신 구조

```
                  ┌─────────────────────────┐
                  │   FastAPI (본 저장소)    │
                  │   AI 추론 전용 서버      │
                  └────────────▲────────────┘
                               │ ① 실시간 WebSocket
                               │   (프레임 → 분석 결과)
                  ┌────────────┴────────────┐
                  │        Android          │
                  │      (사용자 운동)      │
                  └────────────┬────────────┘
                               │ ② 누적 세션/결과 저장 (REST)
                               ▼
                  ┌─────────────────────────┐
                  │       Spring 서버       │ ◀──③ 조회─── React PWA
                  │   메인 백엔드 / DB      │             (기록 열람)
                  └─────────────────────────┘
```

- **① 실시간 분석**: Android ↔ FastAPI (WebSocket 직결, 저지연)
- **② 데이터 저장**: Android → Spring (운동 세션/누적 결과 영속화)
- **③ 데이터 조회**: React PWA → Spring (저장된 운동 기록 조회·시각화)

→ FastAPI는 실시간 추론만 담당하고 데이터 영속화는 Spring이 전담하는 분리 구조.

## Project Structure

```
moduflow_project/
└── ai_pose_project/
    ├── pose_landmarker_lite.task   # MediaPipe 모델 파일 (*.task → .gitignore, 저장소 미포함)
    ├── Dockerfile                  # 12주차: Cloud Run 배포용 이미지 (python:3.11-slim)
    ├── requirements.txt            # 12주차: 배포 의존성 (venv 핀 버전과 일치, uvicorn[standard])
    ├── .dockerignore               # 12주차: Docker 빌드 컨텍스트 제외 목록
    ├── .gcloudignore               # 12주차: gcloud run deploy --source 업로드 제외 목록
    ├── venv/                       # Python 가상환경
    ├── docs/                       # 10주차: 팀 공유 자료
    │   ├── api_changes_w10.md      #   변경 요약 + REST/WS 스키마 + 팀별 액션 아이템
    │   ├── openapi_w10.json        #   FastAPI 자동 생성 OpenAPI 스펙
    │   └── samples_w10.json        #   REST/WS 정상·에러 응답 7종 실측 샘플
    ├── test_images/                # 9~11주차: 테스트 데이터셋
    │   ├── _generate.py            #   더미 이미지 생성기 (blank/noise/stick)
    │   ├── _capture.py             #   웹캠 1프레임 캡처 헬퍼
    │   ├── README.md               #   11주차: 폴더 구조·파일명 컨벤션·촬영 가이드
    │   ├── manifest.csv            #   11주차: 그라운드 트루스 (file_path/exercise/label/expected_*)
    │   ├── _generic/               #   사람 미검출 케이스 (blank/noise/stick)
    │   ├── squat/                  #   라벨별 하위 폴더 (good_up/good_down/<issue_key>/...)
    │   ├── pushup/                 #   라벨별 하위 폴더 (good_up/good_down/hip_sag/hip_pike/camera_angle)
    │   └── lunge/                  #   라벨별 하위 폴더 (good_up/good_down/front_knee_forward/trunk_lean/unknown_front_leg)
    └── src/
        ├── test_pose_8.py          # 8주차 로직 함수화 + 10주차 ExerciseRegistry + 11주차 RepCounter/LungeAnalyzer
        ├── pose_server.py          # 8주차 FastAPI 서버 (REST + WebSocket) + 12주차 WS 연결단위 세션화
        ├── feedback_messages.py    # 10주차 한국어 메시지 dict + 12주차 COACHING_TIPS(종료 요약용 상세 코칭)
        ├── session_state.py        # 11주차 ExerciseSessionManager + 12주차 get_summary 상세 코칭 확장
        ├── test_analyze.py         # 9주차: analyze_pose 모듈 단독 테스트
        ├── test_client.py          # 9주차: REST + WebSocket 통합 테스트
        ├── live_client.py          # 9주차: 실시간 웹캠 → WebSocket 클라이언트
        ├── test_dataset.py         # 11주차: manifest 기반 일괄 검증 + 라벨별 정확도
        └── test/                   # 진행 과정 아카이브 (1~7주차 단계별 구현물)
            ├── test_pose.py        #   기본 랜드마크 표시
            ├── test_pose_2.py      #   주요 관절 좌표 출력
            ├── test_pose_3.py      #   관절 각도 계산 + 화면 표시
            ├── test_pose_4.py      #   스쿼트 자세 판별 + 횟수 카운팅
            ├── test_pose_5.py      #   자세 교정 피드백 메시지
            ├── test_pose_6.py      #   데이터 구조 설계 (좌표/각도 저장)
            └── test_pose_7.py      #   백엔드 API 연동 (Spring)
```

## Tech Stack

- Python
- OpenCV (`cv2`)
- MediaPipe (PoseLandmarker, Tasks API)
- NumPy
- requests (Spring 백엔드 HTTP 통신, 7주차 / REST 테스트 클라이언트, 9주차)
- FastAPI + Uvicorn (자세 분석 API 서버, 8주차)
- Pillow (base64 이미지 디코딩, 8주차)
- websockets (WebSocket 테스트 클라이언트, 9주차)

## Development

- 가상환경: `ai_pose_project/venv/`
- 모델: `pose_landmarker_lite.task` — `test_pose_8.py`에서 `__file__` 기준 절대경로로 로드하므로 어느 CWD에서 import해도 안전
- 서버 실행(로컬): `uvicorn pose_server:app --host 0.0.0.0 --port 8000 --reload` (어느 디렉토리에서든 실행 가능)
- 헬스체크: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`
- 배포 서버(GCP Cloud Run): `https://moduflow-ai-489316272296.asia-northeast3.run.app` — 자세한 내용은 아래 "12주차: GCP Cloud Run 배포" 참고

## 8주차: 자세 분석 서버 구조

웹캠 기반 단일 스크립트(`test_pose_7.py`)에서 **모듈 + 서버** 구조로 분리.
모바일 안드로이드 클라이언트가 카메라 프레임을 서버로 보내 분석 결과를 받는 구조.

### test_pose_8.py — 분석 로직 모듈화

- 웹캠/`cv2.imshow`/while 루프 등 GUI 코드 일체 제거
- MediaPipe `PoseLandmarker`를 **모듈 로드 시 1회 초기화** (`_landmarker`)하여 재사용
- `VIDEO` → `IMAGE` 모드 전환 (단일 프레임 분석에 적합, timestamp 불필요)
- 핵심 함수: **`analyze_pose(image: np.ndarray) -> dict`**
  - 입력: BGR numpy 이미지
  - 출력: `{"posture": "good"|"bad", "feedback": str, "angles": {...}}`
  - stage 판정(UP/DOWN/MID) 후 DOWN일 때만 `judge_squat_pose`로 자세 이슈 검사
- stateful 클래스(`SquatCounter`, `FeedbackManager`, `SessionDataManager`, `PoseAPIClient`)는 외부 호출자가 누적 상태 관리에 사용할 수 있도록 그대로 유지

### pose_server.py — FastAPI 서버

#### REST: `POST /analyze`
- 요청: `{"image": "<base64>"}` (data URL 접두어 자동 제거)
- base64 → PIL → RGB → BGR 변환 후 `analyze_pose` 호출
- 응답: `{"posture", "feedback", "angles"}`
- CORS 전체 허용 (`allow_origins=["*"]`) — 모바일/웹 클라이언트 모두 접근 가능
- 에러: 빈 이미지/잘못된 base64/형식 미인식 → 400, 분석 예외 → 500
- 헬스체크: `GET /`, `GET /health`

#### WebSocket: `/ws`
- 연결 유지 상태에서 프레임을 연속 처리 (실시간용)
- 클라이언트 → 서버: `{"type": "frame", "image": "<base64>"}`
- 서버 → 클라이언트:
  - 성공: `{"type": "result", "posture", "feedback", "angles"}`
  - 실패: `{"type": "error", "message": "..."}`
- `async/await` 기반, **`asyncio.to_thread`로 CPU 바운드(MediaPipe 추론) 분리**
  → 이벤트 루프 블로킹 방지, 다중 클라이언트 동시 처리 가능
- 예외 계층화:
  - 개별 프레임 에러(`ValueError`, 분석 예외) → 에러 메시지만 보내고 **루프 유지**
  - `WebSocketDisconnect` → 정상 종료 로그
  - 그 외 예기치 않은 예외 → `close(code=1011)`

## 9주차: 검증 및 실시간 클라이언트

8주차 구현물(`test_pose_8.py` + `pose_server.py`)을 4단계로 검증하고, 실시간 웹캠 스트리밍 클라이언트를 구현하였다.

### 테스트 자산 (`test_images/`)
- **`_generate.py`** — 더미 이미지 3종 자동 생성 (검은 단색 / 랜덤 노이즈 / 스틱 피규어). 모두 "Person not detected" 케이스 검증용
- **`_capture.py`** — 웹캠으로 한 프레임씩 캡처(`SPACE` 저장 / `ESC` 종료). 정상 분석 케이스용 실제 사람 사진 확보

### 검증 스크립트

#### `test_analyze.py` — 모듈 단독 테스트
- `test_images/`의 모든 이미지에 대해 `analyze_pose()` 호출 후 결과 dict를 JSON으로 출력
- import 시점에 모델이 로드되므로 `os.chdir(HERE)` 후 import 하는 패턴 사용

#### `test_client.py` — REST + WebSocket 통합 테스트
- 헬스체크 → REST 정상/에러 → WebSocket 정상/에러/연결유지 순으로 단계별 검증
- **REST와 WebSocket이 동일 이미지에 대해 100% 같은 결과를 반환함을 확인** (모듈 분리 설계의 일관성 입증)

#### `live_client.py` — 실시간 웹캠 스트리밍
- 웹캠 프레임 → JPEG 압축(quality 70) → base64 → WebSocket 송신
- 응답을 받아 화면에 `posture` / `feedback` / `angles` / `FPS` / `latency(ms)` 오버레이
- 검증 결과: **단일 WebSocket 연결로 604 프레임 처리 / 에러 0건**
- **11주차 확장**: `1`/`2`/`3` 키로 squat/pushup/lunge 즉시 전환 (재연결 없음 — 서버 stateless 설계 활용). 클라이언트가 `ExerciseSessionManager`를 직접 보유하여 운동별 rep 카운트·이슈 통계를 우측 패널에 누적 표시. 운동 전환 시 각 운동의 누적 상태는 보존되어 squat→pushup→squat 복귀 시 카운트 이어짐. 종료 시 콘솔에 운동별 최종 카운트와 top 이슈 출력.

### 9주차에 발견·수정한 이슈
- **모델 경로의 호출자 CWD 의존 문제**: `test_pose_8.py`의 `model_path`를 `__file__` 기준 절대경로로 변경하여 어느 디렉토리에서 import해도 안전하게 동작하도록 수정
- **백그라운드 서버 라이프사이클**: 테스트 시작 전 `/health`를 1초 간격으로 폴링하여 서버 준비 완료를 확인한 뒤 클라이언트 실행. 테스트 종료 후 `task_id` 기반 명시적 종료

### 통합 테스트 실행 패턴

```bash
# 1) 서버 백그라운드 실행
"$VENV/python.exe" -m uvicorn pose_server:app --host 127.0.0.1 --port 8000 &

# 2) 헬스체크 폴링
for i in $(seq 1 30); do
  curl -s http://127.0.0.1:8000/health > /dev/null 2>&1 && break
  sleep 1
done

# 3) 테스트 실행
"$VENV/python.exe" src/test_client.py    # REST + WS 통합 테스트
"$VENV/python.exe" src/live_client.py    # 실시간 웹캠 스트리밍 (GUI)
```

## 10주차: 다중 운동 지원 + 한국어 메시지

스쿼트 단일 운동 → **Strategy + Registry** 구조로 확장. Push-up 분석기를 신규 추가하고 피드백 메시지를 한국어로 전환하였다. 9주차 클라이언트와 100% 하위 호환(`exercise` 옵셔널, 미지정 시 squat).

### 아키텍처: ExerciseAnalyzer + EXERCISE_REGISTRY

- `ExerciseAnalyzer`(typing.Protocol) — 운동별 분석기 인터페이스. **stateless** (rep 카운팅·이슈 누적은 외부 호출자 담당, 추후 `ExerciseSessionManager`로 분리 예정)
- `EXERCISE_REGISTRY: dict[str, ExerciseAnalyzer]` — `"squat"` → `SquatAnalyzer`, `"pushup"` → `PushupAnalyzer`
- `analyze_pose(image, exercise: str = "squat")` — 시그니처 확장. 미지원 운동명은 `UnsupportedExerciseError` (ValueError 서브클래스)

기존 `judge_squat_pose`/stage 판정 로직은 `SquatAnalyzer.analyze`로 이주. 행위 동일성 유지 — 9주차 회귀 시 angles 수치가 100% 동일함을 확인.

### Push-up 폼 검사 (PushupAnalyzer)

- **각도**: `left_elbow`/`right_elbow` (어깨-팔꿈치-손목), `left_shoulder`/`right_shoulder` (엉덩이-어깨-팔꿈치)
- **stage**: avg_elbow > 160 (UP) / < 100 (DOWN) / 그 외 (MID)
- **이슈 키**:
  - `pushup.hip_sag` / `pushup.hip_pike`: 어깨-발목 중간 Y 대비 엉덩이 Y 편차가 ±0.035 초과
  - `pushup.camera_angle`: 어깨 X 폭 / 어깨-엉덩이 Y 거리 비율이 0.4 초과 (정면 촬영 의심)
- **정면 감지 시 다른 폼 검사 스킵** — 정면은 hip 검사가 부정확하므로 `camera_angle` 안내만 우선 (사용자에게 측면 재촬영 요청)
- `pushup.elbow_flare`는 측면에서 어깨 X 폭이 너무 작아 비율이 폭발 → 사실상 비활성

### 프로토콜 확장

#### REST `POST /analyze`
- 요청: `{"image": "<base64>", "exercise": "squat"|"pushup"}` (`exercise` 옵셔널, 기본 `"squat"`)
- 응답: `{"posture", "feedback", "angles", "exercise"}`
- 미지원 운동명 → 400 `{"detail": "지원하지 않는 운동입니다."}`
- MediaPipe 추론 예외 → 500 `{"detail": "자세 분석에 실패했습니다. 잠시 후 다시 시도해주세요."}`

#### WebSocket `/ws`
- 프레임 메시지에 `exercise` 추가. **같은 연결 안에서 프레임마다 다른 값 전송 가능** (서버 stateless, 운동 전환 시 재연결 불필요)
- 응답에 `exercise` 에코
- 미지원 운동명 → `{"type": "error", "message": "지원하지 않는 운동입니다."}` + 연결 유지

### 한국어 메시지 외부화 (`feedback_messages.py`)

- 메시지 dict를 별도 모듈로 분리 → `MESSAGES["squat.left_knee_forward"]` 등
- 키는 영문 prefix(`<exercise>.<issue>`) 유지로 로깅·통계 호환
- 본문만 한국어로 1:1 치환. 향후 다국어 필요 시 `MESSAGES_KO`/`MESSAGES_EN` 두 dict로 확장하기 쉬운 구조
- `test_pose_8.py`의 기존 `FEEDBACK_MESSAGES`(prefix 없는 키)는 `MSG["squat.*"]`을 참조하는 호환 dict로 유지 (FeedbackManager 등 stateful 클래스 호환용)

### Push-up 1차 튜닝 (5장 표본)

| 라벨 | 결과 |
|---|---|
| 정상 UP / 정상 DOWN | good (false positive 0건) |
| 엉덩이 처짐 | hip_sag |
| 엉덩이 솟음 | hip_pike |
| 정면 촬영 | camera_angle만 |

발견·수정한 문제:
- **측면에서 elbow_flare 폭발** (어깨 X 폭 0.008~0.027) → 정면 감지 시 다른 검사 스킵 + elbow_flare 사실상 제거
- **DOWN 임계값 90°가 너무 낮음** (실제 정상 DOWN 95.8°) → `PUSHUP_DOWN_THRESHOLD: 90 → 100`
- **hip 임계값 0.05가 너무 큼** (의도된 처짐 자세 +0.042 누락) → `PUSHUP_HIP_DEVIATION_MARGIN: 0.05 → 0.035`

### 팀 공유 자료 (`ai_pose_project/docs/`)

- `api_changes_w10.md` — 변경 요약 + REST/WS 스키마 + 운동별 응답 예시 + 메시지 키 카탈로그 + 팀별 액션 아이템(Spring/Android/PWA)
- `openapi_w10.json` — FastAPI 자동 생성 OpenAPI 3.x 스펙 (Swagger UI 임포트 가능)
- `samples_w10.json` — REST/WS 정상·에러 응답 7종 실측 샘플 (요청·응답 짝)

## 11주차: 데이터셋 라벨링 체계 + 자동 검증 파이프라인

10주차까지 평탄한 파일 나열이던 `test_images/`를 **운동별/라벨별 폴더 구조 + manifest 기반 그라운드 트루스**로 재편하였다. 새 운동 추가 시 폴더와 manifest 행만 추가하면 검증 스크립트가 자동 인식하는 구조.

### 폴더 구조 원칙

**폴더 = 라벨, 파일명 = 메타데이터, `manifest.csv` = 그라운드 트루스**

```
test_images/
├── _generic/                # 사람 미검출 케이스 (운동 무관)
├── squat/                   # 폴더명 = EXERCISE_REGISTRY 키
│   ├── good_up/             # UP stage 정상 (기립)
│   ├── good_down/           # DOWN stage 정상
│   ├── left_knee_forward/   # 하위 폴더명 = 이슈 키 suffix (squat.left_knee_forward)
│   ├── right_knee_forward/
│   ├── trunk_lean/
│   └── knee_asymmetry/
├── pushup/
│   ├── good_up/ good_down/
│   ├── hip_sag/ hip_pike/
│   └── camera_angle/
└── manifest.csv
```

- 파일명 컨벤션: `<member><id>_<view>_<seq>.jpg` (예: `m1_side_01.jpg`, `m3_front_02.jpg`)
- 4인 팀이 분담 촬영 → `member` 토큰으로 체형 편향 분석 가능
- `view` ∈ {`side`, `front`, `angle`}: `pushup.camera_angle` 등 정면 의도 케이스 식별용

### manifest.csv 스키마

| 컬럼 | 설명 |
|---|---|
| `file_path` | `test_images/` 기준 상대 경로 |
| `exercise` | `EXERCISE_REGISTRY` 키, generic은 빈 값 |
| `label` | 폴더명과 동일 (쿼리 편의용 중복) |
| `expected_posture` | `good` / `bad` |
| `expected_issue_key` | `analyze_pose` 반환의 이슈 식별자(예: `squat.left_knee_forward`), good은 빈 값 |
| `expected_stage` | UP/DOWN/MID, stage 무관이면 빈 값 |
| `view` | side/front/angle |
| `member` | m1~m4 (체형 편향 분석용) |
| `notes` | 자유 메모 |

### test_dataset.py — 자동 검증 스크립트

```bash
python src/test_dataset.py                  # 전체 검증
python src/test_dataset.py --exercise squat # 특정 운동만
python src/test_dataset.py --member m1      # 특정 멤버만
python src/test_dataset.py --verbose        # 통과 케이스도 출력
```

평가 로직:
1. **posture 일치**: `expected_posture` vs `analyze_pose` 결과
2. **이슈 메시지 포함**: `expected_issue_key`가 비어있지 않으면 `MSG[expected_issue_key]`가 `feedback`에 포함되는지 검사 (Korean substring match)
3. **not_detected 케이스**: feedback이 정확히 `MSG["person_not_detected"]`와 일치
4. **종료 코드**: 실패 0건이면 0, 1건 이상이면 1 (CI 통합 가능)

출력: 라벨별/운동별 정확도 테이블 + 실패 케이스의 actual vs expected 상세

### 기존 13장 마이그레이션

10주차까지 평탄 배치되어 있던 13장(`pushup_*.jpg` 5장 + `person_capture_*.jpg` 3장 + 더미 3장 + 실수 파일 2장)을 `git mv`로 이력을 보존하며 라벨 폴더로 이동:

| 원본 | 이동 위치 | 라벨 |
|---|---|---|
| `pushup_1.jpg` | `pushup/good_up/m1_side_01.jpg` | good_up (avg_elbow ~160) |
| `pushup_2.jpg` | `pushup/good_down/m1_side_01.jpg` | good_down (avg_elbow ~96) |
| `pushup_3.jpg` | `pushup/hip_sag/m1_side_01.jpg` | hip_sag |
| `pushup_4.jpg` | `pushup/hip_pike/m1_side_01.jpg` | hip_pike |
| `pushup_5.jpg` | `pushup/camera_angle/m1_front_01.jpg` | camera_angle |
| `person_capture_*528/532.jpg` | `squat/good_up/m1_front_*.jpg` | good_up (기립) |
| `person_capture_*536.jpg` | `squat/left_knee_forward/m1_side_01.jpg` | left_knee_forward |

초기 검증 결과: **11/11 PASS (100%)** — 10주차 분석기 동작과 manifest 라벨이 완전 일치함을 확인.

### 새 운동 추가 시 워크플로우

1. `EXERCISE_REGISTRY`에 분석기 등록 (`up_thr` / `down_thr` / `primary_angle_keys` 클래스 속성 포함)
2. `test_images/<exercise>/` 폴더 생성, 이슈 키별 하위 폴더 생성 (`.gitkeep`로 빈 폴더 보존)
3. 팀원별 촬영 분담 (good_up/good_down + 각 이슈, 운동당 약 30장 목표 = 4인 × 라벨당 1~2장)
4. `manifest.csv`에 행 추가
5. `python src/test_dataset.py --exercise <exercise>` 실행 → 라벨별 정확도 확인

### ExerciseSessionManager (`src/session_state.py`)

`analyze_pose()`는 단일 프레임에 대해 stateless로 결과를 내지만, 실제 사용자 세션에서는 **rep 카운트·이슈 빈도·rep 단위 이슈 묶음** 같은 누적 상태가 필요하다. `ExerciseSessionManager`는 이 상태를 **운동별로 분리 보존**하는 단일 책임 매니저.

```python
sm = ExerciseSessionManager()
result = analyze_pose(frame, "squat")
enriched = sm.update("squat", result)  # → result + count/stage/rep_completed

# 운동 전환 — squat 상태는 매니저 안에 그대로 보존
result = analyze_pose(frame, "pushup")
sm.update("pushup", result)

# squat 으로 돌아가면 이전 카운트가 이어짐
sm.update("squat", analyze_pose(frame, "squat"))

summary = sm.get_summary()  # 세션 전체를 JSON 직렬화 가능한 dict로
```

설계 원칙:
- **단일 책임**: 매니저는 상태만 다룬다. 분석은 호출자가 `analyze_pose()`로 수행 후 결과를 `update()`에 넘김 → 테스트·재사용 용이
- **운동별 격리**: 한 운동의 카운터·이슈가 다른 운동의 통계를 오염시키지 않음. 운동 전환 시 자동으로 별도 `ExerciseState` bucket 생성
- **Registry 자동 인식**: `EXERCISE_REGISTRY`에 새 분석기가 추가되면 매니저 코드 수정 없이 즉시 사용 가능 (rep 임계값을 분석기 클래스 속성에서 끌어옴)
- **`reset(exercise=None)`**: 특정 운동만 또는 세션 전체 초기화 지원

`ExerciseState` 필드:
- `counter`: `RepCounter` (운동별 임계값 자동 주입)
- `issue_counts`: `{full_key → 발생 횟수}` (full_key = `<exercise>.<issue>`)
- `rep_records`: `[{"rep": int, "issues": [full_key, ...]}]` (rep 단위 이슈 묶음)
- `last_posture` / `last_feedback`: 마지막 프레임 결과

#### 분석기 출력 schema 확장 (11주차)

`ExerciseAnalyzer.analyze()` 반환 dict에 **`issues: list[str]`** 추가 (exercise prefix 없는 이슈 키 — 예: `["hip_sag"]`). 매니저는 이 키를 받아 `<exercise>.<key>` 형태로 prepend해 `issue_counts`에 누적. 한국어 feedback 문자열 파싱 없이 깨끗한 통계 가능.

기존 `posture` / `feedback` / `angles`는 유지 → 9·10주차 클라이언트 100% 하위 호환.

#### FeedbackManager 키 통일 (11주차)

8주차에 도입된 `FeedbackManager`는 squat 단일 운동 가정으로 prefix 없는 키(`left_knee_forward` 등)를 사용했고, 이를 위한 prefix-less compat dict `FEEDBACK_MESSAGES`가 별도로 있었다. 11주차 다중 운동 지원을 받아 다음과 같이 통일:

- `update(issues, exercise: str)` — `exercise` 인자 신규. 내부에서 `<exercise>.<key>` 형태 full key로 prepend
- 모든 내부 저장(`active_feedbacks` / `current_rep_issues` / `session_stats`)이 full key 사용 → 동일 issue 명을 갖는 다른 운동(예: `pushup.hip_sag` vs `lunge.hip_sag`) 격리
- 한국어 메시지는 `feedback_messages.MESSAGES`를 full key로 직접 조회 → `FEEDBACK_MESSAGES` compat dict 제거 (deadcode)
- `issues` 인자는 `["key", ...]` 문자열 리스트와 `[{"key": ..., "label": ...}, ...]` legacy dict 형식 모두 수용 → analyze_pose 결과를 그대로 흘려넣기 가능

### LungeAnalyzer (앞다리 식별 휴리스틱)

런지는 좌우 다리가 비대칭으로 동작하므로 폼 검사 전에 **앞다리 식별**이 선행되어야 한다. 단일 신호로는 안정적이지 않아 3-stage 폴백 체인을 사용한다.

| 우선순위 | 신호 | 임계값 | 의도 |
|---|---|---|---|
| 1 | **Z (깊이)** — `ankle.z` 비교 | \|Δz\| > 0.05 | 측면 촬영에서 카메라에 더 가까운 발목(Z 작음)이 앞다리 |
| 2 | **Y (높이) 폴백** — `knee.y` 비교 | \|Δy\| > 0.05 | Z가 ambiguous할 때 사용. 뒷다리 무릎이 바닥쪽으로 내려가므로 Y가 큼 |
| 3 | **히스테리시스** — 이전 프레임 결정 유지 | — | Z·Y 모두 ambiguous면 직전 결과 그대로. 첫 프레임이면 None → `lunge.unknown_front_leg` |

이슈 키: `front_knee_forward`, `trunk_lean`, `unknown_front_leg`. DOWN stage에서만 폼 검사.

**메시지 카탈로그 (`feedback_messages.MESSAGES`)는 차기 분석기 확장 대비 5개 예약 키 포함**: `lunge.front_knee_inward` (무릎 valgus), `lunge.back_knee_high` (깊이 부족), `lunge.hip_drop` (골반 비대칭), `lunge.front_foot_lift` (앞발 뒤꿈치 들림), `lunge.knee_asymmetry` (양쪽 깊이 차). 분석기가 emit하기 시작하면 즉시 한국어 피드백이 노출되도록 사전 등록.

**stateless 원칙의 예외**: `LungeAnalyzer`는 `_prev_front` 인스턴스 상태(히스테리시스)를 보유한다. `EXERCISE_REGISTRY`의 단일 인스턴스 공유는 단일 세션 가정. WebSocket 다중 클라이언트 환경에서는 클라이언트별 인스턴스 또는 세션 시작 시 `reset()` 호출이 필요. 이 제약은 12주차에 분석기 팩토리 도입 시점에 정리 예정.

### RepCounter 일반화 (운동 무관 횟수 카운터)

10주차까지 squat 전용이던 `SquatCounter`를 임계값·각도 키를 인자로 받는 `RepCounter`로 일반화하였다. 운동별 임계값은 **분석기 클래스 속성을 단일 출처**로 사용해 분석기 내부 stage 판정과 RepCounter가 자동으로 동기화된다.

```python
class SquatAnalyzer:
    up_thr             = 160
    down_thr           = 120
    primary_angle_keys = ["left_knee", "right_knee"]
    # analyze() 내부 stage 판정도 self.up_thr / self.down_thr 사용

class PushupAnalyzer:
    up_thr             = 160
    down_thr           = 100
    primary_angle_keys = ["left_elbow", "right_elbow"]

# RepCounter — 운동 무관 카운터
counter = make_rep_counter("squat")        # 분석기에서 임계값 자동 주입
result = analyze_pose(frame, "squat")
count, stage = counter.update(result["angles"])
```

핵심:
- `RepCounter.update(angles: dict)` — `analyze_pose` 반환의 `angles`를 그대로 받음 (호출자가 분해 X)
- `primary_angle_keys`로 좌·우 평균 처리 → squat=무릎, pushup=팔꿈치 모두 동일 코드로
- `make_rep_counter(exercise)` 팩토리 — `EXERCISE_REGISTRY[exercise]`에서 임계값 끌어옴
- 미지원 운동명 → `UnsupportedExerciseError`
- `SquatCounter`는 8주차 시그니처(`update(angle_lk, angle_rk)`)를 보존한 **얇은 호환 래퍼**로 유지 — 내부적으로 `RepCounter`에 위임

설계 결정:
- 임계값 위치를 **분석기 클래스 속성** vs 별도 `REP_CONFIG` dict 두 안 중 전자 채택. 분석기의 stage 판정과 카운터가 같은 값을 공유하므로 임계값 변경 시 한 곳만 고치면 되어 불일치 위험 0
- `ExerciseAnalyzer` Protocol에 `up_thr`/`down_thr`/`primary_angle_keys` 필드 추가 → 새 운동 분석기 작성 시 컨트랙트로 강제

## 12주차: GCP Cloud Run 배포

안드로이드 클라이언트가 다른 네트워크에서도 실시간 연동을 할 수 있도록 FastAPI 서버(`pose_server.py`)를 GCP Cloud Run에 컨테이너로 배포하였다. 서버리스는 장기 WebSocket 연결에 부적합하지만 Cloud Run은 WebSocket을 지원하면서 유휴 시 인스턴스 0대로 축소(scale-to-zero)되어 비용 부담이 거의 없어 채택.

### 배포 좌표

| 항목 | 값 |
|---|---|
| GCP 프로젝트 | `moduflow-ai-pose` (프로젝트 번호 489316272296) — 본인의 다른 프로젝트와 분리, 동일 결제 계정 |
| 서비스 | Cloud Run `moduflow-ai`, 리전 `asia-northeast3` (서울) |
| 공개 URL | `https://moduflow-ai-489316272296.asia-northeast3.run.app` |
| 엔드포인트 | REST `POST /analyze` · WS `wss://.../ws` · 헬스 `/health` · Swagger `/docs` · OpenAPI `/openapi.json` |
| 인증 | `--allow-unauthenticated` (공개) — 안드로이드가 GCP 인증 없이 접근 |
| 스펙 | `--memory=2Gi --cpu=2 --timeout=3600 --cpu-boost`, `min-instances=0` |

→ 안드로이드 측 연동 시 로컬과 달리 **`wss://` (TLS)** 로 WebSocket에 접속해야 함.

### 배포 산출물 (`ai_pose_project/`)

- **`Dockerfile`** — `python:3.11-slim` 기반. `libgl1`/`libglib2.0-0` apt 설치(OpenCV 런타임), `requirements.txt` 설치, `pose_landmarker_lite.task`(src의 부모 위치)와 `src/` 복사, `CMD`에서 `uvicorn pose_server:app --host 0.0.0.0 --port ${PORT} --app-dir src` (Cloud Run이 `PORT` 주입, 기본 8080)
- **`requirements.txt`** — venv 핀 버전과 동일. `uvicorn[standard]`로 지정해 `/ws` 동작에 필요한 websockets 구현체 포함. `mediapipe`가 요구하는 `opencv-contrib-python` 사용
- **`.dockerignore` / `.gcloudignore`** — `venv/`, `test_images/`, `docs/`, `data/`, `src/test/`, `__pycache__` 등을 빌드/업로드에서 제외
- 모델 파일(`*.task`)은 `.gitignore`로 저장소에 없지만, `gcloud run deploy --source` 는 git이 아닌 로컬 작업 디렉토리를 업로드하므로 배포 시 포함됨. 다른 머신에서 clone 후 배포하려면 모델 파일을 별도로 받아야 함

### 운영 명령

```bash
# 재배포 (서버 코드 수정 후) — ai_pose_project/ 디렉토리에서
gcloud run deploy moduflow-ai --source . --project=moduflow-ai-pose --region=asia-northeast3 --quiet

# 시연 직전: 콜드스타트 제거 (항상 1대 유지)
gcloud run services update moduflow-ai --region=asia-northeast3 --project=moduflow-ai-pose --min-instances=1
# 시연 후 원복
gcloud run services update moduflow-ai --region=asia-northeast3 --project=moduflow-ai-pose --min-instances=0

# 로그 확인
gcloud run services logs read moduflow-ai --region=asia-northeast3 --project=moduflow-ai-pose --limit=50
```

### WebSocket 세션화 — rep 카운트·이슈 통계를 서버로 이동

11주차까지 `/ws`는 프레임마다 `analyze_pose` 결과만 그대로 돌려주는 **stateless** 엔드포인트였고, rep 카운팅·세션 통계는 클라이언트(`live_client.py`, Android) 책임이었다. 12주차에 클라이언트(특히 Android)의 부담을 줄이고 카운팅 로직의 단일 출처를 보장하기 위해, 이미 만들어져 있던 `ExerciseSessionManager`(`session_state.py`)를 **`/ws` 핸들러가 연결 단위로 보유**하도록 했다. REST `/analyze`는 단발 분석이라 그대로 stateless 유지.

- 연결마다 `ExerciseSessionManager()` 1개 생성 → 운동별 rep 카운트·이슈 통계·rep 단위 이슈 묶음을 누적. 운동 전환 시에도 각 운동 상태 보존(squat→pushup→squat 복귀 시 카운트 이어짐). 연결 종료 시 세션도 종료(현재 세션 재개 미지원 — 끊기면 새 세션).
- **수신 메시지 타입 추가**:
  - `{"type": "frame", "image", "exercise"}` — 기존과 동일
  - `{"type": "reset", "exercise"?}` — `exercise` 생략 시 세션 전체 초기화 → `{"type": "reset_ok", "exercise": <or null>}`
  - `{"type": "summary"}` — `{"type": "summary", "summary": {...get_summary()...}}`
- **`result` 응답 필드 확장**: 기존 `posture/feedback/angles/exercise`에 더해 `issues`(prefix 없는 이슈 키 배열), `count`(현재 rep 수), `stage`(`UP/DOWN/MID`), `rep_completed`(이 프레임에서 DOWN→UP 전이 발생 여부) 추가. 9·10주차 클라이언트는 추가 필드를 무시하면 그대로 동작 → 하위 호환.
- 사람 미검출 등으로 `angles`가 `{}`여도 `RepCounter.update`가 빈 값을 무시하므로 안전. `exercise` 검증은 `analyze_pose`가 먼저 수행하므로 `session.update`는 추가로 던지지 않음.
- `analyze_pose` 결과 dict가 `response_model`로 필터링되는 REST와 달리 WS는 직접 직렬화하므로 `issues`까지 그대로 전달.
- **잔여 과제**: `LungeAnalyzer._prev_front`는 여전히 `EXERCISE_REGISTRY`의 전역 단일 인스턴스에 묶여 있어 동시 다중 연결 시 lunge 앞다리 판정이 섞일 수 있음. rep 카운트는 연결별로 격리됐지만 분석기 인스턴스 격리(분석기 팩토리)는 별도 작업으로 남김.

### 피드백 2단계: 실시간(짧게) vs 세트 종료(자세히)

실시간 오버레이에는 짧은 한 줄 피드백을, 세트(운동 세션) 종료 요약에는 상세 코칭을 보여주는 2단계 구조.

- **`feedback_messages.MESSAGES`** (실시간용) — 모바일 오버레이에 뜨는 짧은 문구. 예: `"왼쪽 무릎이 발끝을 넘었어요"`, `"상체를 펴세요"`, `"좋은 자세예요"`. 이슈 여러 개면 `analyze_pose`가 `" | "`로 이어 붙이므로 한 문구는 짧을수록 좋다. WS `result.feedback` / REST `/analyze` 응답이 이걸 쓴다.
- **`feedback_messages.COACHING_TIPS`** (종료 요약용) — 이슈 full key(`"<exercise>.<issue>"`) → 자세한 교정 설명(원인·교정법·주의점). `good_form`/`standby`/공통 키는 이슈가 아니므로 없음. `feedback_messages.tip(key, default="")` 헬퍼 제공.
- **`ExerciseSessionManager.get_summary()` 확장** — 운동별 항목에 다음을 담는다(`_summarize_exercise`):
  - `count` / `clean_reps`(이슈 없이 끝난 rep 수) / `stage` / `last_posture`
  - `issue_counts`: `{full_key → 횟수}`
  - `issues_detail`: `[{key, count, message(짧은 문구), tip(상세 코칭)}]` — 횟수 내림차순(동률은 키 순)
  - `assessment`: 한 줄 평가 문구. 예: `"스쿼트 12회 완료. 자세가 안정적이었어요!"` / `"스쿼트 8회 완료 (5회 깔끔). '상체를 펴세요'가 가장 자주 보였어요. 아래 팁을 확인하세요."`
  - `rep_records`: rep 단위 이슈 묶음(그대로 유지)
- WS `{"type":"summary"}` 응답(`{"type":"summary","summary":{...}}`)이 위 구조를 그대로 전달 → 클라이언트(Android)는 `assessment`를 헤드라인으로, `issues_detail[].message`+`.tip`을 항목으로 그리면 됨. `live_client.py`도 종료 시 콘솔에 같은 형식으로 출력.
- 새 운동/이슈 추가 시: `MESSAGES`에 짧은 문구 + `COACHING_TIPS`에 상세 팁을 같은 full key로 등록하면 요약이 자동으로 따라옴(매니저 코드 수정 불필요).

### 주의 사항

- **콜드 스타트**: 유휴 후 첫 요청 시 컨테이너 기동 + MediaPipe 모델 로딩으로 5~15초 지연. 시연 땐 `min-instances=1` 권장
- **WebSocket 타임아웃**: Cloud Run 요청 타임아웃 최대 3600초(60분) — `--timeout=3600`으로 설정. 한 운동 세션이 60분을 넘으면 재연결 필요
- **`LungeAnalyzer` 인스턴스 상태**: `_prev_front` 히스테리시스를 단일 인스턴스가 공유 → Cloud Run에서 동시 다중 클라이언트가 lunge를 분석하면 앞다리 판정이 섞일 수 있음 (CLAUDE.md 11주차 항목 참고, 12주차 분석기 팩토리 도입 시 정리 예정)
- **신규 프로젝트 빌드 권한 이슈(해결됨)**: `gcloud run deploy --source` 가 기본 컴퓨트 SA(`<번호>-compute@developer.gserviceaccount.com`)로 빌드하는데 권한이 없어 `PERMISSION_DENIED` 발생 → `gcloud projects add-iam-policy-binding moduflow-ai-pose --member=serviceAccount:489316272296-compute@developer.gserviceaccount.com --role=roles/cloudbuild.builds.builder` 로 해결, 이후 유지됨
- **비용**: 요청 처리 시간만 과금되며 유휴 시 0원에 수렴. 인스턴스 수동 중지 불필요

## Conventions

- 언어: 한국어 주석 사용 / 한국어 피드백 메시지 (10주차 전환)
- ESC 키로 프로그램 종료 (웹캠 스크립트 한정)
- BGR → RGB 변환 후 MediaPipe에 전달
- 서버에서는 BGR numpy 배열을 `analyze_pose`의 표준 입력으로 사용
- 분석기는 stateless로 유지, 누적 상태는 외부 호출자 책임
