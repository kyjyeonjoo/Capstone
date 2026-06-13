"""Build user-facing fault-analysis explanations from detected evidence."""

from typing import Dict, List, Optional


EVIDENCE_TEXT_MAP = {
    "안전거리미확보추돌위험": "선행 차량이 같은 차로 중앙에서 급격히 확대되고 충돌 예상 시간이 짧아진 조건",
    "신호위반충돌위험": "적색 신호, 정지선 부근 차량 통과 및 차량 간 접근 조건",
    "신호위반": "적색 신호와 정지선 부근 차량 통과 조건",
    "중앙선침범": "차량 중심 궤적이 검출된 중앙선 양쪽을 통과한 조건",
    "노외진입": "도로 측면 또는 주차 위치의 차량이 본선 진행 경로로 접근한 궤적",
    "좌회전": "교차로 표식 주변에서 차량 진행각이 기준 이상 변한 조건",
    "교차로진입": (
        "횡단보도·정지선이 반복 검출된 구간에서 측면 차량이 진행 경로를 "
        "가로질러 접근한 조건"
    ),
    "진로변경": (
        "사고 관련 후보 차량이 측면 차로에서 블랙박스 진행 경로 방향으로 "
        "이동·확대된 조건"
    ),
    "과속": "영상 보정값을 적용한 추정 속도가 기준을 초과한 조건",
    "충돌위험": "차량 박스 확대와 상호 접근 속도에 따른 충돌 위험 조건",
    "측면합류충돌위험": "측면 차량이 화면 중앙 방향으로 접근·확대된 궤적",
    "주차장출차충돌위험": (
        "도로 표식이 없는 저속 공간에서 측면 차량이 통행 경로로 접근한 궤적"
    ),
    "회전교차로진입": "배경의 곡선 회전 이동 중 측면 차량이 회전 경로로 진입한 조건",
    "회전교차로대진입": "측면 차량이 외곽 차로를 지나 내부 회전 경로까지 크게 진입한 조건",
    "회전교차로진출입충돌": "회전차의 진출 경로와 진입차의 이동 경로가 교차한 조건",
    "회전교차로진로변경": "회전 중 진출을 위한 차로 변경 차량이 인접 차량에 접근한 조건",
    "회전교차로동시진입": "인접 차로의 두 차량이 함께 회전교차로로 진입한 조건",
    "교차로통행충돌상황": "교차로 표식 주변에서 사고 관련 차량의 진행 경로가 근접한 조건",
    "교차로강한진입충돌상황": "교차로 표식 주변에서 상대 차량이 주행 경로 안쪽까지 크게 진입한 조건",
    "회전교차로주행충돌상황": "곡선형 도로에서 사고 관련 차량의 진행 경로가 근접한 조건",
    "측면접근충돌상황": "사고 관련 차량이 화면 측면 방향에서 주행 경로로 접근한 조건",
    "측면강한진입충돌상황": "상대 차량이 화면 측면에서 주행 경로 안쪽까지 크게 진입한 조건",
    "전방차량근접상황": "전방 차량의 박스 크기 또는 화면 하단 위치가 증가한 조건",
    "차량간충돌상황": "사고 관련 차량 궤적은 확인했으나 구체적 진행 유형을 구분하지 못한 조건",
}


def build_fault_result(
    event_types: List[str],
    accident_type: Optional[Dict],
    fault_a: int,
    fault_b: int,
    modifier_desc: List[str],
    law_map: Dict[str, str],
    violation_map: Optional[Dict[str, List[int]]] = None,
    internal_event_types: Optional[List[str]] = None,
) -> Dict:
    violation_map = violation_map or {}
    evidence_events = internal_event_types or event_types

    if accident_type:
        accident_name = accident_type.get("accident_name", "사고 유형 미상")
        base_a = accident_type.get("base_fault_a", 50)
        base_b = accident_type.get("base_fault_b", 50)
    else:
        accident_name = "사고 유형 미확정"
        base_a, base_b = 50, 50

    evidence_parts: List[str] = []
    mapped_track_ids = set()
    for event in evidence_events:
        evidence_text = EVIDENCE_TEXT_MAP.get(event)
        if not evidence_text:
            continue

        track_ids = sorted(
            {
                track_id
                for track_id in violation_map.get(event, [])
                if track_id is not None
            }
        )
        mapped_track_ids.update(track_ids)
        track_text = (
            f" (관련 차량 추적 ID: {', '.join(map(str, track_ids))})"
            if track_ids
            else ""
        )
        evidence_parts.append(f"{evidence_text}{track_text}")

    if evidence_parts:
        displayed_events = ", ".join(event_types)
        situation_summary = (
            f"영상에서 {displayed_events} 관련 조건이 감지되었습니다. "
            f"규칙 및 사고유형 DB에서는 '{accident_name}' 후보와 비교했으며, "
            f"기본 과실비율은 A {base_a}% : B {base_b}%입니다."
        )
    else:
        situation_summary = (
            "영상에서 과실 주체를 특정할 만큼 신뢰할 수 있는 위반 이벤트를 "
            f"검출하지 못했습니다. '{accident_name}'의 기본 과실비율 "
            f"A {base_a}% : B {base_b}%를 참고값으로 사용했습니다."
        )

    cause_parts: List[str] = []
    if evidence_parts:
        cause_parts.append("영상 판단 근거: " + "; ".join(evidence_parts) + ".")
    else:
        cause_parts.append(
            "차량 및 도로 객체는 분석했지만 특정 차량의 법규 위반을 확정하지 "
            "못했습니다."
        )

    if modifier_desc:
        cause_parts.append("과실 계산 적용요소: " + ", ".join(modifier_desc) + ".")
    else:
        cause_parts.append(
            "별도의 가감 요소 없이 사고유형 기본값과 감지 이벤트 규칙을 적용했습니다."
        )

    cause_parts.append(f"계산 결과는 A {fault_a}% : B {fault_b}%입니다.")
    if mapped_track_ids:
        cause_parts.append(
            "표시된 추적 ID는 화면에 검출된 외부 차량 기준이며, 블랙박스 차량은 "
            "객체로 검출되지 않으므로 A/B 연결은 사고유형 DB와 영상 내 역할 추정에 "
            "의존합니다."
        )
    cause_parts.append(
        "본 결과는 영상에서 확인된 사고 상황을 알고리즘으로 분석한 예측값으로, "
        "실제 과실비율과 차이가 있을 수 있으며 사고 상황을 해석하는 관점에 따라 "
        "판단 결과가 달라질 수 있습니다."
    )

    legal_basis_list = []
    for event in evidence_events:
        law = law_map.get(event)
        if law and law not in legal_basis_list:
            legal_basis_list.append(law)
    legal_basis = (
        " / ".join(legal_basis_list)
        if legal_basis_list
        else "구체적 법규 위반 유형 미확정 - 원본 영상 및 사고자료 추가 확인 필요"
    )

    concrete_events = {event for event in evidence_events if event != "충돌위험"}
    if accident_type and len(concrete_events) >= 2 and mapped_track_ids:
        confidence = "높음"
    elif evidence_parts or accident_type:
        confidence = "보통"
    else:
        confidence = "낮음"

    return {
        "situation_summary": situation_summary,
        "fault_ratio_a": fault_a,
        "fault_ratio_b": fault_b,
        "accident_cause": " ".join(cause_parts),
        "legal_basis": legal_basis,
        "confidence_level": confidence,
    }
