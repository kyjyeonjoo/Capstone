import os
import shutil
import uuid
import requests
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from dotenv import load_dotenv

# 환경변수 로드 (.env 파일이 backend 폴더에 있음)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(CURRENT_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("WARNING: Supabase URL or KEY not found in .env!")
    supabase = None

if not OPENROUTER_API_KEY:
    print("WARNING: OPENROUTER_API_KEY not found in .env!")

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

from typing import Optional

class AnalyzeResponse(BaseModel):
    total_frames: int
    object_count: int
    records: list

class ChatRequest(BaseModel):
    user_question: str
    accident_data: Optional[dict] = None

class UserAuth(BaseModel):
    email: str
    password: str
    nickname: Optional[str] = None

class EmailCheck(BaseModel):
    email: str

class ResetPassword(BaseModel):
    email: str

class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    password: Optional[str] = None

from supabase import ClientOptions

@app.post("/api/update-profile")
def update_profile(req: Request, data: ProfileUpdate):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")
        
    auth_header = req.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 토큰이 없습니다.")
    token = auth_header.split(" ")[1]
    
    try:
        update_data = {}
        if data.password:
            update_data["password"] = data.password
        if data.nickname:
            update_data["data"] = {"nickname": data.nickname}
            
        # Supabase Python 클라이언트의 세션 에러("Auth session missing!")를 우회하기 위해 REST API 직접 호출
        url = f"{SUPABASE_URL}/auth/v1/user"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        response = requests.put(url, headers=headers, json=update_data)
        
        if not response.ok:
            error_msg = response.json().get("msg", "변경 실패")
            raise HTTPException(status_code=400, detail=error_msg)
            
        user_data = response.json()
        user_id = user_data.get("id")
        
        if data.nickname and user_id:
            try:
                supabase.table("users").update({"nickname": data.nickname}).eq("id", user_id).execute()
            except Exception as e:
                print("public.users 닉네임 업데이트 실패:", e)
            
        return {"message": "회원정보가 수정되었습니다.", "nickname": data.nickname}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/check-email")
def check_email(data: EmailCheck):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        res = supabase.table("users").select("email").eq("email", data.email).execute()
        if res.data and len(res.data) > 0:
            return {"exists": True, "message": "이미 가입된 이메일입니다."}
        return {"exists": False, "message": "사용 가능한 이메일입니다."}
    except Exception as e:
        raise HTTPException(status_code=400, detail="중복 확인 기능 에러 (users 테이블 확인 필요): " + str(e))

@app.post("/api/reset-password")
def reset_password(data: ResetPassword):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        supabase.auth.reset_password_email(data.email)
        return {"message": "비밀번호 재설정 이메일이 발송되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/signup")
def signup(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        # Supabase Auth 회원가입 (닉네임 데이터 추가)
        options = {}
        if user.nickname:
            options = {
                "data": {
                    "nickname": user.nickname
                }
            }
            
        res = supabase.auth.sign_up({
            "email": user.email, 
            "password": user.password,
            "options": options
        })
        
        return {"message": "회원가입이 완료되었습니다.", "user": res.user.email if res.user else user.email}
    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg.lower():
            raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
        raise HTTPException(status_code=400, detail=error_msg)

@app.post("/api/login")
def login(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        # Supabase Auth 로그인
        res = supabase.auth.sign_in_with_password({"email": user.email, "password": user.password})
        
        nickname = "사용자"
        if res.user and getattr(res.user, 'user_metadata', None) and "nickname" in res.user.user_metadata:
            nickname = res.user.user_metadata["nickname"]
            
        return {
            "message": "로그인 성공", 
            "token": res.session.access_token, 
            "user": res.user.email,
            "nickname": nickname
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 잘못되었습니다.")

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

@app.post("/api/chat")
def chat_with_ai(data: ChatRequest):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API key is missing.")
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    # 구성할 시스템 프롬프트
    system_prompt = (
        "당신은 'AI 교통사고 법률 보조 시스템'의 전문 상담 챗봇입니다. "
        "사용자가 제공한 블랙박스 영상 분석 결과를 바탕으로 사고 과실 비율을 추정하고, 관련 법률 및 대법원 판례를 근거로 전문적인 조언을 제공합니다. "
        "친절하고 명확하게 답변하며, 분석된 결과가 있으면 이를 십분 활용하여 답변하세요."
    )

    if data.accident_data:
        system_prompt += f"\n\n[영상 분석 결과 컨텍스트]\n{str(data.accident_data)}"
    
    models_to_try = [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    ]
    
    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": data.user_question}
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            res_data = response.json()
            answer = res_data["choices"][0]["message"]["content"]
            return {"answer": answer}
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                print(f"[경고] {model} 모델 접속량 초과(429). 다음 무료 모델로 재시도합니다...")
                continue
            else:
                print(f"OpenRouter API Error: {e}")
                print(response.text)
                raise HTTPException(status_code=500, detail="챗봇 응답을 가져오는 중 서버 오류가 발생했습니다.")
        except Exception as e:
            print(f"OpenRouter API Request Error: {e}")
            raise HTTPException(status_code=500, detail="챗봇 API 통신 중 알 수 없는 오류가 발생했습니다.")
            
    raise HTTPException(status_code=429, detail="현재 전 세계적으로 무료 AI 모델 사용량이 많아 접속이 지연되고 있습니다. 잠시 후 다시 시도해주세요.")

# 중요: 이 코드가 제일 마지막에 와야 합니다! (api 라우팅이 먼저 적용되어야 함)
# 프론트엔드 폴더 전체를 정적으로 서빙 (마치 로컬 웹서버처럼 구동)
FRONTEND_DIR = os.path.join(CURRENT_DIR, "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
