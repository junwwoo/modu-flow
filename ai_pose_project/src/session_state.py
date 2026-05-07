"""
session_state.py — 세션 단위 운동별 누적 상태 관리 (11주차 신규)

`analyze_pose()`는 단일 프레임에 대해 stateless로 결과를 반환한다.
실제 사용자 세션에서는 다음과 같은 누적 상태가 필요하다.

  - 운동별 rep 카운터 (DOWN→UP 전이 카운팅)
  - 운동별 이슈 발생 빈도 통계
  - rep 단위로 발생한 이슈 묶음 기록

`ExerciseSessionManager`는 위 상태를 운동별로 분리 보존한다. 사용자가
운동을 전환해도 각 운동의 누적 카운트·이슈는 그대로 유지되어, 같은 세션
내에서 squat → pushup → squat로 돌아가면 squat 카운트가 이어진다.

설계 원칙:
  - **단일 책임**: 매니저는 상태만 다룬다. 프레임 분석은 호출자가
    `analyze_pose()`로 수행한 뒤 결과 dict를 `update()`에 전달.
  - **운동별 격리**: 한 운동의 카운터·이슈가 다른 운동의 통계를 오염시키지 않음.
  - **지원 분석기 확장 자동 인식**: `EXERCISE_REGISTRY`에 새 분석기가
    추가되면 자동으로 카운터를 만들어 사용 가능. 매니저 코드 수정 불필요.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from test_pose_8 import (
    EXERCISE_REGISTRY,
    RepCounter,
    UnsupportedExerciseError,
    make_rep_counter,
)


@dataclass
class ExerciseState:
    """단일 운동의 세션 누적 상태."""
    counter:        RepCounter
    issue_counts:   dict[str, int] = field(default_factory=dict)   # full_key (e.g. "squat.left_knee_forward") → 발생 횟수
    rep_records:    list[dict]     = field(default_factory=list)   # [{"rep": int, "issues": list[full_key]}]
    last_feedback:  str = ""
    last_posture:   str = ""
    _current_rep_issues: set[str]  = field(default_factory=set)


class ExerciseSessionManager:
    """세션 단위로 운동별 카운터·이슈 통계를 보존한다.

    Usage:
        sm = ExerciseSessionManager()
        result = analyze_pose(frame, "squat")
        enriched = sm.update("squat", result)
        # enriched 에 count, stage, rep_completed 추가됨

        # 다른 운동 전환 — squat 상태는 매니저 안에 그대로 보존
        result = analyze_pose(frame, "pushup")
        enriched = sm.update("pushup", result)

        # squat 으로 돌아가면 이전 카운트가 이어짐
        result = analyze_pose(frame, "squat")
        enriched = sm.update("squat", result)

        summary = sm.get_summary()
    """

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.start_time = datetime.now()
        self.session_id = session_id or f"sess-{self.start_time.strftime('%Y%m%d_%H%M%S')}"
        self._states: dict[str, ExerciseState] = {}

    # ──────────────────────────────────────────────────────────
    # 핵심 API
    # ──────────────────────────────────────────────────────────
    def update(self, exercise: str, result: dict) -> dict:
        """analyze_pose 결과를 받아 운동별 카운터·이슈 통계 갱신.

        Args:
            exercise: 운동명. EXERCISE_REGISTRY에 등록되어 있어야 함.
            result:   analyze_pose 반환 dict. 필수 키:
                      "angles" (RepCounter용), "issues" (list[str], 옵션),
                      "posture" / "feedback" (옵션, 마지막 값 보존용).

        Returns:
            result에 다음 키를 덧붙인 새 dict:
              - "count": 현재 rep 카운트
              - "stage": "UP" | "DOWN" | "MID"
              - "rep_completed": 이 프레임에서 rep이 완료되었는가 (DOWN→UP 전이)
            원본 result는 변경하지 않는다.

        Raises:
            UnsupportedExerciseError: exercise가 EXERCISE_REGISTRY에 없을 때
        """
        state = self._get_or_create_state(exercise)

        prev_count = state.counter.count
        count, stage = state.counter.update(result.get("angles", {}))
        rep_completed = count > prev_count

        # 이슈 통계 누적 — 매 프레임 발생한 이슈를 카운트.
        # 같은 rep 안에서 여러 프레임에 걸쳐 같은 이슈가 반복되면 그대로 누적되며,
        # rep 종료 시 _current_rep_issues 로부터 rep 단위 요약을 생성한다.
        for issue_key in result.get("issues", []):
            full_key = f"{exercise}.{issue_key}"
            state.issue_counts[full_key] = state.issue_counts.get(full_key, 0) + 1
            state._current_rep_issues.add(full_key)

        if rep_completed:
            state.rep_records.append({
                "rep":    count,
                "issues": sorted(state._current_rep_issues),
            })
            state._current_rep_issues.clear()

        state.last_feedback = result.get("feedback", "")
        state.last_posture  = result.get("posture", "")

        enriched = dict(result)
        enriched["count"]         = count
        enriched["stage"]         = stage
        enriched["rep_completed"] = rep_completed
        return enriched

    # ──────────────────────────────────────────────────────────
    # 조회 / 관리
    # ──────────────────────────────────────────────────────────
    def get_state(self, exercise: str) -> Optional[ExerciseState]:
        """특정 운동의 ExerciseState 반환. 시작된 적 없으면 None."""
        return self._states.get(exercise)

    def get_summary(self) -> dict:
        """세션 전체 요약. JSON 직렬화 가능한 dict."""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "exercises": {
                ex: {
                    "count":        st.counter.count,
                    "stage":        st.counter.stage,
                    "issue_counts": dict(st.issue_counts),
                    "rep_records":  list(st.rep_records),
                    "last_posture": st.last_posture,
                }
                for ex, st in self._states.items()
            },
        }

    def reset(self, exercise: Optional[str] = None) -> None:
        """누적 상태 초기화. exercise 지정 시 해당 운동만, 아니면 전체."""
        if exercise is None:
            self._states.clear()
        else:
            self._states.pop(exercise, None)

    # ──────────────────────────────────────────────────────────
    # 내부
    # ──────────────────────────────────────────────────────────
    def _get_or_create_state(self, exercise: str) -> ExerciseState:
        if exercise not in EXERCISE_REGISTRY:
            raise UnsupportedExerciseError(exercise)
        st = self._states.get(exercise)
        if st is None:
            st = ExerciseState(counter=make_rep_counter(exercise))
            self._states[exercise] = st
        return st
