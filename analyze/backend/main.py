from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import shutil
import uuid

# yolo_inference.py에서 로직 가져오기
from yolo_inference import analyze_video_with_yolo

app = FastAPI()

# CORS 허용 (로컬 구동용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# YOLO 4종 모델 경로 딕셔너리 (프로젝트 내부 동적 상대 경로)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(CURRENT_DIR, "..", "models")

WEIGHTS_PATHS = {
    "신호": os.path.join(MODEL_DIR, "model_객체탐지_신호위반.pt"),
    "안전모": os.path.join(MODEL_DIR, "model_객체탐지_안전모.pt"),
    "중앙": os.path.join(MODEL_DIR, "model_객체탐지_중앙선침범.pt"),
    "진로": os.path.join(MODEL_DIR, "model_객체탐지_진로변경.pt")
}

# 업로드된 영상을 임시 다운받을 폴더
TEMP_DIR = "temp_uploads"
os.makedirs(TEMP_DIR, exist_ok=True)

class AnalyzeResponse(BaseModel):
    total_frames: int
    object_count: int
    records: list

@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_video(file: UploadFile = File(...)):
    print(f"[{file.filename}] 영상을 서버로 업로드 받는 중...")
    
    # 임시 파일로 저장
    temp_video_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_{file.filename}")
    with open(temp_video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    print("저장 완료. YOLOv5 분석을 🚀 시작합니다!")
    
    # 딥러닝 추론 (시간이 꽤 걸리므로 콘솔에 로그가 찍힘)
    # video_id를 파일 이름 기반으로 자동 생성
    video_id_str = f"VID_{file.filename.split('.')[0].upper()[:5]}"
    
    try:
        result_dict = analyze_video_with_yolo(temp_video_path, WEIGHTS_PATHS, video_id=video_id_str)
    except Exception as e:
        print("분석 중 오류 발생:", e)
        return {"total_frames": 0, "object_count": 0, "records": []}
    finally:
        # 하드디스크 낭비 방지를 위해 임시 영상 파일 즉시 삭제
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
    
    print("✅ 영상 분석 및 DB 추출 완료! 프론트엔드로 전송합니다.")
    
    return {
        "total_frames": result_dict["total_frames"],
        "object_count": len(result_dict["records"]),
        "records": result_dict["records"]
    }

# 중요: 이 코드가 제일 마지막에 와야 합니다! (api 라우팅이 먼저 적용되어야 함)
# 프론트엔드 폴더 전체를 정적으로 서빙 (마치 로컬 웹서버처럼 구동)
FRONTEND_DIR = os.path.join(CURRENT_DIR, "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
