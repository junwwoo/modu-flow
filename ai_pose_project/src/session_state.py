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
_EXERCISE_LABEL_KO = {
    "squat": "스쿼트", "pushup": "푸시업", "lunge": "런지",
    "lateralraise": "사이드 레터럴 레이즈", "shoulderpress": "숄더프레스",
    "pullup": "풀업", "situp": "싯업",
}


@dataclass
class ExerciseState:
    """단일 운동의 누적 상태.

    counter/issue_counts/rep_records 는 **현재 진행 중인 세트**의 누적치이며,
    세트 종료(`end_set`) 시 그 시점 요약이 `completed_sets` 로 스냅샷되고 초기화된다.
    세트 개념을 쓰지 않는 호출자(예: live_client)는 세트를 한 번도 끝내지 않으므로
    전체가 하나의 진행 중 세트처럼 동작한다(하위 호환).
    """
    counter:        RepCounter
    issue_counts:   dict[str, int] = field(default_factory=dict)   # full_key (e.g. "squat.left_knee_forward") → 발생 횟수
    rep_records:    list[dict]     = field(default_factory=list)   # [{"rep": int, "issues": list[full_key]}]
    last_feedback:  str = ""
    last_posture:   str = ""
    completed_sets: list[dict]     = field(default_factory=list)   # 종료된 세트별 요약 스냅샷 (1단계)
    _current_rep_issues: set[str]  = field(default_factory=set)
    _disp_feedback: str = ""        # 실시간 표시용 피드백(throttle 적용) — 매 프레임 안 바뀜
    _disp_hold:     int = 0         # 현재 표시 메시지를 더 유지할 남은 프레임 수


class ExerciseSessionManager:
    """세션 단위로 운동별 카운터·이슈 통계를 보존한다.

    Usage:
        sm = ExerciseSessionManager()
        result = analyze_pose(frame, "squat")
        enriched = sm.update("squat", result)
        # enriched 에 count, stage, repCompleted 추가됨

        # 다른 운동 전환 — squat 상태는 매니저 안에 그대로 보존
        result = analyze_pose(frame, "pushup")
        enriched = sm.update("pushup", result)

        # squat 으로 돌아가면 이전 카운트가 이어짐
        result = analyze_pose(frame, "squat")
        enriched = sm.update("squat", result)

        summary = sm.get_summary()
    """

    def __init__(self, session_id: Optional[str] = None,
                 feedback_hold_frames: int = 12) -> None:
        self.start_time = datetime.now()
        self.session_id = session_id or f"sess-{self.start_time.strftime('%Y%m%d_%H%M%S')}"
        self._states: dict[str, ExerciseState] = {}
        # 실시간 피드백 throttle: 표시 메시지를 최소 이 프레임 수만큼 유지한 뒤에만 교체.
        # 클라이언트 fps 기준 대략 (frames / fps)초. 0 이면 매 프레임 갱신(throttle 끔).
        self.feedback_hold_frames = max(0, feedback_hold_frames)

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
            result에 다음 키를 덧붙인 새 dict (JSON Key 컨벤션 → camelCase):
              - "count": 현재 rep 카운트
              - "stage": "UP" | "DOWN" | "MID"
              - "repCompleted": 이 프레임에서 rep이 완료되었는가 (DOWN→UP 전이)
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

        # 실시간 피드백 throttle — 매 프레임 새 문구로 갱신하면 메시지가 깜빡이므로,
        # 현재 표시 메시지를 feedback_hold_frames 동안 유지한 뒤에만 새 문구로 교체한다.
        # issues 통계는 위에서 매 프레임 그대로 누적했으므로 요약 정확도엔 영향 없음.
        raw_feedback = result.get("feedback", "")
        if state._disp_hold > 0 and state._disp_feedback:
            state._disp_hold -= 1
        else:
            state._disp_feedback = raw_feedback
            state._disp_hold = self.feedback_hold_frames
        display_feedback = state._disp_feedback

        state.last_feedback = display_feedback
        state.last_posture  = result.get("posture", "")

        enriched = dict(result)
        enriched["feedback"]     = display_feedback
        enriched["count"]        = count
        enriched["stage"]        = stage
        enriched["repCompleted"] = rep_completed
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
        **상세 코칭**을 함께 담는다. JSON Key 는 camelCase 컨벤션. 운동별로:
          - count / cleanReps / stage / lastPosture
          - issueCounts: {full_key → 횟수}
          - issuesDetail: [{key, count, message(짧은 문구), tip(상세 코칭)}], 횟수 내림차순
          - assessment: 한 줄 평가 문구 (예: "스쿼트 12회 완료 — 자세가 안정적이었어요!")
          - repRecords: rep 단위 이슈 묶음 (그대로 유지)
        """
        return {
            "sessionId": self.session_id,
            "startTime": self.start_time.isoformat(),
            "exercises": {
                ex: self._summarize_exercise(ex, st)
                for ex, st in self._states.items()
            },
        }

    def _issues_detail(self, issue_counts: dict) -> list[dict]:
        """{full_key → 횟수} → 횟수 내림차순(동률은 키 순) [{key,count,message,tip}]."""
        return [
            {
                "key":     full_key,
                "count":   cnt,
                "message": MESSAGES.get(full_key, full_key),
                "tip":     COACHING_TIPS.get(full_key, ""),
            }
            for full_key, cnt in sorted(
                issue_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]

    def _assess(self, label: str, total: int, clean_reps: int, issues_detail: list) -> str:
        """한 줄 평가 문구. label 은 범위 표기(예: "스쿼트", "스쿼트 1세트", "스쿼트 전체")."""
        if total == 0:
            return f"{label}: 완료된 반복이 없어요. 다시 시도해 보세요."
        if not issues_detail:
            return f"{label} {total}회 완료. 자세가 안정적이었어요!"
        top_msg = issues_detail[0]["message"]
        return (
            f"{label} {total}회 완료 ({clean_reps}회 깔끔). "
            f"'{top_msg}'가 가장 자주 보였어요. 아래 팁을 확인하세요."
        )

    def _summarize_exercise(self, exercise: str, st: ExerciseState) -> dict:
        """현재 진행 중인 세트(누적 accumulator)의 요약. get_summary / live 모니터링용."""
        total = st.counter.count
        clean_reps = sum(1 for r in st.rep_records if not r["issues"])
        issues_detail = self._issues_detail(st.issue_counts)
        label = _EXERCISE_LABEL_KO.get(exercise, exercise)
        return {
            "count":        total,
            "cleanReps":    clean_reps,
            "stage":        st.counter.stage,
            "lastPosture":  st.last_posture,
            "issueCounts":  dict(st.issue_counts),
            "issuesDetail": issues_detail,
            "assessment":   self._assess(label, total, clean_reps, issues_detail),
            "repRecords":   list(st.rep_records),
        }

    def reset(self, exercise: Optional[str] = None) -> None:
        """누적 상태 초기화. exercise 지정 시 해당 운동만, 아니면 전체."""
        if exercise is None:
            self._states.clear()
        else:
            self._states.pop(exercise, None)

    # ──────────────────────────────────────────────────────────
    # 3단계 피드백 (세트 → 운동 → 세션)
    # ──────────────────────────────────────────────────────────
    def end_set(self, exercise: str) -> dict:
        """[1단계] 현재 세트를 마감한다.

        현재 누적치를 세트 요약으로 스냅샷해 completed_sets 에 보관하고, 다음 세트를
        위해 카운터·이슈 누적을 초기화한다. 마감된 세트 요약(setNumber 포함)을 반환.
        """
        st = self._get_or_create_state(exercise)
        set_number = len(st.completed_sets) + 1
        summary = self._summarize_exercise(exercise, st)
        # 세트 단위 평가 문구로 덮어쓴다 ("스쿼트 1세트 ...")
        label = _EXERCISE_LABEL_KO.get(exercise, exercise)
        summary["assessment"] = self._assess(
            f"{label} {set_number}세트",
            summary["count"], summary["cleanReps"], summary["issuesDetail"],
        )
        set_record = {"setNumber": set_number, **summary}
        st.completed_sets.append(set_record)
        self._reset_current_set(exercise, st)
        return set_record

    def end_exercise(self, exercise: str) -> dict:
        """[2단계] 한 운동의 모든 완료 세트를 집계한다.

        마지막 세트 end_set 직후 호출하는 것을 전제하나, 진행 중 세트에 rep 이
        남아 있으면(예: 직접 호출) 안전하게 먼저 마감한다.
        """
        st = self._get_or_create_state(exercise)
        if st.counter.count > 0:            # 미마감 세트 flush (안전장치)
            self.end_set(exercise)

        sets = st.completed_sets
        merged: dict[str, int] = {}
        for s in sets:
            for k, v in s["issueCounts"].items():
                merged[k] = merged.get(k, 0) + v
        total_reps  = sum(s["count"] for s in sets)
        total_clean = sum(s["cleanReps"] for s in sets)
        issues_detail = self._issues_detail(merged)
        label = _EXERCISE_LABEL_KO.get(exercise, exercise)
        return {
            "exercise":     exercise,
            "totalSets":    len(sets),
            "totalReps":    total_reps,
            "cleanReps":    total_clean,
            "issueCounts":  merged,
            "issuesDetail": issues_detail,
            "assessment":   self._assess(f"{label} 전체", total_reps, total_clean, issues_detail),
            "sets":         list(sets),
        }

    def end_session(self) -> dict:
        """[3단계] 전체 운동 세션을 집계한다. 진행 중 세트가 남은 운동은 먼저 마감한다."""
        exercises = {
            ex: self.end_exercise(ex)
            for ex, st in self._states.items()
            if st.counter.count > 0 or st.completed_sets
        }
        total_reps = sum(e["totalReps"] for e in exercises.values())
        n_ex = len(exercises)
        assessment = (
            "완료된 운동이 없어요."
            if n_ex == 0
            else f"운동 {n_ex}종목 · 총 {total_reps}회 완료. 수고하셨어요!"
        )
        return {
            "sessionId":  self.session_id,
            "startTime":  self.start_time.isoformat(),
            "exercises":  exercises,
            "assessment": assessment,
        }

    def _reset_current_set(self, exercise: str, st: ExerciseState) -> None:
        """다음 세트를 위해 진행 중 누적치만 초기화(completed_sets 는 보존)."""
        st.counter = make_rep_counter(exercise)
        st.issue_counts = {}
        st.rep_records = []
        st._current_rep_issues = set()
        st.last_feedback = ""
        st.last_posture = ""
        st._disp_feedback = ""
        st._disp_hold = 0

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
