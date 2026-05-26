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

def check_overlap(rec1, rec2):
    xA = max(rec1.get("bbox_x1", 0), rec2.get("bbox_x1", 0))
    yA = max(rec1.get("bbox_y1", 0), rec2.get("bbox_y1", 0))
    xB = min(rec1.get("bbox_x2", 0), rec2.get("bbox_x2", 0))
    yB = min(rec1.get("bbox_y2", 0), rec2.get("bbox_y2", 0))
    interArea = max(0, xB - xA) * max(0, yB - yA)
    return interArea > 0

def get_bbox_center(rec):
    x1 = rec.get("bbox_x1", 0)
    y1 = rec.get("bbox_y1", 0)
    x2 = rec.get("bbox_x2", 0)
    y2 = rec.get("bbox_y2", 0)
    return (x1 + x2) / 2, (y1 + y2) / 2

def get_bbox_distance(rec1, rec2):
    c1_x, c1_y = get_bbox_center(rec1)
    c2_x, c2_y = get_bbox_center(rec2)
    return ((c1_x - c2_x)**2 + (c1_y - c2_y)**2)**0.5

def get_base_type(obj_type: str) -> str:
    """
    "[신호] car" 같은 모델별 접두사를 제거하여 레거시 판단 로직과의 하위 호환성을 확보합니다.
    """
    if obj_type.startswith("[") and "]" in obj_type:
        return obj_type.split("]", 1)[1].strip()
    return obj_type

def detect_events(supabase: Client, video_id: int, records: List[Dict]) -> Tuple[List[str], Dict[str, List[int]]]:
    """
    이벤트 감지 후 두 가지를 반환:
      - event_types: 감지된 이벤트 이름 목록
      - violation_map: {event_type: [위반 track_id, ...]} — 어떤 차량이 어떤 위반을 했는지
    """
    seen_events: Dict[str, Dict] = {}
    # 위반 차량 track_id 추적 맵 (event_type → set of track_ids)
    violation_track_map: Dict[str, set] = {}

    def _record_violator(event_type: str, track_id):
        if track_id is not None:
            violation_track_map.setdefault(event_type, set()).add(track_id)

    # 1. 프레임별로 객체 그룹화
    from collections import defaultdict
    frames_data = defaultdict(list)
    for rec in records:
        frames_data[rec.get("frame", 0)].append(rec)

    # 신호위반을 한 차량의 track_id 추적
    red_light_violators = set()
    
    # 모든 프레임을 돌면서 규칙 기반 기하학적 상황 판단
    for frame_no, frame_objs in sorted(frames_data.items()):
        # 객체 타입별 분류 (접두사가 붙은 객체명도 안전하게 처리)
        red_lights = [o for o in frame_objs if get_base_type(o.get("object_type")) == "red"]
        stoplines = [o for o in frame_objs if get_base_type(o.get("object_type")) in ("stopline", "corner_stopline")]
        vehicles = [o for o in frame_objs if get_base_type(o.get("object_type")) in ("car", "bus", "truck", "motorcycle")]
        yellowlines = [o for o in frame_objs if get_base_type(o.get("object_type")) == "yellowline"]
        crosswalks = [o for o in frame_objs if get_base_type(o.get("object_type")) == "crosswalk"]
        pedestrians = [o for o in frame_objs if get_base_type(o.get("object_type")) == "pedestrian"]
        whitelines = [o for o in frame_objs if get_base_type(o.get("object_type")) == "white_line"]
        no_helmets = [o for o in frame_objs if get_base_type(o.get("object_type")) in ("no_helmet", "no_helmet_motorcycle")]
        
        # ── (1) 신호위반 감지 ──
        # 적색 신호가 켜져 있고 정지선이 감지된 프레임에서 차량이 정지선 위로 지나가거나 이미 넘어간 경우
        if len(red_lights) > 0 and len(stoplines) > 0:
            for v in vehicles:
                v_track_id = v.get("track_id")
                for s in stoplines:
                    # 차량의 하단 Y좌표가 정지선 Y좌표보다 작아지거나 (화면 위쪽 전진)
                    # 정지선과 바운딩 박스가 겹친 상태일 때
                    if v.get("bbox_y2", 0) < s.get("bbox_y1", 0) or check_overlap(v, s):
                        red_light_violators.add(v_track_id)
                        _record_violator("신호위반", v_track_id)
                        if "신호위반" not in seen_events:
                            seen_events["신호위반"] = {
                                "video_id": video_id,
                                "event_type": "신호위반",
                                "event_time": round(frame_no / 5.0, 3),
                                "severity": "HIGH",
                                "description": f"적색 신호 중 차량(ID:{v_track_id}) 정지선 침범 및 통과 감지 (프레임 {frame_no})"
                            }

        # ── (2) 신호위반 교차로 충돌 위험 감지 ──
        # 신호위반한 차량이 존재하고, 다른 차량들과 매우 가까운 거리에 접근했을 때
        if len(vehicles) >= 2:
            for i in range(len(vehicles)):
                for j in range(i + 1, len(vehicles)):
                    v1 = vehicles[i]
                    v2 = vehicles[j]
                    
                    t1 = v1.get("track_id")
                    t2 = v2.get("track_id")
                    
                    # 둘 중 하나가 신호위반차량인 경우
                    if t1 in red_light_violators or t2 in red_light_violators:
                        dist = get_bbox_distance(v1, v2)
                        # 두 차량의 바운딩 박스 중심 거리가 180 픽셀 이하로 극도로 좁혀지거나 겹칠 때
                        if dist < 180.0 or check_overlap(v1, v2):
                            violator_id = t1 if t1 in red_light_violators else t2
                            normal_id = t2 if t1 in red_light_violators else t1
                            
                            _record_violator("신호위반충돌위험", violator_id)
                            if "신호위반충돌위험" not in seen_events:
                                seen_events["신호위반충돌위험"] = {
                                    "video_id": video_id,
                                    "event_type": "신호위반충돌위험",
                                    "event_time": round(frame_no / 5.0, 3),
                                    "severity": "HIGH",
                                    "description": f"적색 신호위반 차량(ID:{violator_id})과 타 차량(ID:{normal_id}) 간의 교차로 내 충돌 위험 감지 (거리 {dist:.1f}px, 프레임 {frame_no})"
                                }

        # ── (3) 중앙선 침범 감지 ──
        if len(yellowlines) > 0:
            for v in vehicles:
                v_track_id = v.get("track_id")
                for y in yellowlines:
                    # 차량이 중앙선과 겹쳐서 지나갈 때
                    if check_overlap(v, y):
                        _record_violator("중앙선침범", v_track_id)
                        if "중앙선침범" not in seen_events:
                            seen_events["중앙선침범"] = {
                                "video_id": video_id,
                                "event_type": "중앙선침범",
                                "event_time": round(frame_no / 5.0, 3),
                                "severity": "HIGH",
                                "description": f"차량(ID:{v_track_id})이 중앙선(황색선)을 침범하여 주행함 감지 (프레임 {frame_no})"
                            }

        # ── (4) 보행자 위협 (보행자 보호의무 위반) 감지 ──
        if len(pedestrians) > 0 and len(crosswalks) > 0:
            for p in pedestrians:
                # 보행자가 횡단보도와 오버랩되어 횡단 중일 때
                is_crossing = False
                for c in crosswalks:
                    if check_overlap(p, c):
                        is_crossing = True
                        break
                        
                if is_crossing:
                    # 횡단보도를 건너는 보행자가 있을 때, 차량이 횡단보도를 침범하거나 보행자와 가까워지는 경우
                    for v in vehicles:
                        v_track_id = v.get("track_id")
                        dist = get_bbox_distance(p, v)
                        # 보행자와 차량 거리가 150 픽셀 이하로 좁혀지거나 횡단보도 오버랩 발생 시
                        if dist < 150.0 or any(check_overlap(v, c) for c in crosswalks):
                            _record_violator("보행자위협", v_track_id)
                            if "보행자위협" not in seen_events:
                                seen_events["보행자위협"] = {
                                    "video_id": video_id,
                                    "event_type": "보행자위협",
                                    "event_time": round(frame_no / 5.0, 3),
                                    "severity": "HIGH",
                                    "description": f"횡단보도 내 보행자 횡단 중 차량(ID:{v_track_id})이 접근하여 위협함 감지 (거리 {dist:.1f}px, 프레임 {frame_no})"
                                }

        # ── (5) 진로변경 감지 ──
        if len(whitelines) > 0:
            for v in vehicles:
                v_track_id = v.get("track_id")
                for w in whitelines:
                    # 차량이 백색 차선과 겹치는 경우
                    if check_overlap(v, w):
                        _record_violator("진로변경", v_track_id)
                        if "진로변경" not in seen_events:
                            seen_events["진로변경"] = {
                                "video_id": video_id,
                                "event_type": "진로변경",
                                "event_time": round(frame_no / 5.0, 3),
                                "severity": "NORMAL",
                                "description": f"차량(ID:{v_track_id})이 차선(백색선)을 침범하여 주행함 감지 (프레임 {frame_no})"
                            }

        # ── (6) 안전모 미착용 감지 ──
        if len(no_helmets) > 0:
            for nh in no_helmets:
                motorcycles = [o for o in frame_objs if get_base_type(o.get("object_type")) == "motorcycle"]
                target_motorcycle_id = "이륜차"
                if motorcycles:
                    min_dist = float('inf')
                    for mc in motorcycles:
                        dist = get_bbox_distance(nh, mc)
                        if dist < min_dist:
                            min_dist = dist
                            target_motorcycle_id = f"이륜차 ID:{mc.get('track_id')}"
                
                if "안전모미착용" not in seen_events:
                    seen_events["안전모미착용"] = {
                        "video_id": video_id,
                        "event_type": "안전모미착용",
                        "event_time": round(frame_no / 5.0, 3),
                        "severity": "NORMAL",
                        "description": f"안전모 미착용 탑승자({target_motorcycle_id}) 감지 (프레임 {frame_no})"
                    }

    # ── (7) 과속 감지 (전체 프레임 데이터 분석) ──
    from collections import defaultdict
    track_positions = defaultdict(list)
    for rec in records:
        v_type = get_base_type(rec.get("object_type"))
        if v_type in ("car", "bus", "truck", "motorcycle"):
            track_id = rec.get("track_id")
            if track_id:
                cx, cy = get_bbox_center(rec)
                track_positions[track_id].append((rec.get("frame", 0), cx, cy))

    for track_id, pos_list in track_positions.items():
        if len(pos_list) < 5:  # 최소 5프레임 이상 관찰되어야 속도 추정 신뢰성 확보
            continue
        
        pos_list.sort(key=lambda x: x[0])
        speeds = []
        for k in range(len(pos_list) - 1):
            f1, x1, y1 = pos_list[k]
            f2, x2, y2 = pos_list[k+1]
            dt = (f2 - f1) / 5.0  # 5 FPS
            if dt > 0:
                dist = ((x2 - x1)**2 + (y2 - y1)**2)**0.5
                speed_px = dist / dt
                speed_kmh = speed_px * 0.25  # 320 px/s = 80 km/h 기준 변환율
                speeds.append((f2, speed_kmh))
        
        if speeds:
            max_frame, max_speed_kmh = max(speeds, key=lambda x: x[1])
            if max_speed_kmh > 80.0:
                _record_violator("과속", track_id)
                if "과속" not in seen_events:
                    seen_events["과속"] = {
                        "video_id": video_id,
                        "event_type": "과속",
                        "event_time": round(max_frame / 5.0, 3),
                        "severity": "NORMAL",
                        "description": f"차량(ID:{track_id})이 제한 속도(80km/h)를 초과하여 과속 주행함 감지 (추정 속도: {max_speed_kmh:.1f}km/h, 프레임 {max_frame})"
                    }

    # DB 저장 (DB의 event_type CHECK 제약조건 우회를 위해 정제)
    if seen_events:
        db_payload = []
        for ev in seen_events.values():
            ev_copy = ev.copy()
            # DB가 "신호위반충돌위험"이라는 신규 타입을 지원하지 않을 수 있으므로 기존 호환 타입인 "신호위반"으로 안전 우회
            if ev_copy.get("event_type") == "신호위반충돌위험":
                ev_copy["event_type"] = "신호위반"
            db_payload.append(ev_copy)
            
        supabase.table("event").insert(db_payload).execute()
        print(f"[DB] event {len(db_payload)}건 저장 완료: {list(seen_events.keys())}")
        
    # violation_map을 list 형태로 변환 (set → list)
    violation_map: Dict[str, List[int]] = {k: list(v) for k, v in violation_track_map.items()}
    return list(seen_events.keys()), violation_map


# ──────────────────────────────────────────────────────────
# Step 3. accident_type 매칭 (Python 직접 매칭)
# ──────────────────────────────────────────────────────────

# 이벤트 → description/accident_name 검색 키워드 목록
EVENT_TO_KEYWORDS = {
    "신호위반충돌위험": ["신호기", "신호등", "신호위반", "적색", "교차로"],
    "신호위반":    ["신호기", "신호등", "신호위반", "적색", "녹색신호", "신호에"],
    "중앙선침범":  ["중앙선", "중앙분리"],
    "진로변경":    ["차선변경", "진로변경", "끼어들기", "앞지르기"],
    "안전모미착용": ["이륜차", "오토바이", "안전모"],
    "과속":       ["과속", "속도위반", "제한속도"],
    "보행자위협":  ["보행자", "횡단보도"],
}

PRIORITY_ORDER = ["신호위반충돌위험", "신호위반", "중앙선침범", "과속", "보행자위협", "진로변경", "안전모미착용"]

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
    "신호위반충돌위험": "도로교통법 제5조(신호 또는 지시에 따를 의무) 및 교차로 통행방법 위반",
    "신호위반":    "도로교통법 제5조(신호 또는 지시에 따를 의무)",
    "중앙선침범":  "도로교통법 제13조(차마의 통행)",
    "진로변경":    "도로교통법 제19조(안전거리 확보 등)",
    "안전모미착용": "도로교통법 제50조(모든 차의 운전자의 준수사항)",
    "과속":       "도로교통법 제17조(자동차 등의 속도)",
    "보행자위협":  "도로교통법 제27조(보행자의 보호)",
}

def evaluate_car_to_car_fault(
    event_types: List[str],
    records: List[Dict],
    violation_map: Dict[str, List[int]],
    base_a: int,
    base_b: int,
    modifier_desc: List[str],
) -> Tuple[int, int, List[str]]:
    """
    차대차 과실비율 내장 룰 엔진.
    violation_map을 통해 어떤 차량(track_id)이 어떤 위반을 저질렀는지 파악하고,
    A차량(주과실 차량) / B차량(피해 차량) 을 특정하여 과실비율을 조정한다.

    기본 룰 (한국소비자원 및 손해보험협회 과실비율 인정기준 참조):
      - 신호위반/중앙선침범 단독 → 일방과실 100:0
      - 진로변경 단독 → 70:30
      - 진로변경 + 직진 차량 과속 → 50:50 (+20% 가산)
      - 중과실 + 진로변경 복합 → 80:20
      - 쌍방 진로변경/과속 → 50:50
    """
    applied_desc = list(modifier_desc)

    # ── 위반 차량 집합 구성 ──
    critical_events  = {"신호위반", "신호위반충돌위험", "중앙선침범"}
    lane_change_events = {"진로변경"}
    speed_events     = {"과속"}

    # 중과실 위반 차량 track_ids
    critical_violators: set = set()
    for ev in critical_events:
        critical_violators.update(violation_map.get(ev, []))

    # 진로변경 위반 차량 track_ids
    lane_change_violators: set = set(violation_map.get("진로변경", []))

    # 과속 위반 차량 track_ids
    speed_violators: set = set(violation_map.get("과속", []))

    has_critical    = bool(critical_violators) or any(e in event_types for e in critical_events)
    has_lane_change = bool(lane_change_violators) or "진로변경" in event_types
    has_speeding    = bool(speed_violators) or "과속" in event_types

    # ── A/B 차량 특정 (위반 차량 = A, 피해 차량 = B) ──
    # 중과실 위반자가 있으면 그가 A차량, 나머지가 B차량
    # 진로변경 위반자가 있으면 그가 A차량
    a_violators: set = critical_violators or lane_change_violators
    b_violators: set = speed_violators - a_violators  # 과속은 B 차량 과실 가산 요소

    # A/B 차량 ID 설명 문자열
    def _ids(s: set) -> str:
        return f"(차량ID: {sorted(s)})" if s else ""

    # ── 1. 일방 과실 (100:0) ──
    # 중과실이 있고, 상대방의 별도 위반(진로변경·과속)이 없는 경우
    if has_critical and not has_lane_change and not has_speeding:
        a_str = _ids(critical_violators)
        applied_desc.append(
            f"일방과실(100:0) 판단 {a_str}: 한쪽 차량의 중대한 법규 위반(신호위반/중앙선침범)으로 사고가 발생하였고, "
            "상대 차량은 정상 주행 중이었으며 당시 상황을 예견하거나 회피하기 어려웠음 "
            "(도로교통법 제5조·제13조 기준)"
        )
        return 100, 0, applied_desc

    # ── 2. 중과실 + 진로변경 복합 (80:20) ──
    if has_critical and has_lane_change:
        # 중과실 위반자 ≠ 진로변경 위반자 → 서로 다른 차량이 각각 위반
        cv_ids = _ids(critical_violators)
        lc_ids = _ids(lane_change_violators)
        applied_desc.append(
            f"과실 조정(80:20): A차량 중과실 위반 {cv_ids} + B차량 진로변경 주의의무 위반 {lc_ids} 경합. "
            "일방 중과실을 상쇄하더라도 A차량 과실이 더 크므로 80:20 적용"
        )
        return 80, 20, applied_desc

    # ── 3. 진로변경 기본 과실 (70:30) ──
    if has_lane_change:
        lc_ids = _ids(lane_change_violators)

        # 3-a. 진로변경 + 직진 차량 과속 → 50:50 (과속 가산 20%)
        if has_speeding:
            sp_ids = _ids(speed_violators)
            # 진로변경 차량과 과속 차량이 동일 차량이면 자기 과실 심화 → 85:15
            same_vehicle = lane_change_violators & speed_violators
            if same_vehicle:
                applied_desc.append(
                    f"과실 가중(85:15): 동일 차량 {_ids(same_vehicle)}이 진로변경과 과속을 동시에 위반. "
                    "자기 과실이 심화되어 85:15 적용"
                )
                return 85, 15, applied_desc
            else:
                applied_desc.append(
                    f"과실 조정(50:50): 진로변경 차량 {lc_ids}의 기본 과실(70%)에서 "
                    f"상대 직진 차량 {sp_ids}의 과속에 따른 주의의무 위반(+20%) 반영하여 50:50으로 보정 "
                    "(손해보험협회 과실비율 인정기준 참조)"
                )
                return 50, 50, applied_desc

        # 3-b. 쌍방 모두 진로변경 → 50:50
        if len(lane_change_violators) >= 2:
            applied_desc.append(
                f"과실 조정(50:50): 양 차량 {lc_ids} 모두 진로변경 중 충돌. "
                "쌍방 주의의무 위반이 동등하므로 50:50 적용"
            )
            return 50, 50, applied_desc

        # 3-c. 진로변경 단독 → 70:30
        applied_desc.append(
            f"기본 과실(70:30): 진로변경 차량 {lc_ids}의 주의의무 위반. "
            "직진 차량은 정상 주행 중이었으며 예견·회피 가능성이 낮았음 "
            "(손해보험협회 과실비율 인정기준 참조)"
        )
        return 70, 30, applied_desc

    # ── 4. 과속 단독 (+20% B차량 가산) ──
    if has_speeding and not has_critical and not has_lane_change:
        sp_ids = _ids(speed_violators)
        new_b = min(100, base_b + 20)
        new_a = 100 - new_b
        applied_desc.append(
            f"과실 가산: B차량 {sp_ids} 과속 감지 → B차량 과실 +20% 반영 (기본 {base_b}% → {new_b}%)"
        )
        return new_a, new_b, applied_desc

    # ── 5. 해당 없음 → DB 기반 기본 과실비율 유지 ──
    return base_a, base_b, applied_desc

def build_result(
    event_types: List[str],
    accident_type: Optional[Dict],
    fault_a: int,
    fault_b: int,
    modifier_desc: List[str],
) -> Dict:
    accident_name = accident_type["accident_name"] if accident_type else "불명확"
    is_one_sided_fault = (fault_a == 100 and fault_b == 0)

    if "신호위반충돌위험" in event_types:
        situation_summary = (
            f"블랙박스 영상 분석 결과, 적색 신호 상태에서 정지선을 넘어 돌진한 신호위반 차량과 "
            f"교차로 내 타 차선에서 정상 진입한 차량 간의 급격한 근접 및 충돌 위협 상황이 감지되었습니다. "
        )
        if is_one_sided_fault:
            situation_summary += "상대 차량은 정상 신호에 따라 주행 중이었으며 당시 사고를 예견하거나 회피하기 어려웠던 것으로 판단됩니다."
        else:
            situation_summary += f"사고 유형({accident_name})의 DB 기준 및 양측 위반 상황을 토대로 과실 비율을 판단하였습니다."

        accident_cause = (
            f"적색 신호 중 정지선 침범 및 교차로 강제 진입으로 인해 타 정상 신호 주행 차량과의 충돌 위험이 발생하였습니다. "
            f"이는 도로교통법 제5조 신호위반에 따른 중과실 사고 유발 행위입니다. "
        )
        if is_one_sided_fault:
            accident_cause += "상대 차량에게 사고 예견 및 회피 가능성을 인정하기 어려운 상황이므로 A차량의 일방 과실(100%)로 산정하였습니다."
        else:
            accident_cause += f"양측의 과실 요소를 고려하여 A차량 과실 {fault_a}%로 산정하였습니다."
            
    elif event_types:
        situation_summary = (
            f"블랙박스 영상 분석 결과 {', '.join(event_types)} 등 "
            f"{len(event_types)}건의 위반 행위가 감지되었습니다. "
            f"사고 유형({accident_name})을 기준으로 과실비율을 산정하였습니다."
        )
        if is_one_sided_fault:
            situation_summary += " 상대 차량은 정상 주행 중이었으며 당해 사고를 예견하거나 회피하기 어려웠던 상황으로 판단됩니다."

        accident_cause = (
            f"영상에서 {', '.join(event_types)}이(가) 감지되었으며 "
            f"이는 사고의 주요 원인으로 판단됩니다. "
        )
        if is_one_sided_fault:
            accident_cause += "중대한 법규 위반으로 인해 상대방의 예견·회피 가능성이 극히 낮아 A차량의 일방 과실(100%)로 산정하였습니다."
        else:
            accident_cause += f"A차량의 과실을 {fault_a}%로 산정하였습니다."
            
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
    elif len(event_types) >= 2 or "신호위반충돌위험" in event_types:
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
    event_types, violation_map = detect_events(supabase, video_id, records)

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

    # 4.5. 내장 규칙 기반 차대차 과실비율 판단 및 조정 (법적 피드백 반영)
    fault_a, fault_b, modifier_desc = evaluate_car_to_car_fault(
        event_types=event_types,
        records=records,
        violation_map=violation_map,
        base_a=fault_a,
        base_b=fault_b,
        modifier_desc=modifier_desc,
    )

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
