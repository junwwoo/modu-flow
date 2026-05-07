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
    ├── pose_landmarker_lite.task   # MediaPipe 모델 파일
    ├── venv/                       # Python 가상환경
    ├── docs/                       # 10주차: 팀 공유 자료
    │   ├── api_changes_w10.md      #   변경 요약 + REST/WS 스키마 + 팀별 액션 아이템
    │   ├── openapi_w10.json        #   FastAPI 자동 생성 OpenAPI 스펙
    │   └── samples_w10.json        #   REST/WS 정상·에러 응답 7종 실측 샘플
    ├── test_images/                # 9~10주차: 테스트 데이터셋
    │   ├── _generate.py            #   더미 이미지 생성기 (blank/noise/stick)
    │   ├── _capture.py             #   웹캠 1프레임 캡처 헬퍼
    │   ├── blank_black.jpg
    │   ├── noise.jpg
    │   ├── stick_figure.jpg
    │   ├── person_capture_*.jpg    #   9주차: 실제 사람 사진
    │   └── pushup_*.jpg            #   10주차: Push-up 1차 튜닝 표본 5장
    └── src/
        ├── test_pose_8.py          # 8주차 로직 함수화 + 10주차 ExerciseRegistry
        ├── pose_server.py          # 8주차 FastAPI 서버 (REST + WebSocket)
        ├── feedback_messages.py    # 10주차: 한국어 피드백 메시지 dict
        ├── test_analyze.py         # 9주차: analyze_pose 모듈 단독 테스트
        ├── test_client.py          # 9주차: REST + WebSocket 통합 테스트
        ├── live_client.py          # 9주차: 실시간 웹캠 → WebSocket 클라이언트
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
- 서버 실행: `uvicorn pose_server:app --host 0.0.0.0 --port 8000 --reload` (어느 디렉토리에서든 실행 가능)
- 헬스체크: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`

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

- `ExerciseAnalyzer`(typing.Protocol) — 운동별 분석기 인터페이스. **stateless** (rep 카운팅·이슈 누적은 외부 호출자 담당, 11주차 `ExerciseSessionManager`로 분리 예정)
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

## Conventions

- 언어: 한국어 주석 사용 / 한국어 피드백 메시지 (10주차 전환)
- ESC 키로 프로그램 종료 (웹캠 스크립트 한정)
- BGR → RGB 변환 후 MediaPipe에 전달
- 서버에서는 BGR numpy 배열을 `analyze_pose`의 표준 입력으로 사용
- 분석기는 stateless로 유지, 누적 상태는 외부 호출자 책임
