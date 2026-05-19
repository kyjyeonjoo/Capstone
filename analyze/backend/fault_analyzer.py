"""
fault_analyzer.py
─────────────────────────────────────────────────────────────
규칙 기반 과실비율 판단 엔진 (외부 API 없음)

ilike 한글 문제를 우회하기 위해
accident_type 전체를 가져와서 Python에서 직접 키워드 매칭.
"""

import os
from typing import Optional, List, Tuple, Dict
from supabase import create_client, Client


# ──────────────────────────────────────────────────────────
# 클라이언트 초기화
# ──────────────────────────────────────────────────────────

def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수 없음")
    return create_client(url, key)


# ──────────────────────────────────────────────────────────
# Step 1. object_detection / tracking 저장
# ──────────────────────────────────────────────────────────

def save_detections(supabase: Client, video_id: int, records: List[Dict]):
    if not records:
        return

    detection_rows = []
    for rec in records:
        detection_rows.append({
            "video_id":    video_id,
            "frame_no":    rec.get("frame", 0),
            "timestamp":   round(rec.get("frame", 0) / 5.0, 3),
            "object_type": rec.get("object_type", ""),
            "confidence":  rec.get("confidence", 0.0),
            "bbox_x1":     rec.get("bbox_x1", 0),
            "bbox_y1":     rec.get("bbox_y1", 0),
            "bbox_x2":     rec.get("bbox_x2", 0),
            "bbox_y2":     rec.get("bbox_y2", 0),
        })

    det_res  = supabase.table("object_detection").insert(detection_rows).execute()
    inserted = det_res.data or []

    tracking_rows = []
    for i, det in enumerate(inserted):
        rec = records[i]
        cx  = (rec.get("bbox_x1", 0) + rec.get("bbox_x2", 0)) / 2
        cy  = (rec.get("bbox_y1", 0) + rec.get("bbox_y2", 0)) / 2
        tracking_rows.append({
            "video_id":     video_id,
            "detection_id": det["detection_id"],
            "track_id":     rec.get("track_id", 0),
            "frame_no":     rec.get("frame", 0),
            "center_x":     round(cx, 2),
            "center_y":     round(cy, 2),
            "speed":        None,
            "direction":    None,
        })

    if tracking_rows:
        supabase.table("tracking").insert(tracking_rows).execute()

    print(f"[DB] object_detection {len(detection_rows)}건, tracking {len(tracking_rows)}건 저장 완료")


# ──────────────────────────────────────────────────────────
# Step 2. EVENT 판단 및 저장
# ──────────────────────────────────────────────────────────

EVENT_KEYWORD_MAP = {
    "신호":   ("신호위반",    "HIGH"),
    "중앙":   ("중앙선침범",  "HIGH"),
    "진로":   ("진로변경",    "MEDIUM"),
    "안전모": ("안전모미착용", "MEDIUM"),
    "과속":   ("과속",       "HIGH"),
    "보행자": ("보행자위협",  "HIGH"),
}

def detect_events(supabase: Client, video_id: int, records: List[Dict]) -> List[str]:
    seen_events: Dict[str, Dict] = {}

    for rec in records:
        obj_type = rec.get("object_type", "")
        for keyword, (event_type, severity) in EVENT_KEYWORD_MAP.items():
            if keyword in obj_type and event_type not in seen_events:
                seen_events[event_type] = {
                    "video_id":    video_id,
                    "event_type":  event_type,
                    "event_time":  round(rec.get("frame", 0) / 5.0, 3),
                    "severity":    severity,
                    "description": (
                        f"{obj_type} 감지 "
                        f"(프레임 {rec.get('frame', 0)}, "
                        f"신뢰도 {rec.get('confidence', 0):.2f})"
                    ),
                }

    if seen_events:
        supabase.table("event").insert(list(seen_events.values())).execute()
        print(f"[DB] event {len(seen_events)}건 저장: {list(seen_events.keys())}")

    return list(seen_events.keys())


# ──────────────────────────────────────────────────────────
# Step 3. accident_type 매칭 (Python 직접 매칭)
# ──────────────────────────────────────────────────────────

# 이벤트 → description/accident_name 검색 키워드 목록
EVENT_TO_KEYWORDS = {
    "신호위반":    ["신호기", "신호등", "신호위반", "적색", "녹색신호", "신호에"],
    "중앙선침범":  ["중앙선", "중앙분리"],
    "진로변경":    ["차선변경", "진로변경", "끼어들기", "앞지르기"],
    "안전모미착용": ["이륜차", "오토바이", "안전모"],
    "과속":       ["과속", "속도위반", "제한속도"],
    "보행자위협":  ["보행자", "횡단보도"],
}

PRIORITY_ORDER = ["신호위반", "중앙선침범", "과속", "보행자위협", "진로변경", "안전모미착용"]

def match_accident_type(supabase: Client, event_types: List[str]) -> Optional[Dict]:
    """
    accident_type 전체를 가져와서 Python에서 직접 키워드 매칭.
    """
    # 전체 데이터 가져오기 (최대 1000건)
    res = supabase.table("accident_type").select("*").limit(1000).execute()
    all_types = res.data or []

    if not all_types:
        print("[매칭] accident_type 테이블이 비어있음")
        return None

    if not event_types:
        print(f"[매칭] 이벤트 없음 → 기본값 사용: {all_types[0]['accident_name']}")
        return all_types[0]

    # 우선순위 순서대로 매칭 시도
    for event in PRIORITY_ORDER:
        if event not in event_types:
            continue

        keywords = EVENT_TO_KEYWORDS.get(event, [])

        for accident in all_types:
            desc = accident.get("description", "") or ""
            name = accident.get("accident_name", "") or ""
            combined = desc + name

            # 키워드 중 하나라도 포함되면 매칭
            if any(kw in combined for kw in keywords):
                print(f"[매칭] '{event}' → {accident['accident_name']} "
                      f"(A:{accident['base_fault_a']}% / B:{accident['base_fault_b']}%)")
                return accident

    # 매칭 실패 시 기본값
    print(f"[매칭] 매칭 실패 → 기본값 사용: {all_types[0]['accident_name']}")
    return all_types[0]


# ──────────────────────────────────────────────────────────
# Step 4. fault_modifier 적용
# ──────────────────────────────────────────────────────────

def apply_fault_modifiers(
    supabase: Client,
    accident_type_id: int,
    event_types: List[str],
    base_fault_a: int,
    base_fault_b: int,
) -> Tuple[int, int, List[str]]:
    res = (supabase.table("fault_modifier")
           .select("*")
           .eq("accident_type_id", accident_type_id)
           .execute())
    modifiers = res.data or []

    applied_desc = []
    fault_a = base_fault_a
    fault_b = base_fault_b

    for mod in modifiers:
        mod_name   = mod.get("modifier_name", "")
        adjustment = mod.get("adjustment_ratio", 0)
        target     = mod.get("target_party", "A")

        matched = any(keyword in mod_name for keyword in event_types)
        if not matched:
            continue

        if target == "A":
            fault_a = min(100, max(0, fault_a + adjustment))
            fault_b = 100 - fault_a
        else:
            fault_b = min(100, max(0, fault_b + adjustment))
            fault_a = 100 - fault_b

        sign = "+" if adjustment > 0 else ""
        applied_desc.append(
            f"{mod_name}: {target}차량 {sign}{adjustment}% ({mod.get('description', '')})"
        )

    print(f"[수정요소] {len(applied_desc)}개 적용 → A:{fault_a}% / B:{fault_b}%")
    return fault_a, fault_b, applied_desc


# ──────────────────────────────────────────────────────────
# Step 5. 결과 생성
# ──────────────────────────────────────────────────────────

LAW_MAP = {
    "신호위반":    "도로교통법 제5조(신호 또는 지시에 따를 의무)",
    "중앙선침범":  "도로교통법 제13조(차마의 통행)",
    "진로변경":    "도로교통법 제19조(안전거리 확보 등)",
    "안전모미착용": "도로교통법 제50조(모든 차의 운전자의 준수사항)",
    "과속":       "도로교통법 제17조(자동차 등의 속도)",
    "보행자위협":  "도로교통법 제27조(보행자의 보호)",
}

def build_result(
    event_types: List[str],
    accident_type: Optional[Dict],
    fault_a: int,
    fault_b: int,
    modifier_desc: List[str],
) -> Dict:
    accident_name = accident_type["accident_name"] if accident_type else "불명확"

    if event_types:
        situation_summary = (
            f"블랙박스 영상 분석 결과 {', '.join(event_types)} 등 "
            f"{len(event_types)}건의 위반 행위가 감지되었습니다. "
            f"사고 유형({accident_name})을 기준으로 과실비율을 산정하였습니다."
        )
        accident_cause = (
            f"영상에서 {', '.join(event_types)}이(가) 감지되었으며 "
            f"이는 사고의 주요 원인으로 판단됩니다. "
            f"A차량의 과실을 {fault_a}%로 산정하였습니다."
        )
        if modifier_desc:
            accident_cause += f" 적용된 수정 요소: {', '.join(modifier_desc)}"
    else:
        situation_summary = (
            f"블랙박스 영상 분석 결과 특이한 위반 행위가 감지되지 않았습니다. "
            f"사고 유형({accident_name}) 기준 기본 과실비율을 적용하였습니다."
        )
        accident_cause = (
            f"명확한 위반 행위가 감지되지 않아 사고 유형({accident_name}) 기준 "
            f"기본 과실비율을 적용하였습니다."
        )

    laws = [LAW_MAP[e] for e in event_types if e in LAW_MAP]
    legal_basis = ", ".join(laws) if laws else "도로교통법 제19조(안전거리 확보 등)"

    if not accident_type:
        confidence = "낮음"
    elif len(event_types) >= 2:
        confidence = "높음"
    elif len(event_types) == 1:
        confidence = "보통"
    else:
        confidence = "낮음"

    return {
        "situation_summary": situation_summary,
        "fault_ratio_a":     fault_a,
        "fault_ratio_b":     fault_b,
        "accident_cause":    accident_cause,
        "legal_basis":       legal_basis,
        "confidence_level":  confidence,
    }


# ──────────────────────────────────────────────────────────
# Step 6. analysis_result 저장
# ──────────────────────────────────────────────────────────

def save_analysis_result(
    supabase: Client,
    video_id: int,
    accident_type_id: Optional[int],
    result: Dict,
) -> Dict:
    payload = {
        "video_id":         video_id,
        "accident_type_id": accident_type_id,
        "summary":          result.get("situation_summary"),
        "accident_cause":   result.get("accident_cause"),
        "fault_a":          result.get("fault_ratio_a"),
        "fault_b":          result.get("fault_ratio_b"),
        "legal_basis":      result.get("legal_basis"),
    }
    res = supabase.table("analysis_result").insert(payload).execute()
    return res.data[0] if res.data else payload


# ──────────────────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────────────────

def analyze_fault(
    video_id: int,
    total_frames: int,
    records: List[Dict],
) -> Dict:
    supabase = get_supabase()

    # 1. object_detection + tracking 저장
    save_detections(supabase, video_id, records)

    # 2. 이벤트 판별 + event 테이블 저장
    event_types = detect_events(supabase, video_id, records)

    # 3. accident_type 매칭 (Python 직접 매칭)
    accident_type    = match_accident_type(supabase, event_types)
    accident_type_id = accident_type["accident_type_id"] if accident_type else None
    base_a           = accident_type["base_fault_a"]      if accident_type else 50
    base_b           = accident_type["base_fault_b"]      if accident_type else 50

    # 4. fault_modifier 적용
    if accident_type_id:
        fault_a, fault_b, modifier_desc = apply_fault_modifiers(
            supabase, accident_type_id, event_types, base_a, base_b
        )
    else:
        fault_a, fault_b, modifier_desc = base_a, base_b, []

    print(f"[판단] 최종 과실비율 → A:{fault_a}% / B:{fault_b}%")

# 5. 결과 생성
    result = build_result(event_types, accident_type, fault_a, fault_b, modifier_desc)

    # 6. case_law 판례 검색
    cases = []
    if accident_type_id:
        try:
            case_res = supabase.table("case_law").select(
                "case_title, case_number, court_name, decision_date, summary, fault_ratio"
            ).eq("accident_type_id", accident_type_id).limit(3).execute()
            cases = case_res.data or []
            print(f"[DB] case_law {len(cases)}건 조회")
        except Exception as e:
            print(f"[DB] case_law 조회 오류: {e}")

    # 7. analysis_result 저장
    saved = save_analysis_result(supabase, video_id, accident_type_id, result)

    return {
        **result,
        "detected_events":    event_types,
        "accident_type_name": accident_type["accident_name"] if accident_type else "불명확",
        "result_id":          saved.get("result_id"),
        "case_laws":          cases,
    }