"""
ai_summary.py — 세션 종료(3단계) 요약을 Gemini 로 자연어 총평 생성 (14주차 신규).

설계 원칙:
  - **세션 종료에만** 적용. 실시간 per-frame 피드백엔 쓰지 않는다(지연·비용).
  - **통계 근거(grounding)**: end_session() 이 계산한 수치(운동·세트·이슈 통계)만
    전달하고, 그 안에서만 말하도록 제약 → 검출 안 된 자세 조언 할루시네이션 방지.
  - **graceful degradation**: API 키 없음 / SDK 미설치 / 호출 실패·타임아웃 → None 반환.
    호출자는 None 이면 기존 템플릿 assessment 를 그대로 쓴다(세션 종료가 절대 안 깨짐).

환경 변수:
  GEMINI_API_KEY (또는 GOOGLE_API_KEY)  — 없으면 기능 비활성(None 반환)
  GEMINI_MODEL                          — 기본 "gemini-2.5-flash"
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("ai_summary")

# 운동명 한국어 라벨 (요약 통계 가독용). session_state 와 동일 출처를 재사용.
try:
    from session_state import _EXERCISE_LABEL_KO as _LABELS
except Exception:  # pragma: no cover - 방어적
    _LABELS = {}

_DEFAULT_MODEL = "gemini-2.5-flash"

_SYSTEM_INSTRUCTION = (
    "너는 친근한 운동 코치다. 아래에 주어진 운동 통계 수치만 근거로, "
    "한국어로 따뜻하고 격려하는 운동 총평을 작성한다. "
    "규칙: (1) 주어진 수치·이슈에 없는 운동 조언이나 사실을 절대 지어내지 마라. "
    "(2) 잘한 점과 가장 개선할 점을 한 가지씩 짚어라. "
    "(3) 3~4문장, 군더더기 없이. (4) 이모지·마크다운 없이 평범한 문장으로."
)


def _api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _build_prompt(summary: dict) -> str:
    """end_session() 결과 → LLM 에 넘길 한국어 통계 블록."""
    exercises = summary.get("exercises", {})
    lines = ["[운동 세션 통계]"]
    for ex, e in exercises.items():
        label = _LABELS.get(ex, ex)
        total = e.get("totalReps", 0)
        clean = e.get("cleanReps", 0)
        sets  = e.get("totalSets", 0)
        head = f"- {label}: {sets}세트, 총 {total}회 (깔끔 {clean}회)"
        issues = e.get("issuesDetail", [])
        if issues:
            top = ", ".join(f"{d['message']} {d['count']}회" for d in issues[:3])
            head += f" / 자주 본 문제: {top}"
        else:
            head += " / 자세 문제 없음"
        lines.append(head)
    lines.append("")
    lines.append("위 통계만 근거로 운동 총평을 작성해줘.")
    return "\n".join(lines)


def generate_session_narrative(summary: dict, *, max_output_tokens: int = 600) -> Optional[str]:
    """세션 요약 dict → Gemini 자연어 총평. 실패 시 None(호출자가 템플릿 폴백).

    동기 함수(네트워크 I/O). 호출자가 asyncio.to_thread + wait_for 로 감싸 타임아웃을 건다.
    """
    key = _api_key()
    if not key:
        return None  # 키 없음 → 기능 비활성
    if not summary.get("exercises"):
        return None  # 완료된 운동 없음 → LLM 호출 불필요

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.info("google-genai 미설치 — AI 요약 비활성, 템플릿 폴백")
        return None

    try:
        client = genai.Client(api_key=key)
        model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
        # gemini-2.5-flash 는 thinking 모델 — 짧은 총평엔 사고 과정이 불필요하고
        # thinking 토큰이 출력 예산을 먹어 응답이 잘리므로 thinking_budget=0 으로 끈다.
        cfg = types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.7,
            max_output_tokens=max_output_tokens,
        )
        try:
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass  # thinking 미지원 모델/SDK 면 무시
        resp = client.models.generate_content(
            model=model, contents=_build_prompt(summary), config=cfg,
        )
        text = (resp.text or "").strip()
        return text or None
    except Exception as e:  # API 오류·네트워크·차단 등 모두 폴백
        logger.warning("Gemini 요약 생성 실패 → 템플릿 폴백: %s", e)
        return None
