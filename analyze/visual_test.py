import torch
import cv2
import os
import argparse
import warnings

# PyTorch 2.4+ FutureWarning 숨김
warnings.filterwarnings("ignore", category=FutureWarning)

from backend.yolo_inference import compute_iou, HistIoUTracker

def run_visual(video_path):
    print(f"[{video_path}] 비디오 분석을 시작합니다...")
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    yolo_repo_dir = os.path.join(current_dir, "yolov5")
    model_dir = os.path.join(current_dir, "models")
    
    weights_paths = {
        "신호": os.path.join(model_dir, "model_객체탐지_신호위반.pt"),
        "안전모": os.path.join(model_dir, "model_객체탐지_안전모.pt"),
        "중앙": os.path.join(model_dir, "model_객체탐지_중앙선침범.pt"),
        "진로": os.path.join(model_dir, "model_객체탐지_진로변경.pt")
    }

    _original_load = torch.load
    def safe_load(*args, **kwargs):
        kwargs['weights_only'] = False
        return _original_load(*args, **kwargs)
    torch.load = safe_load

    print("모델 가중치를 로딩 중입니다...")
    models = {}
    try:
        for m_name, path in weights_paths.items():
            loaded = torch.hub.load(repo_or_dir=yolo_repo_dir, model='custom', path=path, source='local', force_reload=False)
            loaded.conf = 0.70 # 신뢰도 70% 이상인 객체만 필터링하도록 수정
            models[m_name] = loaded
    finally:
        torch.load = _original_load

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"오류: {video_path} 비디오를 열 수 없습니다.")
        return

    # 화면에 표시하기 위한 리사이징 (화면이 너무 클 경우 방지)
    def resize_frame(frame, max_width=1280):
        h, w = frame.shape[:2]
        if w > max_width:
            r = max_width / float(w)
            dim = (max_width, int(h * r))
            return cv2.resize(frame, dim, interpolation=cv2.INTER_AREA)
        return frame

    tracker = HistIoUTracker(iou_thresh=0.1, max_frames=3, missing_history=150)
    
    print("\n✅ 분석 시작! 화면에서 확인하세요.")
    print("종료하려면 영상 창을 선택하고 'q' 키를 누르세요.\n")

    # 프레임 생략 없이 부드럽게 보기 (원한다면 target_fps 지정 가능)
    while True:
        ret, frame = cap.read()
        if not ret:
            print("영상 재생 완료.")
            break
            
        view_frame = resize_frame(frame)
        
        all_detections = []
        # 원본 크기에서 탐지
        for m_name, model in models.items():
            results = model(frame)
            df = results.pandas().xyxy[0]
            for index, row in df.iterrows():
                all_detections.append({
                    "bbox": [int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])],
                    "name": f"[{m_name}] {row['name']}",
                    "confidence": round(float(row['confidence']), 4)
                })
        
        all_detections = sorted(all_detections, key=lambda x: x['confidence'], reverse=True)
        
        merged_detections = []
        for det in all_detections:
            is_dup = False
            for kept in merged_detections:
                if compute_iou(det['bbox'], kept['bbox']) > 0.6:
                    if det['name'] not in kept['name']:
                        kept['name'] += f", {det['name']}"
                    is_dup = True
                    break
            if not is_dup:
                merged_detections.append(det)
        
        tracked_detections = tracker.update(merged_detections, frame)
        
        # 화면에 그리기
        scale_x = view_frame.shape[1] / frame.shape[1]
        scale_y = view_frame.shape[0] / frame.shape[0]

        for det in tracked_detections:
            x1, y1, x2, y2 = det["bbox"]
            conf = det['confidence']
            name = det['name']
            t_id = det["track_id"]
            
            # 리사이즈 화면 좌표로 변환
            vx1, vy1 = int(x1 * scale_x), int(y1 * scale_y)
            vx2, vy2 = int(x2 * scale_x), int(y2 * scale_y)
            
            # 박스 그리기 (파란색)
            cv2.rectangle(view_frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
            
            # 텍스트 그리기
            label = f"ID:{t_id} {name} {conf:.2f}"
            cv2.putText(view_frame, label, (vx1, vy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        cv2.imshow("YOLO Tracking Visualization", view_frame)

        # 'q' 키를 누르면 종료
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("사용자에 의해 중단되었습니다.")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YOLO Visual Test")
    parser.add_argument("video_path", help="분석할 동영상 파일의 경로를 입력하세요")
    args = parser.parse_args()
    
    run_visual(args.video_path)
