import torch
import cv2
import uuid
import os
import warnings

# PyTorch 2.4+의 autocast FutureWarning 숨김 처리
warnings.filterwarnings("ignore", category=FutureWarning, message=".*torch\.cuda\.amp\.autocast.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="models.common")

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

class IoUTracker:
    def __init__(self, iou_thresh=0.1, max_frames=3):
        self.tracks = {}  # {track_id: {"box": [x1, y1, x2, y2], "frames_missing": 0}}
        self.next_id = 1
        self.iou_thresh = iou_thresh
        self.max_frames = max_frames

    def update(self, detected_boxes):
        if len(self.tracks) == 0:
            for det in detected_boxes:
                det["track_id"] = self.next_id
                self.tracks[self.next_id] = {"box": det["bbox"], "frames_missing": 0}
                self.next_id += 1
            return detected_boxes

        unmatched_dets = list(range(len(detected_boxes)))
        unmatched_tracks = list(self.tracks.keys())
        matches = []

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

        for d_idx in unmatched_dets:
            detected_boxes[d_idx]["track_id"] = self.next_id
            self.tracks[self.next_id] = {"box": detected_boxes[d_idx]["bbox"], "frames_missing": 0}
            self.next_id += 1

        for t_id in unmatched_tracks:
            self.tracks[t_id]["frames_missing"] += 1
            
        for t_id in list(self.tracks.keys()):
            if self.tracks[t_id]["frames_missing"] > self.max_frames:
                del self.tracks[t_id]

        return detected_boxes

def analyze_video_with_yolo(video_path, weights_paths, video_id="WEB_UP_001"):
    """
    FastAPI 서버 내부에서 비동기 호출을 받거나, 직접 실행되어 비디오를 분석하고
    object_detection 테이블용 데이터를 반환하는 함수입니다 (추적 및 다중가중치 병합 기능 포함).
    """
    # 현재 파일 기준 rum 내부의 로컬 yolov5 경로 매핑
    current_dir = os.path.dirname(os.path.abspath(__file__))
    yolo_repo_dir = os.path.join(current_dir, "..", "yolov5")
    
    # PyTorch 2.6+ 대응: torch.load가 기본적으로 weights_only=False로 동작하도록 임시 패치
    _original_load = torch.load
    def safe_load(*args, **kwargs):
        kwargs['weights_only'] = False
        return _original_load(*args, **kwargs)
    
    torch.load = safe_load
    try:
        if isinstance(weights_paths, dict):
            models = {}
            for m_name, path in weights_paths.items():
                # 인터넷 다운로드 대신 로컬(source='local') 리포지토리 사용
                loaded = torch.hub.load(repo_or_dir=yolo_repo_dir, model='custom', path=path, source='local', force_reload=False)
                loaded.conf = 0.25
                models[m_name] = loaded
        else:
            # 하위호환을 위해 단일 문자열 경로일 경우
            loaded = torch.hub.load(repo_or_dir=yolo_repo_dir, model='custom', path=weights_paths, source='local', force_reload=False)
            loaded.conf = 0.25 
            models = {"기본": loaded}
    finally:
        torch.load = _original_load
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("비디오 파일을 열 수 없습니다.")

    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    if orig_fps <= 0: orig_fps = 30
    
    target_fps = 5
    frame_interval = max(int(round(orig_fps / target_fps)), 1)

    extracted_records = []
    frame_idx = 0
    processed_count = 0
    tracker = IoUTracker(iou_thresh=0.1, max_frames=3)
    
    while True:
        ret, frame = cap.read()
        if not ret: break
            
        if frame_idx % frame_interval != 0:
            frame_idx += 1
            continue
            
        # 모든 모델에 대해 추론하고 1차 수집
        all_detections = []
        for m_name, model in models.items():
            results = model(frame)
            df = results.pandas().xyxy[0]
            for index, row in df.iterrows():
                all_detections.append({
                    "bbox": [int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])],
                    "name": f"[{m_name}] {row['name']}",
                    "confidence": round(float(row['confidence']), 4)
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
        tracked_detections = tracker.update(merged_detections)
        
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
    return {"total_frames": processed_count, "records": extracted_records}
