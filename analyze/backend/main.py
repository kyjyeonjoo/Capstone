import os
import shutil
import uuid
from typing import Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from dotenv import load_dotenv

# 환경변수 로드
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(CURRENT_DIR, "..", "..", "test", ".env")
load_dotenv(dotenv_path=ENV_PATH)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("WARNING: Supabase URL or KEY not found!")
    supabase = None

from yolo_inference import analyze_video_with_yolo
from fault_analyzer import analyze_fault

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_DIR = os.path.join(CURRENT_DIR, "..", "models")
WEIGHTS_PATHS = {
    "신호":  os.path.join(MODEL_DIR, "model_객체탐지_신호위반.pt"),
    "안전모": os.path.join(MODEL_DIR, "model_객체탐지_안전모.pt"),
    "중앙":  os.path.join(MODEL_DIR, "model_객체탐지_중앙선침범.pt"),
    "진로":  os.path.join(MODEL_DIR, "model_객체탐지_진로변경.pt"),
}

TEMP_DIR = "temp_uploads"
os.makedirs(TEMP_DIR, exist_ok=True)


# ──────────────────────────────────────────
# 응답 모델
# ──────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    # YOLO
    total_frames: int
    object_count: int
    records: list

    # 판단 결과
    situation_summary:   Optional[str] = None
    fault_ratio_a:       Optional[int] = None
    fault_ratio_b:       Optional[int] = None
    accident_cause:      Optional[str] = None
    legal_basis:         Optional[str] = None
    confidence_level:    Optional[str] = None
    detected_events:     list          = []
    accident_type_name:  Optional[str] = None
    result_id:           Optional[int] = None

case_laws:           list          = []

class UserAuth(BaseModel):
    email: str
    password: str

class ResetPasswordRequest(BaseModel):
    email: str


# ──────────────────────────────────────────
# 인증 API
# ──────────────────────────────────────────

@app.post("/api/signup")
def signup(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        res = supabase.auth.sign_up({"email": user.email, "password": user.password})
        return {"message": "회원가입이 완료되었습니다.", "user": res.user.email if res.user else user.email}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/login")
def login(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        res = supabase.auth.sign_in_with_password({"email": user.email, "password": user.password})
        return {"message": "로그인 성공", "token": res.session.access_token, "user": res.user.email}
    except Exception as e:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 잘못되었습니다.")

@app.post("/api/reset-password")
def reset_password(req: ResetPasswordRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        supabase.auth.reset_password_email(req.email)
        return {"message": "비밀번호 재설정 링크가 발송되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────────────────────────────────
# 분석 이력 조회 API
# ──────────────────────────────────────────

@app.get("/api/results")
def get_results(authorization: Optional[str] = Header(None)):
    """로그인 사용자의 분석 이력 목록 반환."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        token   = (authorization or "").replace("Bearer ", "")
        user    = supabase.auth.get_user(token)
        user_id = user.user.id if user and user.user else None

        res = (supabase.table("analysis_result")
               .select("""
                   result_id, fault_a, fault_b, summary, created_at,
                   video_record!inner(video_id, original_name, upload_time, user_id),
                   accident_type(accident_name)
               """)
               .order("created_at", desc=True)
               .limit(20)
               .execute())
        return {"results": res.data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/results/{result_id}")
def get_result_detail(result_id: int):
    """특정 분석 결과 상세 조회."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        res = (supabase.table("analysis_result")
               .select("*, accident_type(*), video_record(*)")
               .eq("result_id", result_id)
               .single()
               .execute())
        return res.data
    except Exception:
        raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")


# ──────────────────────────────────────────
# 핵심: 영상 분석 + 과실비율 판단
# ──────────────────────────────────────────

@app.post("/api/analyze")
def analyze_video(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
):
    print(f"[{file.filename}] 영상 수신 중...")

    # 임시 저장
    temp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_{file.filename}")
    with open(temp_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # 로그인 사용자 확인
    user_id = None
    if authorization and supabase:
        try:
            token   = authorization.replace("Bearer ", "")
            user    = supabase.auth.get_user(token)
            user_id = user.user.id if user and user.user else None
        except Exception:
            pass

    # video_record 먼저 INSERT → video_id 확보
    video_id = None
    if supabase:
        try:
            vr_res = supabase.table("video_record").insert({
                "user_id":       user_id,
                "original_name": file.filename,
                "file_path":     temp_path,
                "status":        "분석중",
            }).execute()
            video_id = vr_res.data[0]["video_id"] if vr_res.data else None
            print(f"[DB] video_record 생성 완료 (video_id={video_id})")
        except Exception as e:
            print(f"[DB] video_record 생성 실패: {e}")

    try:
        # ① YOLO 분석
        yolo_result = analyze_video_with_yolo(
            temp_path, WEIGHTS_PATHS,
            video_id=f"VID_{file.filename.split('.')[0].upper()[:5]}"
        )

        # duration 업데이트
        if supabase and video_id:
            supabase.table("video_record").update({
                "duration": yolo_result["total_frames"] / 5.0,
                "status":   "판단중",
            }).eq("video_id", video_id).execute()

        # ② 과실비율 판단
        print("🤖 과실비율 판단 시작...")
        fault_result = analyze_fault(
            video_id     = video_id or -1,
            total_frames = yolo_result["total_frames"],
            records      = yolo_result["records"],
        )

        # 완료 상태 업데이트
        if supabase and video_id:
            supabase.table("video_record").update({"status": "완료"}).eq("video_id", video_id).execute()

        print("✅ 전체 분석 완료!")

    except Exception as e:
        print(f"분석 오류: {e}")
        if supabase and video_id:
            supabase.table("video_record").update({"status": "실패"}).eq("video_id", video_id).execute()
        return {
            "total_frames": 0, "object_count": 0, "records": [],
            "situation_summary": f"분석 중 오류: {e}",
            "confidence_level": "낮음",
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "total_frames":      yolo_result["total_frames"],
        "object_count":      len(yolo_result["records"]),
        "records":           yolo_result["records"],
        "situation_summary": fault_result.get("situation_summary"),
        "fault_ratio_a":     fault_result.get("fault_ratio_a"),
        "fault_ratio_b":     fault_result.get("fault_ratio_b"),
        "accident_cause":    fault_result.get("accident_cause"),
        "legal_basis":       fault_result.get("legal_basis"),
        "confidence_level":  fault_result.get("confidence_level"),
        "detected_events":   fault_result.get("detected_events", []),
        "accident_type_name": fault_result.get("accident_type_name"),
        "result_id":         fault_result.get("result_id"),
        "case_laws":         fault_result.get("case_laws", []),
    }


# 프론트엔드 정적 서빙 (반드시 마지막)
FRONTEND_DIR = os.path.join(CURRENT_DIR, "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
