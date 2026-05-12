"""
운동 자세 피드백 메시지 (한국어).

키 명명 규칙:
  - 운동별 이슈:  "<exercise>.<issue_key>"  (예: "squat.left_knee_forward")
  - 공통 키:       prefix 없음              (예: "person_not_detected")

모바일 오버레이에 표시되므로 짧은 문구로 유지한다. 이슈가 여러 개면
analyze_pose 가 " | " 로 이어 붙이므로 한 문구는 더 짧을수록 좋다.
향후 다국어 지원이 필요해지면 MESSAGES_KO / MESSAGES_EN 두 dict로 분리한다.
"""

MESSAGES = {
    # ───── Squat ─────
    "squat.left_knee_forward":  "왼쪽 무릎이 발끝을 넘었어요",
    "squat.right_knee_forward": "오른쪽 무릎이 발끝을 넘었어요",
    "squat.trunk_lean":         "상체를 펴세요",
    "squat.knee_asymmetry":     "양쪽 균형을 맞추세요",
    "squat.good_form":          "좋은 자세예요",
    "squat.standby":            "준비 자세를 잡으세요",

    # ───── Push-up ─────
    "pushup.elbow_flare":  "팔꿈치를 몸통에 붙이세요",
    "pushup.hip_sag":      "엉덩이가 처졌어요",
    "pushup.hip_pike":     "엉덩이가 솟았어요",
    "pushup.camera_angle": "측면에서 촬영하세요",
    "pushup.good_form":    "좋은 자세예요",
    "pushup.standby":      "준비 자세를 잡으세요",

    # ───── Lunge (11주차) ─────
    # 분석기 emit 중인 키
    "lunge.front_knee_forward":  "앞 무릎이 발끝을 넘었어요",
    "lunge.trunk_lean":          "상체를 펴세요",
    "lunge.unknown_front_leg":   "측면에서 다리를 앞뒤로 벌리세요",
    "lunge.good_form":           "좋은 자세예요",
    "lunge.standby":             "준비 자세를 잡으세요",
    # LungeAnalyzer 차기 확장용 예약 키 (현재 emit되지 않음)
    "lunge.front_knee_inward":   "앞 무릎이 안쪽으로 모여요",
    "lunge.back_knee_high":      "뒷무릎을 더 내리세요",
    "lunge.hip_drop":            "골반을 수평으로 유지하세요",
    "lunge.front_foot_lift":     "앞발 뒤꿈치가 들렸어요",
    "lunge.knee_asymmetry":      "양쪽 균형을 맞추세요",

    # ───── 공통 ─────
    "person_not_detected":  "사람이 보이지 않아요",
    "inference_failed":     "자세 분석에 실패했어요. 잠시 후 다시 시도하세요",
    "unsupported_exercise": "지원하지 않는 운동이에요",
}


# 세트(운동 세션) 종료 시 보여줄 상세 코칭 팁.
# 실시간 오버레이는 MESSAGES(짧은 문구), 종료 요약은 아래 COACHING_TIPS(자세한 설명)를 쓴다.
# 키는 이슈 full key("<exercise>.<issue>") — good_form / standby / 공통 키는 이슈가 아니므로 없음.
COACHING_TIPS = {
    # ───── Squat ─────
    "squat.left_knee_forward":  "내려갈 때 엉덩이를 먼저 뒤로 빼고 체중을 발 뒤꿈치에 두세요. 무릎이 발끝을 넘으면 무릎에 부담이 갑니다.",
    "squat.right_knee_forward": "내려갈 때 엉덩이를 먼저 뒤로 빼고 체중을 발 뒤꿈치에 두세요. 무릎이 발끝을 넘으면 무릎에 부담이 갑니다.",
    "squat.trunk_lean":         "가슴을 들고 시선을 정면에 두세요. 코어에 힘을 주면 등이 굽거나 상체가 과하게 숙여지는 걸 막을 수 있습니다.",
    "squat.knee_asymmetry":     "양쪽 다리에 체중을 고르게 싣고 같은 깊이로 천천히 내려가세요. 한쪽으로 치우치면 한쪽 무릎·고관절에 무리가 갑니다.",
    # ───── Push-up ─────
    "pushup.elbow_flare":  "팔꿈치를 몸통과 약 45도로 유지하세요. 어깨와 일직선이 될 만큼 벌어지면 어깨 부상 위험이 커집니다.",
    "pushup.hip_sag":      "복부와 엉덩이에 힘을 주어 머리-엉덩이-발끝이 일직선이 되게 하세요. 허리가 아래로 꺾이면 요추에 부담이 갑니다.",
    "pushup.hip_pike":     "엉덩이를 너무 들어 올리지 말고 몸 전체를 일직선으로 낮추세요. 시선은 바닥에서 약간 앞쪽을 보면 정렬이 쉽습니다.",
    "pushup.camera_angle": "정면 촬영은 엉덩이 정렬 분석이 부정확합니다. 카메라를 옆에 두고 전신 측면이 보이도록 촬영해 주세요.",
    # ───── Lunge ─────
    "lunge.front_knee_forward":  "보폭을 조금 넓히고 뒷무릎을 바닥쪽으로 곧게 내리세요. 앞다리 무릎이 발끝을 넘으면 무릎에 무리가 갑니다.",
    "lunge.trunk_lean":          "상체를 세우고 코어에 힘을 주세요. 앞으로 숙이면 균형이 무너지고 앞무릎 부담이 커집니다.",
    "lunge.unknown_front_leg":   "카메라를 옆에 두고, 한 다리는 앞·한 다리는 뒤로 확실히 벌린 자세가 측면에서 보이도록 촬영해 주세요.",
    "lunge.front_knee_inward":   "앞다리 무릎이 안쪽으로 무너지지 않게, 무릎이 두 번째 발가락 방향을 향하도록 바깥으로 밀어내세요.",
    "lunge.back_knee_high":      "뒷무릎이 바닥에 거의 닿을 만큼 깊게 내려가야 가동 범위가 충분합니다. 너무 얕으면 운동 효과가 떨어집니다.",
    "lunge.hip_drop":            "골반이 한쪽으로 기울지 않게 양쪽 엉덩이 높이를 맞추고 코어로 중심을 잡으세요.",
    "lunge.front_foot_lift":     "앞발 뒤꿈치가 들리지 않게 발바닥 전체로 바닥을 누르며 일어나세요. 뒤꿈치가 들리면 추진력이 약해집니다.",
    "lunge.knee_asymmetry":      "좌우 반복의 깊이가 다릅니다. 보폭을 일정하게 하고 거울이나 영상으로 양쪽을 비교해 보세요.",
}


def get(key: str, default: str = "") -> str:
    """메시지 키로 한국어 문구를 조회한다. 없으면 default 반환."""
    return MESSAGES.get(key, default)


def tip(key: str, default: str = "") -> str:
    """이슈 full key 로 상세 코칭 팁을 조회한다. 없으면 default 반환."""
    return COACHING_TIPS.get(key, default)
