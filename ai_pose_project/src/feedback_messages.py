"""
운동 자세 피드백 메시지 (한국어).

키 명명 규칙:
  - 운동별 이슈:  "<exercise>.<issue_key>"  (예: "squat.left_knee_forward")
  - 공통 키:       prefix 없음              (예: "person_not_detected")

향후 다국어 지원이 필요해지면 MESSAGES_KO / MESSAGES_EN 두 dict로 분리한다.
"""

MESSAGES = {
    # ───── Squat ─────
    "squat.left_knee_forward":  "왼쪽 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요.",
    "squat.right_knee_forward": "오른쪽 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요.",
    "squat.trunk_lean":         "상체가 너무 숙여졌습니다. 가슴을 들고 등을 곧게 유지하세요.",
    "squat.knee_asymmetry":     "양쪽 무릎의 깊이가 다릅니다. 균형을 맞추세요.",
    "squat.good_form":          "좋은 스쿼트 자세입니다.",
    "squat.standby":            "준비 자세를 잡아주세요.",

    # ───── Push-up ─────
    "pushup.elbow_flare":  "팔꿈치가 너무 벌어졌습니다. 몸통 가까이 붙이세요.",
    "pushup.hip_sag":      "엉덩이가 처졌습니다. 코어에 힘을 주고 일직선을 유지하세요.",
    "pushup.hip_pike":     "엉덩이가 솟았습니다. 등에서 발끝까지 일직선을 유지하세요.",
    "pushup.camera_angle": "측면에서 촬영해주세요.",
    "pushup.good_form":    "좋은 푸시업 자세입니다.",
    "pushup.standby":      "푸시업 준비 자세를 잡아주세요.",

    # ───── Lunge (11주차) ─────
    # 분석기 emit 중인 키
    "lunge.front_knee_forward":  "앞다리 무릎이 발끝보다 앞으로 나갔습니다. 무릎을 발목 위로 정렬하세요.",
    "lunge.trunk_lean":          "상체가 너무 숙여졌습니다. 가슴을 들고 등을 곧게 유지하세요.",
    "lunge.unknown_front_leg":   "앞다리를 식별할 수 없습니다. 측면에서 다리를 앞뒤로 벌려주세요.",
    "lunge.good_form":           "좋은 런지 자세입니다.",
    "lunge.standby":             "런지 준비 자세를 잡아주세요.",
    # LungeAnalyzer 차기 확장용 예약 키 (현재 emit되지 않음)
    "lunge.front_knee_inward":   "앞다리 무릎이 안쪽으로 모입니다. 무릎과 발끝이 같은 방향을 향하도록 정렬하세요.",
    "lunge.back_knee_high":      "뒷무릎이 충분히 내려가지 않았습니다. 더 깊게 내려가 자세를 안정시키세요.",
    "lunge.hip_drop":            "골반이 한쪽으로 기울었습니다. 양쪽 골반을 수평으로 유지하세요.",
    "lunge.front_foot_lift":     "앞발 뒤꿈치가 들렸습니다. 발바닥 전체로 바닥을 디디세요.",
    "lunge.knee_asymmetry":      "양쪽 무릎의 깊이가 다릅니다. 보폭과 균형을 다시 잡으세요.",

    # ───── 공통 ─────
    "person_not_detected":  "사람이 감지되지 않았습니다.",
    "inference_failed":     "자세 분석에 실패했습니다. 잠시 후 다시 시도해주세요.",
    "unsupported_exercise": "지원하지 않는 운동입니다.",
}


def get(key: str, default: str = "") -> str:
    """메시지 키로 한국어 문구를 조회한다. 없으면 default 반환."""
    return MESSAGES.get(key, default)
