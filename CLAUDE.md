# ModuFlow Project

## Overview

MediaPipe PoseLandmarker를 활용한 실시간 포즈 추정 프로젝트.
웹캠 영상에서 인체 관절을 감지하고 각도를 계산하여 시각화한다.
추후에 모바일 안드로이드 환경으로 변경하고 운동 자세 분석과
자세 피드백을 시각화하는 기능을 제공한다.

## Project Structure

```
moduflow_project/
└── ai_pose_project/
    ├── pose_landmarker_lite.task   # MediaPipe 모델 파일
    ├── venv/                       # Python 가상환경
    ├── test_images/                # 9주차: 테스트 데이터셋
    │   ├── _generate.py            #   더미 이미지 생성기 (blank/noise/stick)
    │   ├── _capture.py             #   웹캠 1프레임 캡처 헬퍼
    │   ├── blank_black.jpg
    │   ├── noise.jpg
    │   ├── stick_figure.jpg
    │   └── person_capture_*.jpg    #   실제 사람 사진
    └── src/
        ├── test_pose.py            # 기본 랜드마크 표시
        ├── test_pose_2.py          # 주요 관절 좌표 출력
        ├── test_pose_3.py          # 관절 각도 계산 + 화면 표시
        ├── test_pose_4.py          # 스쿼트 자세 판별 + 횟수 카운팅
        ├── test_pose_5.py          # 자세 교정 피드백 메시지
        ├── test_pose_6.py          # 데이터 구조 설계 (좌표/각도 저장)
        ├── test_pose_7.py          # 백엔드 API 연동 (Spring)
        ├── test_pose_8.py          # 8주차: 로직 함수화 (analyze_pose)
        ├── pose_server.py          # 8주차: FastAPI 서버 (REST + WebSocket)
        ├── test_analyze.py         # 9주차: analyze_pose 모듈 단독 테스트
        ├── test_client.py          # 9주차: REST + WebSocket 통합 테스트
        └── live_client.py          # 9주차: 실시간 웹캠 → WebSocket 클라이언트
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

## Conventions

- 언어: 한국어 주석 사용
- ESC 키로 프로그램 종료 (웹캠 스크립트 한정)
- BGR → RGB 변환 후 MediaPipe에 전달
- 서버에서는 BGR numpy 배열을 `analyze_pose`의 표준 입력으로 사용
