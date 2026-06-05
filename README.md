# ModuFlow — AI 자세 인식 (FastAPI)

MediaPipe PoseLandmarker 기반 **실시간 운동 자세 분석 서버**.
웹캠/모바일 카메라 프레임에서 인체 관절을 감지해 각도를 계산하고, 운동별 자세 결함을
판정하여 **실시간 피드백 + 반복 횟수 카운팅 + 세트/운동/세션 단위 요약**을 제공한다.

> 본 저장소는 4인 팀 프로젝트 중 **팀원 1(AI 자세 인식)** 파트만 포함한다.
> Spring 백엔드 · Android 앱 · React PWA 는 별도 저장소에서 관리된다.

---

## 통신 구조

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
- **③ 데이터 조회**: React PWA → Spring (저장된 기록 조회·시각화)

→ FastAPI 는 실시간 추론만 담당하고, 데이터 영속화는 Spring 이 전담하는 분리 구조.

---

## 지원 운동 (7종)

| 분류 | 운동 (키) | 폼 검사 |
|---|---|---|
| 하체 | `squat` 스쿼트 | 무릎 넘김 · 상체 숙임 · 좌우 비대칭 |
| 하체 | `lunge` 런지 | 앞무릎 넘김 · 상체 숙임 · 앞다리 식별 |
| 상체 | `pushup` 푸시업 | 엉덩이 처짐/솟음 · 정면 촬영 감지 |
| 상체 | `lateral_raise` 사레레 | 좌우 비대칭 · 과도 거상 |
| 상체 | `shoulder_press` 숄더프레스 | 좌우 비대칭 |
| 상체 | `pullup` 풀업 | 좌우 비대칭 |
| 코어 | `situp` 싯업 | (횟수 + 안내) |

> 반복 횟수 카운팅은 **적응형(골짜기 검출)** 이라 운동별 데이터 없이도 정확하게 동작한다.
> 데드리프트·벤치프레스·플랭크는 2D 단일 카메라 한계로 보류 (자세한 내용은 `CLAUDE.md`).

---

## 기술 스택

- **Python** · FastAPI · Uvicorn · Pydantic
- **MediaPipe** PoseLandmarker (Tasks API) · OpenCV · NumPy · Pillow
- **WebSocket** (실시간 스트리밍) · GCP Cloud Run (배포)

전체 의존성은 [`ai_pose_project/requirements.txt`](ai_pose_project/requirements.txt) 참고.

---

## 빠른 시작 (로컬)

```bash
cd ai_pose_project

# 1) 가상환경 + 의존성
python -m venv venv
venv\Scripts\activate            # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt

# 2) 모델 파일 배치 (저장소 미포함 — .gitignore)
#    pose_landmarker_lite.task 를 ai_pose_project/ 에 둔다

# 3) 서버 실행
uvicorn pose_server:app --host 0.0.0.0 --port 8000 --reload --app-dir src

# 4) 헬스체크
curl http://127.0.0.1:8000/health     # → {"status":"ok"}
```

> ⚠️ MediaPipe 모델 파일 `pose_landmarker_lite.task` 는 용량 문제로 저장소에 포함되지 않는다(`.gitignore`).
> 별도로 받아 `ai_pose_project/` 에 배치해야 한다.

---

## API 개요

비즈니스 경로는 `/api/v1` prefix, JSON Key 는 camelCase (팀 공통 컨벤션).
운영용 `GET /` · `GET /health` 만 root 유지.

### REST — `POST /api/v1/analyze`
단발 프레임 분석.
```jsonc
요청:  { "image": "<base64>", "exercise": "squat" }
응답:  { "posture": "good|bad", "feedback": "...", "angles": {...}, "exercise": "squat" }
```

### WebSocket — `/api/v1/ws`
연결 단위 실시간 스트리밍 (VIDEO 모드 + rep 카운트·이슈 통계 누적).
```jsonc
수신:  { "type": "frame",   "image": "<base64>", "exercise": "squat" }
       { "type": "set_end", "exercise": "squat", "isLastSet": false }   // 세트 종료
       { "type": "session_end" }                                        // 전체 운동 종료
송신:  { "type": "result",           ... "count", "stage", "repCompleted" }
       { "type": "set_feedback",      "summary": {...} }   // 1단계: 세트
       { "type": "exercise_feedback", "summary": {...} }   // 2단계: 운동 종목
       { "type": "session_feedback",  "summary": {...} }   // 3단계: 전체
```

→ **3단계 피드백**(세트 → 운동 → 세션)과 필드 구조는 `CLAUDE.md` 참고.

---

## 배포 (GCP Cloud Run)

| 항목 | 값 |
|---|---|
| 공개 URL | `https://moduflow-ai-489316272296.asia-northeast3.run.app` |
| REST | `POST /api/v1/analyze` |
| WebSocket | `wss://.../api/v1/ws` (TLS 필수) |
| 헬스 | `GET /health` · Swagger `GET /docs` |

```bash
# 재배포 (ai_pose_project/ 에서)
gcloud run deploy moduflow-ai --source . --project=moduflow-ai-pose --region=asia-northeast3 --quiet
```

> 콜드 스타트(유휴 후 첫 요청 5~15초)가 있으므로, 시연 직전엔 `min-instances=1` 권장.

---

## 검증 / 데이터셋

규칙 기반 분석기의 정확도를 **manifest 기반 그라운드 트루스**로 검증한다.

```bash
python src/test_dataset.py                  # 전체 검증 (라벨별 정확도)
python src/test_dataset.py --exercise squat # 특정 운동만
python src/test_client.py                   # REST + WS 통합 테스트 (서버 실행 중)
```

- 데이터셋 구조·라벨 컨벤션: [`ai_pose_project/test_images/README.md`](ai_pose_project/test_images/README.md)
- 영상→프레임 추출 도구: `ai_pose_project/test_images/_extract.py`
- 팀 촬영 가이드: [`ai_pose_project/docs/capture_guide_w14.md`](ai_pose_project/docs/capture_guide_w14.md)

---

## 프로젝트 구조

```
ai_pose_project/
├── pose_landmarker_lite.task   # MediaPipe 모델 (.gitignore — 저장소 미포함)
├── Dockerfile / requirements.txt
├── docs/                       # 팀 공유 자료 (API 변경·촬영 가이드 등)
├── test_images/                # 검증 데이터셋 (운동/라벨 폴더 + manifest.csv)
└── src/
    ├── test_pose_8.py          # 분석 로직 (분석기 7종 · RepCounter · LivePoseSession)
    ├── pose_server.py          # FastAPI 서버 (REST + WebSocket)
    ├── session_state.py        # 세션/세트 누적 상태 + 3단계 피드백
    ├── feedback_messages.py    # 한국어 피드백 메시지 + 코칭 팁
    ├── live_client.py          # 실시간 웹캠 클라이언트 (로컬 테스트)
    └── test_*.py               # 모듈/통합/데이터셋 검증
```

---

## 문서

- **[`CLAUDE.md`](CLAUDE.md)** — 주차별 상세 개발 로그 · 설계 결정 · 아키텍처 (8~14주차)
- `ai_pose_project/docs/` — 팀 공유 API 스펙·촬영 가이드
- `ai_pose_project/test_images/README.md` — 데이터셋 라벨링 체계
