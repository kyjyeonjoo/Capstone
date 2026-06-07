import torch
import cv2
import uuid
import os
import warnings
import math

# PyTorch 2.4+의 autocast FutureWarning 숨김 처리
warnings.filterwarnings("ignore", category=FutureWarning, message=r".*torch\.cuda\.amp\.autocast.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="models.common")

# ──────────────────────────────────────────────────────────────────
# 모델 클래스명 → fault_analyzer 기대 클래스명 정규화 매핑
# best.pt 학습 시 사용된 클래스명과 fault_analyzer 판단 로직에서
# 기대하는 클래스명이 달라서 필요한 변환 테이블
# ──────────────────────────────────────────────────────────────────
CLASS_NAME_MAP = {
    "vehicle":      "car",         # 차량 → 일반 차량 (car/bus/truck/motorcycle 공통 처리)
    "red_light":    "red",         # 적색 신호 → red
    "green_light":  "green_light",
    "yellow_light": "yellow_light",
    "left_light":   "left_light",
    "stop_line":    "stopline",    # 정지선 → stopline
    "crosswalk":    "crosswalk",
    "center_line":  "yellowline",  # 중앙선(황색) → yellowline
    "white_line":   "white_line",  # 백색 차선
    "helmet":       "helmet",
    "no_helmet":    "no_helmet",
}

VEHICLE_TYPES = {"car", "bus", "truck", "motorcycle"}

def get_base_object_type(object_type):
    if object_type.startswith("[") and "]" in object_type:
        return object_type.split("]", 1)[1].strip()
    return object_type

def reconcile_vehicle_track_ids(records, fps, max_gap_seconds=2.5):
    """Merge vehicle track fragments that were split by brief occlusion or scale change."""
    vehicle_tracks = {}
    for record in records:
        if get_base_object_type(record.get("object_type", "")) not in VEHICLE_TYPES:
            continue
        track_id = record.get("track_id")
        if track_id is None:
            continue
        vehicle_tracks.setdefault(track_id, []).append(record)

    fragments = []
    for track_id, track_records in vehicle_tracks.items():
        ordered = sorted(track_records, key=lambda item: item.get("frame", 0))
        first = ordered[0]
        last = ordered[-1]

        def metrics(record):
            width = max(1, record.get("bbox_x2", 0) - record.get("bbox_x1", 0))
            height = max(1, record.get("bbox_y2", 0) - record.get("bbox_y1", 0))
            return (
                (record.get("bbox_x1", 0) + record.get("bbox_x2", 0)) / 2,
                (record.get("bbox_y1", 0) + record.get("bbox_y2", 0)) / 2,
                width * height,
            )

        fragments.append(
            {
                "track_id": track_id,
                "records": ordered,
                "start_frame": first.get("frame", 0),
                "end_frame": last.get("frame", 0),
                "start": metrics(first),
                "end": metrics(last),
            }
        )

    fragments.sort(key=lambda item: item["start_frame"])
    parent = {fragment["track_id"]: fragment["track_id"] for fragment in fragments}
    max_gap_frames = max(1, int(fps * max_gap_seconds))

    for current_index, current in enumerate(fragments):
        best_previous = None
        best_score = float("inf")
        start_x, start_y, start_area = current["start"]

        for previous in fragments[:current_index]:
            previous_root = parent[previous["track_id"]]
            gap = current["start_frame"] - previous["end_frame"]
            if gap <= 0 or gap > max_gap_frames:
                continue

            end_x, end_y, end_area = previous["end"]
            center_distance = math.hypot(start_x - end_x, start_y - end_y)
            scale = max(40.0, math.sqrt(end_area), math.sqrt(start_area))
            normalized_distance = center_distance / scale
            area_change = abs(math.log(max(start_area, 1) / max(end_area, 1)))

            # A short gap may include a large apparent-size change near impact.
            score = normalized_distance + (area_change * 0.35) + (gap / max_gap_frames)
            if normalized_distance <= 2.5 and area_change <= 2.2 and score < best_score:
                best_score = score
                best_previous = previous_root

        if best_previous is not None and best_score <= 3.2:
            parent[current["track_id"]] = best_previous

    def root(track_id):
        while parent.get(track_id, track_id) != track_id:
            track_id = parent[track_id]
        return track_id

    for record in records:
        track_id = record.get("track_id")
        if track_id in parent:
            record["track_id"] = root(track_id)

    return records

def compute_iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    iou = interArea / float(boxAArea + boxBArea - interArea + 1e-5)
    return iou

def extract_histogram(frame, bbox):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    hsv_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv_crop], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist

class HistIoUTracker:
    def __init__(self, iou_thresh=0.1, max_frames=3, missing_history=150):
        self.tracks = {}  # {track_id: {"box": bbox, "frames_missing": 0, "hist": hist}}
        self.history = {} # 휴지통 {track_id: {"hist": hist, "frames_missing": 0}}
        self.next_id = 1
        self.iou_thresh = iou_thresh
        self.max_frames = max_frames
        self.missing_history = missing_history

    def update(self, detected_boxes, frame):
        for det in detected_boxes:
            det["hist"] = extract_histogram(frame, det["bbox"])

        if len(self.tracks) == 0:
            for det in detected_boxes:
                det["track_id"] = self.next_id
                self.tracks[self.next_id] = {"box": det["bbox"], "frames_missing": 0, "hist": det["hist"]}
                self.next_id += 1
            return detected_boxes

        unmatched_dets = list(range(len(detected_boxes)))
        unmatched_tracks = list(self.tracks.keys())
        matches = []

        # 1. IoU 매칭
        for d_idx, det in enumerate(detected_boxes):
            best_iou = self.iou_thresh
            best_t_id = -1
            for t_id in unmatched_tracks:
                iou = compute_iou(det["bbox"], self.tracks[t_id]["box"])
                if iou > best_iou:
                    best_iou = iou
                    best_t_id = t_id
            
            if best_t_id != -1:
                matches.append((d_idx, best_t_id))
                unmatched_tracks.remove(best_t_id)
                unmatched_dets.remove(d_idx)
                
        for d_idx, t_id in matches:
            detected_boxes[d_idx]["track_id"] = t_id
            self.tracks[t_id]["box"] = detected_boxes[d_idx]["bbox"]
            self.tracks[t_id]["frames_missing"] = 0
            if detected_boxes[d_idx]["hist"] is not None:
                self.tracks[t_id]["hist"] = detected_boxes[d_idx]["hist"]

        # 2. 색상 히스토그램 재식별 (Re-ID)
        reid_matches = []
        matched_history = set()
        
        # 아직 휴지통(history)에 가지 않았지만 프레임에서 사라져서 IoU 매칭에 실패한 기존 트랙들도 모두 색상 검사 풀에 넣습니다.
        candidate_pool = {}
        for t_id in unmatched_tracks:
            candidate_pool[t_id] = self.tracks[t_id]
        for t_id, data in self.history.items():
            candidate_pool[t_id] = data
            
        for d_idx in unmatched_dets:
            det_hist = detected_boxes[d_idx]["hist"]
            if det_hist is None: continue
            
            best_score = 0.50  # 빡빡했던 유사도 기준을 살짝 완화
            best_t_id = -1
            for t_id, t_data in candidate_pool.items():
                if t_id in matched_history: continue
                if t_data["hist"] is not None:
                    score = cv2.compareHist(det_hist, t_data["hist"], cv2.HISTCMP_CORREL)
                    if score > best_score:
                        best_score = score
                        best_t_id = t_id
                        
            if best_t_id != -1:
                reid_matches.append((d_idx, best_t_id))
                matched_history.add(best_t_id)
                
        for d_idx, t_id in reid_matches:
            detected_boxes[d_idx]["track_id"] = t_id
            self.tracks[t_id] = {
                "box": detected_boxes[d_idx]["bbox"],
                "frames_missing": 0,
                "hist": detected_boxes[d_idx]["hist"]
            }
            if t_id in self.history:
                del self.history[t_id]
            if t_id in unmatched_tracks:
                unmatched_tracks.remove(t_id)
            unmatched_dets.remove(d_idx)

        # 3. 매칭 안 된 객체 새 ID 부여
        for d_idx in unmatched_dets:
            detected_boxes[d_idx]["track_id"] = self.next_id
            self.tracks[self.next_id] = {"box": detected_boxes[d_idx]["bbox"], "frames_missing": 0, "hist": detected_boxes[d_idx]["hist"]}
            self.next_id += 1

        # 4. 사라진 객체 휴지통(History) 이동 처리
        for t_id in unmatched_tracks:
            self.tracks[t_id]["frames_missing"] += 1
            if self.tracks[t_id]["frames_missing"] > self.max_frames:
                self.history[t_id] = {"hist": self.tracks[t_id]["hist"], "frames_missing": 0}
                del self.tracks[t_id]
                
        for t_id in list(self.history.keys()):
            self.history[t_id]["frames_missing"] += 1
            if self.history[t_id]["frames_missing"] > self.missing_history:
                del self.history[t_id]

        return detected_boxes

def analyze_video_with_yolo(video_path, weights_paths, video_id="WEB_UP_001"):
    """
    FastAPI 서버 내부에서 비동기 호출을 받거나, 직접 실행되어 비디오를 분석하고
    object_detection 테이블용 데이터를 반환하는 함수입니다 (추적 및 다중가중치 병합 기능 포함).
    """
    # 현재 파일 기준 rum 내부의 로컬 yolov5 경로 매핑
    current_dir = os.path.dirname(os.path.abspath(__file__))
    yolo_repo_dir = os.path.join(current_dir, "..", "yolov5")
    
    # AutoShape._apply의 AttributeError: 'Detect' object has no attribute 'grid' 패치 (PyTorch 버전/모델 호환성 문제 해결)
    import sys
    if yolo_repo_dir not in sys.path:
        sys.path.append(yolo_repo_dir)
        
    try:
        from models.common import AutoShape
        _original_apply = AutoShape._apply
        def safe_apply(self, fn):
            if self.pt:
                m = self.model.model.model[-1] if self.dmb else self.model.model[-1]  # Detect()
                if not hasattr(m, 'grid'):
                    m.grid = [torch.empty(0) for _ in range(getattr(m, 'nl', 3))]
                if not hasattr(m, 'anchor_grid'):
                    m.anchor_grid = [torch.empty(0) for _ in range(getattr(m, 'nl', 3))]
            return _original_apply(self, fn)
        AutoShape._apply = safe_apply
    except Exception as e:
        print(f"[경고] AutoShape._apply 패치 적용 실패: {e}")

    # PyTorch 2.6+ 대응: torch.load가 기본적으로 weights_only=False로 동작하도록 임시 패치
    _original_load = torch.load
    def safe_load(*args, **kwargs):
        kwargs['weights_only'] = False
        return _original_load(*args, **kwargs)
    
    torch.load = safe_load
    try:
        models = {}
        if isinstance(weights_paths, dict):
            paths_dict = weights_paths
        else:
            paths_dict = {"기본": weights_paths}

        for m_name, path in paths_dict.items():
            if not os.path.exists(path):
                print(f"[YOLO 경고] 모델 파일이 존재하지 않습니다: {path}")
                continue
            
            # 1. YOLOv8 (ultralytics) 로딩 우선 시도
            try:
                from ultralytics import YOLO
                print(f"[YOLO] YOLOv8 모델 로딩 시도: {m_name} ← {path}")
                loaded = YOLO(path)
                print(f"[YOLO] YOLOv8 모델 '{m_name}' 로딩 완료. 클래스 목록: {loaded.names}")
                models[m_name] = {"type": "yolov8", "model": loaded}
            except Exception as e8:
                print(f"[YOLO] YOLOv8 로딩 실패 ({e8}), YOLOv5 로딩 시도...")
                # 2. 기존 YOLOv5 (Hub) 로딩 Fallback
                try:
                    loaded = torch.hub.load(repo_or_dir=yolo_repo_dir, model='custom', path=path, source='local', force_reload=False)
                    loaded.conf = 0.30 if isinstance(weights_paths, dict) else 0.70
                    print(f"[YOLO] YOLOv5 모델 '{m_name}' 로딩 완료. 클래스 목록: {loaded.names}")
                    models[m_name] = {"type": "yolov5", "model": loaded}
                except Exception as e5:
                    print(f"[YOLO 오류] 모델 '{m_name}' 로딩 실패: {e5}")

        if not models:
            raise ValueError("[YOLO] 로딩된 모델이 없습니다. 모델 파일 경로를 확인하세요.")
    finally:
        torch.load = _original_load
    
    # ── Detect layer 내부 구조 진단 (nc/no 불일치 확인) ──
    for m_name, model_info in models.items():
        m_obj = model_info["model"]
        m_type = model_info["type"]
        try:
            if m_type == "yolov5":
                detect_m = m_obj.model.model[-1]
                real_nc = getattr(detect_m, 'nc', '?')
                real_no = getattr(detect_m, 'no', '?')
                names_count = len(m_obj.names)
                print(f"[YOLO DIAG] 모델={m_name} (YOLOv5) | Detect.nc={real_nc}, Detect.no={real_no} | names 수={names_count}")
                if isinstance(real_nc, int) and real_nc != names_count:
                    print(f"[YOLO DIAG] ⚠️  nc({real_nc}) ≠ names 수({names_count}) → 아키텍처/메타데이터 불일치! cls_id가 names 범위 밖으로 나올 수 있음")
            else:
                print(f"[YOLO DIAG] 모델={m_name} (YOLOv8) | classes={m_obj.names}")
        except Exception as diag_e:
            print(f"[YOLO DIAG] 모델={m_name} 진단 실패: {diag_e}")

    print(f"[YOLO] 영상 열기 시도: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"비디오 파일을 열 수 없습니다: {video_path}")

    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[YOLO] 영상 정보 — FPS: {orig_fps}, 전체 프레임 수: {total_video_frames}")
    if orig_fps <= 0: orig_fps = 30

    target_fps = 5
    frame_interval = max(int(round(orig_fps / target_fps)), 1)

    extracted_records = []
    frame_idx = 0
    processed_count = 0
    tracker = HistIoUTracker(iou_thresh=0.1, max_frames=3, missing_history=150)
    
    while True:
        ret, frame = cap.read()
        if not ret: break
            
        if frame_idx % frame_interval != 0:
            frame_idx += 1
            continue
            
        # 모든 모델에 대해 추론하고 1차 수집
        all_detections = []
        for m_name, model_info in models.items():
            m_type = model_info["type"]
            model = model_info["model"]
            
            if m_type == "yolov8":
                conf_val = 0.30 if len(models) > 1 or m_name == "통합" else 0.70
                results = model(frame, conf=conf_val, verbose=False)
                if len(results) > 0:
                    result = results[0]
                    for box in result.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        
                        cls_name = None
                        names = model.names
                        if isinstance(names, dict):
                            cls_name = names.get(cls_id) or names.get(str(cls_id))
                        elif isinstance(names, list) and 0 <= cls_id < len(names):
                            cls_name = names[cls_id]
                        if not cls_name:
                            cls_name = f"class_{cls_id}"

                        # 첫 탐지 시 디버그 로그
                        if processed_count == 0 and len(all_detections) == 0:
                            print(f"[YOLO DEBUG] YOLOv8 첫 탐지 상세: cls_id={cls_id}, cls_name='{cls_name}', names={names}")

                        mapped_name = CLASS_NAME_MAP.get(cls_name, cls_name)
                        clean_name = mapped_name if m_name == "통합" else f"[{m_name}] {mapped_name}"
                        all_detections.append({
                            "bbox": [int(x1), int(y1), int(x2), int(y2)],
                            "name": clean_name,
                            "confidence": round(float(conf), 4)
                        })
            else:
                # YOLOv5 추론
                results = model(frame)
                if processed_count == 0:
                    # 첫 프레임에서만 raw pred 출력 (디버그용)
                    raw = results.pred[0] if hasattr(results, 'pred') and len(results.pred) > 0 else None
                    print(f"[YOLO DEBUG] YOLOv5 첫 프레임 탐지 결과 (모델={m_name}): {raw.shape if raw is not None else 'None'} | 탐지 수={len(raw) if raw is not None else 0}")
                # results.pandas() 호출 시 내부 KeyError: 5006 방지 및 안전 예외 처리를 위해 results.pred 직접 파싱
                if hasattr(results, 'pred') and len(results.pred) > 0:
                    pred = results.pred[0]
                    for det in pred:
                        x1, y1, x2, y2, conf, cls = det.tolist()
                        cls_id = int(cls)
                        
                        # model.names가 딕셔너리인지 리스트인지에 따른 극도의 안전한 매칭 조회
                        cls_name = None
                        names = model.names
                        if isinstance(names, dict):
                            cls_name = names.get(cls_id) or names.get(str(cls_id))
                        elif isinstance(names, list) and 0 <= cls_id < len(names):
                            cls_name = names[cls_id]
                        if not cls_name:
                            cls_name = f"class_{cls_id}"

                        # 첫 탐지 시 raw 값 전체 출력 (모델 nc 불일치 원인 파악용)
                        if processed_count == 0 and len(all_detections) == 0:
                            h_f, w_f = frame.shape[:2]
                            print(f"[YOLO DIAG] 원본 해상도: {w_f}x{h_f}")
                            print(f"[YOLO DIAG] YOLOv5 첫 탐지 raw 6값: {[round(v,4) for v in det.tolist()]}")
                            print(f"[YOLO DIAG]   → x1={x1:.1f}, y1={y1:.1f}, x2={x2:.1f}, y2={y2:.1f}, conf={conf:.6f}, cls={cls:.2f}")
                            print(f"[YOLO DIAG]   → cls_id(int)={cls_id}, raw_name='{cls_name}'")

                        mapped_name = CLASS_NAME_MAP.get(cls_name, cls_name)
                        clean_name = mapped_name if m_name == "통합" else f"[{m_name}] {mapped_name}"
                        all_detections.append({
                            "bbox": [int(x1), int(y1), int(x2), int(y2)],
                            "name": clean_name,
                            "confidence": round(float(conf), 4)
                        })
        
        # 신뢰도 내림차순 정렬
        all_detections = sorted(all_detections, key=lambda x: x['confidence'], reverse=True)
        
        # 커스텀 중복 제거(Merge) 로직
        merged_detections = []
        for det in all_detections:
            is_dup = False
            for kept in merged_detections:
                # 겹치는 면적이 60% 이상이면 동일 사물로 간주
                if compute_iou(det['bbox'], kept['bbox']) > 0.6:
                    # 이름 융합 (없는 이름일 경우에만 추가)
                    if det['name'] not in kept['name']:
                        kept['name'] += f", {det['name']}"
                    is_dup = True
                    break
            
            if not is_dup:
                merged_detections.append(det)
            
        # 통합된 BBox들을 트래커에 통과시켜 track_id 부여
        tracked_detections = tracker.update(merged_detections, frame)
        
        for det in tracked_detections:
            record = {
                "id": str(uuid.uuid4()),               
                "video_id": video_id,                  
                "frame": frame_idx,
                "track_id": det["track_id"], # 새로 추가된 트래킹 ID
                "object_type": det['name'],            
                "bbox_x1": det["bbox"][0],           
                "bbox_y1": det["bbox"][1],           
                "bbox_x2": det["bbox"][2],           
                "bbox_y2": det["bbox"][3],           
                "confidence": det['confidence'] 
            }
            extracted_records.append(record)
            
        frame_idx += 1
        processed_count += 1
        
    cap.release()
    extracted_records = reconcile_vehicle_track_ids(
        extracted_records,
        fps=float(orig_fps),
    )
    print(f"[YOLO] 분석 완료 — 처리 프레임: {processed_count}, 총 탐지 기록 수: {len(extracted_records)}")
    return {
        "total_frames": processed_count,
        "records": extracted_records,
        "fps": float(orig_fps),
        "total_video_frames": total_video_frames
    }
