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
from feedback_messages import MESSAGES, COACHING_TIPS

# 운동명 → 한국어 표기 (요약 문구용). 없으면 키 그대로 사용.
_EXERCISE_LABEL_KO = {"squat": "스쿼트", "pushup": "푸시업", "lunge": "런지"}


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
        """세션 전체 요약. JSON 직렬화 가능한 dict.

        실시간 result 의 짧은 feedback 과 달리, 여기서는 세트 종료 시 보여줄
        **상세 코칭**을 함께 담는다. 운동별로:
          - count / clean_reps / stage / last_posture
          - issue_counts: {full_key → 횟수}
          - issues_detail: [{key, count, message(짧은 문구), tip(상세 코칭)}], 횟수 내림차순
          - assessment: 한 줄 평가 문구 (예: "스쿼트 12회 완료 — 자세가 안정적이었어요!")
          - rep_records: rep 단위 이슈 묶음 (그대로 유지)
        """
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "exercises": {
                ex: self._summarize_exercise(ex, st)
                for ex, st in self._states.items()
            },
        }

    def _summarize_exercise(self, exercise: str, st: ExerciseState) -> dict:
        total = st.counter.count
        clean_reps = sum(1 for r in st.rep_records if not r["issues"])

        # 이슈 빈도 내림차순 + 상세 코칭 팁
        issues_detail = [
            {
                "key":     full_key,
                "count":   cnt,
                "message": MESSAGES.get(full_key, full_key),
                "tip":     COACHING_TIPS.get(full_key, ""),
            }
            for full_key, cnt in sorted(
                st.issue_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]

        label = _EXERCISE_LABEL_KO.get(exercise, exercise)
        if total == 0:
            assessment = f"{label}: 완료된 반복이 없어요. 다시 시도해 보세요."
        elif not issues_detail:
            assessment = f"{label} {total}회 완료. 자세가 안정적이었어요!"
        else:
            top_msg = issues_detail[0]["message"]
            assessment = (
                f"{label} {total}회 완료 ({clean_reps}회 깔끔). "
                f"'{top_msg}'가 가장 자주 보였어요. 아래 팁을 확인하세요."
            )

        return {
            "count":         total,
            "clean_reps":    clean_reps,
            "stage":         st.counter.stage,
            "last_posture":  st.last_posture,
            "issue_counts":  dict(st.issue_counts),
            "issues_detail": issues_detail,
            "assessment":    assessment,
            "rep_records":   list(st.rep_records),
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
