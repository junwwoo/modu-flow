# ModuFlow Pose API — 10주차 변경 안내

| 항목 | 내용 |
|---|---|
| 작성자 | 팀원 1 (AI 자세 인식) |
| 대상 | 팀원 2 (Spring), 팀원 3 (Android), 팀원 4 (React PWA) |
| 적용 시점 | 10주차 |
| 호환성 | **하위 호환** — 기존 클라이언트 코드 변경 없이 그대로 동작 |
| 첨부 | `openapi_w10.json` (FastAPI 자동 생성), `samples_w10.json` (실제 응답 샘플) |

---

## 1. 한 줄 요약

REST `/analyze` 와 WebSocket `/ws` 양쪽에 **운동 종류를 선택하는 `exercise` 필드**가 추가되었습니다. 생략 시 `"squat"`로 처리되므로 기존 코드는 수정 없이 동작합니다. 응답에는 `exercise` 필드가 에코됩니다.

지원 운동: `"squat"`, `"pushup"` (10주차 기준). 11주차에 `"lunge"` 추가 예정.

피드백 메시지는 **한국어로 전환**되었습니다. 메시지 키는 영문 그대로 유지(예: `squat.left_knee_forward`)됩니다.

---

## 2. REST: `POST /analyze`

### 2.1 요청 스키마

```json
{
  "image":    "<base64 인코딩 이미지 문자열>",
  "exercise": "squat"
}
```

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `image` | string | O | — | base64. `data:image/...;base64,` 접두 자동 제거 |
| `exercise` | string | X | `"squat"` | `"squat"` \| `"pushup"` |

### 2.2 응답 스키마 (200 OK)

```json
{
  "posture":  "good",
  "feedback": "...",
  "angles":   { ... },
  "exercise": "squat"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `posture` | string | `"good"` \| `"bad"` |
| `feedback` | string | 한국어 피드백 메시지 (이슈 여러 개면 ` \| `로 구분) |
| `angles` | object | **운동별로 키 다름** (아래 표) |
| `exercise` | string | 분석에 사용된 운동명 (요청 에코) |

### 2.3 운동별 `angles` 키

| 운동 | angles 키 |
|---|---|
| `squat` | `left_knee`, `right_knee`, `left_hip`, `right_hip` |
| `pushup` | `left_elbow`, `right_elbow`, `left_shoulder`, `right_shoulder` |

각도 단위: 도(degree), 소수점 1자리.

### 2.4 응답 예시 — 스쿼트 (`exercise` 생략 == `"squat"`)

```json
{
  "posture": "bad",
  "feedback": "왼쪽 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요. | 오른쪽 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요. | 상체가 너무 숙여졌습니다. 가슴을 들고 등을 곧게 유지하세요.",
  "angles": {
    "left_knee": 86.8,
    "right_knee": 97.2,
    "left_hip": 110.8,
    "right_hip": 116.0
  },
  "exercise": "squat"
}
```

### 2.5 응답 예시 — 푸시업

```json
{
  "posture": "bad",
  "feedback": "팔꿈치가 너무 벌어졌습니다. 몸통 가까이 붙이세요.",
  "angles": {
    "left_elbow": 55.3,
    "right_elbow": 70.5,
    "left_shoulder": 42.7,
    "right_shoulder": 43.9
  },
  "exercise": "pushup"
}
```

### 2.6 에러 응답

| HTTP | detail | 케이스 |
|---|---|---|
| 400 | `"image 필드가 비어 있습니다."` | `image` 빈 문자열 |
| 400 | `"base64 디코딩에 실패했습니다."` | base64 형식 오류 |
| 400 | `"이미지 파일 형식을 인식할 수 없습니다."` | 디코딩은 됐으나 이미지 아님 |
| 400 | `"잘못된 data URL 형식입니다."` | `data:` 접두는 있으나 콤마 없음 |
| 400 | `"지원하지 않는 운동입니다."` | `exercise`가 `"squat"`/`"pushup"` 아님 |
| 500 | `"자세 분석에 실패했습니다. 잠시 후 다시 시도해주세요."` | MediaPipe 추론 등 내부 예외 |

```json
// 예시: exercise=plank 요청
HTTP 400
{ "detail": "지원하지 않는 운동입니다." }
```

---

## 3. WebSocket: `/ws`

연결 유지 상태에서 프레임마다 다른 운동을 보낼 수 있습니다 (서버 stateless).

### 3.1 클라이언트 → 서버

```json
{
  "type":     "frame",
  "image":    "<base64>",
  "exercise": "squat"
}
```

`exercise` 생략 시 `"squat"` 기본값. **연결 유지 중 프레임마다 다른 `exercise` 전송 가능** — 운동 전환 시 새 연결을 맺을 필요 없음.

### 3.2 서버 → 클라이언트 (성공)

```json
{
  "type":     "result",
  "posture":  "good",
  "feedback": "...",
  "angles":   { ... },
  "exercise": "pushup"
}
```

### 3.3 서버 → 클라이언트 (에러)

```json
{
  "type":    "error",
  "message": "지원하지 않는 운동입니다."
}
```

에러 메시지 종류:
- `"JSON 파싱 실패"`
- `"지원하지 않는 type: <값>"` (`type`이 `"frame"`이 아닐 때)
- `"image 필드가 비어 있습니다."`
- `"base64 디코딩에 실패했습니다."`
- `"이미지 파일 형식을 인식할 수 없습니다."`
- `"지원하지 않는 운동입니다."` (10주차 신규)
- `"자세 분석에 실패했습니다. 잠시 후 다시 시도해주세요."` (10주차 신규)

**개별 프레임 에러는 연결을 끊지 않습니다** — 다음 프레임은 정상 처리됩니다 (9주차와 동일 동작).

---

## 4. 피드백 메시지 키 카탈로그

`feedback` 필드 본문은 한국어 문구이지만, 클라이언트에서 이슈 통계를 집계하거나 아이콘을 매핑하려면 **메시지 키**가 필요합니다. 현재 응답에는 `feedback` 텍스트만 노출되며, 키 자체는 응답에 포함되지 않습니다(요청 시 추가 가능 — 필요하면 알려주세요).

| 키 | 한국어 문구 |
|---|---|
| `squat.left_knee_forward` | 왼쪽 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요. |
| `squat.right_knee_forward` | 오른쪽 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요. |
| `squat.trunk_lean` | 상체가 너무 숙여졌습니다. 가슴을 들고 등을 곧게 유지하세요. |
| `squat.knee_asymmetry` | 양쪽 무릎의 깊이가 다릅니다. 균형을 맞추세요. |
| `squat.good_form` | 좋은 스쿼트 자세입니다. |
| `squat.standby` | 준비 자세를 잡아주세요. |
| `pushup.elbow_flare` | 팔꿈치가 너무 벌어졌습니다. 몸통 가까이 붙이세요. |
| `pushup.hip_sag` | 엉덩이가 처졌습니다. 코어에 힘을 주고 일직선을 유지하세요. |
| `pushup.hip_pike` | 엉덩이가 솟았습니다. 등에서 발끝까지 일직선을 유지하세요. |
| `pushup.camera_angle` | 측면에서 촬영해주세요. |
| `pushup.good_form` | 좋은 푸시업 자세입니다. |
| `pushup.standby` | 푸시업 준비 자세를 잡아주세요. |
| `person_not_detected` | 사람이 감지되지 않았습니다. |
| `inference_failed` | 자세 분석에 실패했습니다. 잠시 후 다시 시도해주세요. |
| `unsupported_exercise` | 지원하지 않는 운동입니다. |

11주차에 `lunge.*` 키가 추가 예정입니다.

---

## 5. 팀별 액션 아이템

### 팀원 2 — Spring 백엔드

**필요 작업**: rep/세션 페이로드 스키마에 `exercise` 필드를 추가하면 좋겠습니다.

```jsonc
// 예: POST /api/sessions/start (현행 → 권장)
{
  "userId":       "demo-user",
  "startedAt":    "2026-05-07T14:00:00",
  "exerciseType": "squat"   // ← 이미 있다면 OK. 값 도메인을 "squat"|"pushup"로 확장
}

// 예: POST /api/sessions/{id}/reps
{
  "rep":         1,
  "exercise":    "squat",   // ← 신규(권장). 운동별 통계 분리에 사용
  "issues":      ["squat.left_knee_forward", "squat.trunk_lean"],
  "start_frame": 0,
  "end_frame":   145
}
```

- **합의 지연 시 폴백**: Android 측이 `exercise`를 메모리에만 보관하다가 합의 후 전송. 본 변경은 Spring DB 스키마 변경이 없어도 진행 가능.
- 응답 예시·필드 확정 후 회신 부탁드립니다.

### 팀원 3 — Android

**필요 작업**:
1. WebSocket 프레임 메시지에 `exercise` 필드 추가
2. UI에 운동 선택기(라디오/세그먼트 컨트롤) 추가 — `"squat"` / `"pushup"`
3. 응답에서 `exercise` 필드를 읽어 운동별 카운트/이슈 분리(11주차에 lunge 추가될 예정이라 enum이 아닌 string 키로 관리 권장)

```kotlin
// 예시 (Kotlin)
val frame = JSONObject().apply {
    put("type", "frame")
    put("image", base64)
    put("exercise", currentExercise)  // ← "squat" | "pushup"
}
ws.send(frame.toString())
```

**호환성**: `exercise` 필드를 안 보내도 기존처럼 squat으로 동작합니다 — 단계적 도입 가능.

### 팀원 4 — React PWA

이번 변경은 직접 영향 없음. 다만 Spring 측 rep/session 스키마에 `exercise`가 들어가는 시점부터 운동별 통계 시각화가 필요하므로, Spring과 합의 후 작업 시작 부탁드립니다.

---

## 6. 11주차 예고

- `"lunge"` 운동 추가 (`lunge.front_knee_over_toe`, `lunge.back_knee_floor`, `lunge.trunk_lean`, `lunge.unclear_stance`)
- 응답에 메시지 **키 배열 필드**(예: `issue_keys`) 추가 검토 — 클라이언트가 아이콘/색상을 매핑하기 쉬워짐. 의견 주세요.

---

## 7. 직접 확인 방법

1. AI 서버 가동: 본 저장소 `ai_pose_project/` 디렉터리에서
   ```powershell
   & "venv\Scripts\python.exe" -m uvicorn pose_server:app --host 0.0.0.0 --port 8000 --app-dir src
   ```
2. 브라우저에서 `http://<AI서버호스트>:8000/docs` 열면 Swagger UI에서 `exercise` 필드를 직접 시도 가능
3. OpenAPI 스펙 다운로드: `http://<AI서버호스트>:8000/openapi.json` (또는 첨부 `openapi_w10.json` 참고)
4. WebSocket은 첨부 `samples_w10.json`의 요청/응답 페이로드를 참고

문의: 팀원 1
