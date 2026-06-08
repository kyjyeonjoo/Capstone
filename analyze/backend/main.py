import os
import shutil
import uuid
import requests
from typing import Optional, List
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Request
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
    print("WARNING: Supabase URL or KEY not found!")
    supabase = None

if not OPENROUTER_API_KEY:
    print("WARNING: OPENROUTER_API_KEY not found in .env!")

# yolo_inference.py에서 로직 가져오기
from yolo_inference import analyze_video_with_yolo
from fault_analyzer import analyze_fault, enrich_case_laws, fetch_law_api_cases

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_DIR = os.path.join(CURRENT_DIR, "..", "models")
WEIGHTS_PATHS = {
    "통합": os.path.join(MODEL_DIR, "best.pt")
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

class ChatRequest(BaseModel):
    user_question: str
    accident_data: Optional[dict] = None
    result_id: Optional[int] = None

class UserAuth(BaseModel):
    email: str
    password: str
    nickname: Optional[str] = None

class EmailCheck(BaseModel):
    email: str

class ResetPassword(BaseModel):
    email: str

class RecoveryTokenExchange(BaseModel):
    token_hash: Optional[str] = None
    code: Optional[str] = None

class PasswordResetConfirm(BaseModel):
    token_hash: Optional[str] = None   # 신형 Supabase
    access_token: Optional[str] = None # 구형 Implicit 방식
    new_password: str

class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    password: Optional[str] = None

from supabase import ClientOptions

@app.post("/api/update-profile")
def update_profile(req: Request, data: ProfileUpdate):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")
        
    auth_header = req.headers.get("Authorization")
    print(f"[DEBUG] update_profile - auth_header received: {auth_header}")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 토큰이 없습니다.")
    token = auth_header.split(" ")[1]
    print(f"[DEBUG] update_profile - extracted token value: {token}")
    
    try:
        update_data = {}
        if data.password:
            update_data["password"] = data.password
        if data.nickname:
            update_data["data"] = {"nickname": data.nickname}
            update_data["user_metadata"] = {"nickname": data.nickname} # Supabase Auth REST API 명세 호환성 보장
            
        # Supabase Python 클라이언트의 세션 에러("Auth session missing!")를 우회하기 위해 REST API 직접 호출
        url = f"{SUPABASE_URL}/auth/v1/user"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        response = requests.put(url, headers=headers, json=update_data)
        print(f"[update-profile] Supabase 응답: {response.status_code} {response.text[:300]}")

        if not response.ok:
            try:
                err_body = response.json()
                # Supabase는 버전에 따라 msg / message / error_description 중 하나를 씀
                error_msg = (
                    err_body.get("msg")
                    or err_body.get("message")
                    or err_body.get("error_description")
                    or err_body.get("error")
                    or "회원정보 변경 실패"
                )
            except Exception:
                error_msg = response.text or "회원정보 변경 실패"
            raise HTTPException(status_code=response.status_code, detail=error_msg)
            
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

class ResetPasswordRequest(BaseModel):
    email: str

class RefreshRequest(BaseModel):
    refresh_token: str

@app.post("/api/auth/pkce-callback")
def pkce_callback(data: RecoveryTokenExchange):
    """Supabase 비밀번호 재설정 링크의 토큰을 실제 세션(access_token)으로 교환합니다.

    Supabase 신형(sb_* 키) 프로젝트: ?token_hash=HASH&type=recovery
    Supabase PKCE 방식:              ?code=CODE&type=recovery
    Supabase 구형 Implicit 방식:     #access_token=JWT&type=recovery (프론트에서 직접 처리)
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    api_headers = {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json"
    }

    # ── 방법 1: token_hash 방식 (Supabase 신형 이메일 링크 기본값) ──
    if data.token_hash:
        print(f"[Recovery] token_hash 방식 시도 (앞 10자: {data.token_hash[:10]}...)")
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/verify",
                headers=api_headers,
                json={"type": "recovery", "token_hash": data.token_hash}
            )
            print(f"[Recovery] /verify 응답: {resp.status_code} {resp.text[:200]}")
            if resp.ok:
                token_data = resp.json()
                at = token_data.get("access_token")
                rt = token_data.get("refresh_token")
                if at:
                    print("[Recovery] token_hash → /verify 성공")
                    return {"access_token": at, "refresh_token": rt}
        except Exception as e:
            print(f"[Recovery] token_hash → /verify 예외: {e}")

    # ── 방법 2: PKCE code 방식 ──
    if data.code:
        print(f"[Recovery] PKCE code 방식 시도 (앞 10자: {data.code[:10]}...)")
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
                headers=api_headers,
                json={"auth_code": data.code}
            )
            print(f"[Recovery] grant_type=pkce 응답: {resp.status_code} {resp.text[:200]}")
            if resp.ok:
                token_data = resp.json()
                at = token_data.get("access_token")
                rt = token_data.get("refresh_token")
                if at:
                    print("[Recovery] PKCE code → 교환 성공")
                    return {"access_token": at, "refresh_token": rt}
        except Exception as e:
            print(f"[Recovery] PKCE code 예외: {e}")

        # PKCE code를 token_hash로도 시도
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/verify",
                headers=api_headers,
                json={"type": "recovery", "token_hash": data.code}
            )
            if resp.ok:
                token_data = resp.json()
                at = token_data.get("access_token")
                rt = token_data.get("refresh_token")
                if at:
                    print("[Recovery] code를 token_hash로 /verify 성공")
                    return {"access_token": at, "refresh_token": rt}
        except Exception as e:
            print(f"[Recovery] code → /verify 예외: {e}")

    print("[Recovery] 모든 방법 실패")
    raise HTTPException(
        status_code=400,
        detail="비밀번호 재설정 링크가 만료되었거나 이미 사용된 링크입니다. 비밀번호 찾기를 다시 요청해주세요."
    )


@app.post("/api/reset-password-confirm")
def reset_password_confirm(data: PasswordResetConfirm):
    """비밀번호 재설정 링크의 token_hash와 새 비밀번호를 받아 한 번에 처리합니다.
    프론트엔드에 JWT를 저장하지 않아도 되는 더 안전한 방식입니다."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    if not data.new_password or len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="비밀번호는 6자 이상이어야 합니다.")

    api_headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    user_id = None

    # ── Step 1: 토큰으로 user_id 획득 ──
    if data.token_hash:
        print(f"[PasswordReset] token_hash로 검증 시도 (앞 10자: {data.token_hash[:10]}...)")
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/verify",
                headers=api_headers,
                json={"type": "recovery", "token_hash": data.token_hash}
            )
            print(f"[PasswordReset] /verify 응답: {resp.status_code} {resp.text[:300]}")
            if resp.ok:
                body = resp.json()
                user_id = (body.get("user") or {}).get("id") or body.get("id")
        except Exception as e:
            print(f"[PasswordReset] /verify 예외: {e}")

    if not user_id and data.access_token:
        print(f"[PasswordReset] access_token으로 user_id 조회")
        try:
            resp = requests.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={**api_headers, "Authorization": f"Bearer {data.access_token}"}
            )
            print(f"[PasswordReset] /user 응답: {resp.status_code} {resp.text[:300]}")
            if resp.ok:
                user_id = resp.json().get("id")
        except Exception as e:
            print(f"[PasswordReset] /user 예외: {e}")

    if not user_id:
        raise HTTPException(status_code=400,
            detail="비밀번호 재설정 링크가 만료되었거나 유효하지 않습니다. 다시 요청해주세요.")

    # ── Step 2: 서비스 키로 비밀번호 직접 변경 ──
    print(f"[PasswordReset] 관리자 API로 비밀번호 변경 (user_id={user_id})")
    try:
        resp = requests.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers={
                **api_headers,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            json={"password": data.new_password}
        )
        print(f"[PasswordReset] admin 변경 응답: {resp.status_code} {resp.text[:300]}")
        if not resp.ok:
            err = resp.json()
            msg = err.get("message") or err.get("msg") or err.get("error_description") or "비밀번호 변경 실패"
            raise HTTPException(status_code=400, detail=msg)
        return {"message": "비밀번호가 성공적으로 변경되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh-token")
def refresh_token_endpoint(data: RefreshRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        res = supabase.auth.refresh_session(data.refresh_token)
        return {
            "token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="토큰 갱신 실패: " + str(e))


# ──────────────────────────────────────────
# 인증 API
# ──────────────────────────────────────────

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
        res = supabase.auth.sign_in_with_password({"email": user.email, "password": user.password})
        
        nickname = "사용자"
        if res.user and getattr(res.user, 'user_metadata', None) and "nickname" in res.user.user_metadata:
            nickname = res.user.user_metadata["nickname"]
            
        return {
            "message": "로그인 성공",
            "token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
            "user": res.user.email,
            "nickname": nickname
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 잘못되었습니다.")

@app.post("/api/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        print(f"[비밀번호 재설정] 이메일 발송 시도: {req.email}")

        # 브라우저가 보낸 Origin 또는 Referer 헤더로 앱 URL 자동 감지
        origin = request.headers.get("origin") or request.headers.get("referer", "")
        # Referer가 경로까지 포함할 수 있으므로 루트만 사용
        if origin:
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            app_url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            app_url = "http://localhost:8000"  # 기본값 (필요시 수정)

        print(f"[비밀번호 재설정] redirect_to → {app_url}")
        supabase.auth.reset_password_email(req.email, {"redirect_to": app_url})
        return {"message": "비밀번호 재설정 링크가 발송되었습니다."}
    except Exception as e:
        print(f"[비밀번호 재설정] 오류: {e}")
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

        if not user_id:
            return {"results": []}

        res = (supabase.table("analysis_result")
               .select("""
                   result_id, fault_a, fault_b, summary, created_at,
                   video_record!inner(video_id, original_name, upload_time, user_id),
                   accident_type(accident_name)
               """)
               .eq("video_record.user_id", user_id)
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
        # 1. analysis_result 조회
        res = (supabase.table("analysis_result")
               .select("*, accident_type(*), video_record(*)")
               .eq("result_id", result_id)
               .single()
               .execute())
        data = res.data
        if not data:
            raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")

        video_id = data.get("video_id")
        
        # 2. 관련 event 조회 (감지된 위반 복원용)
        detected_events = []
        if video_id:
            try:
                event_res = supabase.table("event").select("event_type").eq("video_id", video_id).execute()
                detected_events = [e["event_type"] for e in event_res.data] if event_res.data else []
            except Exception as e:
                print(f"[DB] event 조회 오류: {e}")

        # 3. 관련 object_detection 조회 (YOLO 검출 테이블 복원용)
        records = []
        if video_id:
            try:
                det_res = supabase.table("object_detection").select("*").eq("video_id", video_id).execute()
                for det in (det_res.data or []):
                    records.append({
                        "frame": int(det.get("timestamp", 0.0) * 5),
                        "object_type": det.get("object_type"),
                        "confidence": det.get("confidence")
                    })
            except Exception as e:
                print(f"[DB] object_detection 조회 오류: {e}")

        # 4. 관련 case_law 판례 조회
        case_laws = []
        accident_type_id = data.get("accident_type_id")
        if accident_type_id:
            try:
                case_res = supabase.table("case_law").select(
                    "case_title, case_number, court_name, decision_date, summary, fault_ratio"
                ).eq("accident_type_id", accident_type_id).limit(3).execute()
                raw_cases = case_res.data or []
                # 동적 복원 및 가공 헬퍼 통과!
                case_laws = enrich_case_laws(raw_cases, detected_events)
            except Exception as e:
                print(f"[DB] case_law 조회 오류: {e}")
        if not case_laws and detected_events:
            internal_events = list(detected_events)
            if "교차로진입" in detected_events and "진로변경" in detected_events:
                internal_events.append("측면합류충돌위험")
            case_laws = fetch_law_api_cases(internal_events, limit=3)

        # 5. 프론트엔드가 요구하는 포맷으로 필드 병합 및 바인딩
        data["detected_events"] = detected_events
        data["records"] = records
        data["case_laws"] = case_laws
        data["accident_type_name"] = data.get("accident_type", {}).get("accident_name") if data.get("accident_type") else "불명확"
        data["confidence_level"] = "높음" if len(detected_events) > 0 else "보통"

        return data
    except Exception as e:
        print(f"상세 조회 오류: {e}")
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
            # 같은 사용자의 중복 파일명 방지: 이미 동일 이름 존재 시 번호 추가
            upload_name = file.filename
            if user_id:
                base, ext = os.path.splitext(upload_name)
                existing = supabase.table("video_record").select("original_name").eq("user_id", user_id).execute()
                existing_names = {r["original_name"] for r in (existing.data or [])}
                counter = 1
                while upload_name in existing_names:
                    upload_name = f"{base}({counter}){ext}"
                    counter += 1

            vr_res = supabase.table("video_record").insert({
                "user_id":       user_id,
                "original_name": upload_name,
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
        fps = yolo_result.get("fps", 5.0)
        total_video_frames = yolo_result.get("total_video_frames", yolo_result["total_frames"] * (fps / 5.0))
        duration = round(total_video_frames / max(fps, 0.1), 3)

        if supabase and video_id:
            supabase.table("video_record").update({
                "duration": duration,
                "status":   "판단중",
            }).eq("video_id", video_id).execute()

        # ② 과실비율 판단
        print("🤖 과실비율 판단 시작...")
        fault_result = analyze_fault(
            video_id     = video_id or -1,
            total_frames = yolo_result["total_frames"],
            records      = yolo_result["records"],
            fps          = fps,
        )

        # 완료 상태 업데이트
        if supabase and video_id:
            supabase.table("video_record").update({"status": "완료"}).eq("video_id", video_id).execute()

        print("✅ 전체 분석 완료!")

    except Exception as e:
        import traceback
        traceback.print_exc() # 상세 에러 추적 출력 추가
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

@app.post("/api/chat")
def chat_with_ai(data: ChatRequest, authorization: Optional[str] = Header(None)):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API key is missing.")

    # ── 인증 필수화: 로그인하지 않은 사용자는 채팅 불가 ──
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    user_id = None
    try:
        token = authorization.replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        user_id = user.user.id if user and user.user else None
    except Exception as e:
        print(f"[Auth] 토큰 확인 실패: {e}")
        raise HTTPException(status_code=401, detail="유효하지 않은 인증 토큰입니다. 다시 로그인해주세요.")

    if not user_id:
        raise HTTPException(status_code=401, detail="인증된 사용자를 확인할 수 없습니다.")

    if not is_traffic_chat_question(data.user_question):
        save_chat_history_safe(
            user_id=user_id,
            question=data.user_question,
            answer=CHAT_DOMAIN_REJECTION,
            result_id=data.result_id,
        )
        return {"answer": CHAT_DOMAIN_REJECTION}

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = (
        "당신은 'AI 교통사고 법률 보조 시스템'의 전문 상담 챗봇입니다. "
        "답변 가능 범위는 교통사고, 교통법규, 과실 비율, 보험, 사고 관련 법률과 판례로 제한합니다. "
        "위 주제에 해당하지 않는 질문에는 다음 문장만 답변하세요: "
        f"'{CHAT_DOMAIN_REJECTION}' "
        "사용자가 제공한 블랙박스 영상 분석 결과를 바탕으로 사고 과실 비율을 추정하고, 관련 법률 및 대법원 판례를 근거로 전문적인 조언을 제공합니다. "
        "분석 결과에 연동된 도로교통법 조문과 판례 요약(사실관계 및 대법원 판결의 요지)을 최대한 자세하게 해설해 주세요. "
        "친절하고 명확하게 답변하며, 분석된 결과가 있으면 이를 십분 활용하여 답변하세요."
    )

    if data.accident_data:
        system_prompt += f"\n\n[영상 분석 결과 컨텍스트 (적용 법규 및 관련 판례 정보 포함)]\n{str(data.accident_data)}"

    models_to_try = [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    ]

    # 과거 대화 내용 불러오기 (result_id가 있을 때만 해당 분석의 이전 대화 로드)
    history_messages = []
    if data.result_id:
        try:
            hist_res = (supabase.table("chat_history")
                        .select("question, answer")
                        .eq("user_id", user_id)
                        .eq("result_id", data.result_id)
                        .order("created_at", desc=False)
                        .execute())
            for chat in (hist_res.data or []):
                history_messages.append({"role": "user", "content": chat["question"]})
                if chat.get("answer"):
                    history_messages.append({"role": "assistant", "content": chat["answer"]})
        except Exception as e:
            print(f"[DB] 이전 대화 내역 조회 실패: {e}")

    for model in models_to_try:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": data.user_question})

        payload = {
            "model": model,
            "messages": messages
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            res_data = response.json()
            answer = res_data["choices"][0]["message"]["content"]

            # ── DB 저장: 로그인 사용자만 저장 (user_id 보장됨) ──
            # result_id가 None이면 일반 채팅으로 저장 (영상 분석에 종속되지 않음)
            save_chat_history_safe(
                user_id=user_id,
                question=data.user_question,
                answer=answer,
                result_id=data.result_id,
            )

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


@app.get("/api/chat/history")
def get_chat_history(
    result_id: Optional[int] = None,
    authorization: Optional[str] = Header(None)
):
    """특정 분석 건 또는 사용자의 전체 과거 채팅 기록 반환."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        token = (authorization or "").replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        user_id = user.user.id if user and user.user else None

        if not user_id:
            return {"history": []}

        query = supabase.table("chat_history").select("*").eq("user_id", user_id)
        if result_id is not None:
            query = query.eq("result_id", result_id)
            
        res = query.order("created_at", desc=False).execute()
        return {"history": res.data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/chat/history")
def delete_chat_history(result_id: int, authorization: Optional[str] = Header(None)):
    """특정 분석 건의 채팅 기록만 삭제."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        token = (authorization or "").replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        user_id = user.user.id if user and user.user else None
        if not user_id:
            raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

        # 해당 result_id가 본인 것인지 확인
        res = supabase.table("analysis_result").select("*, video_record(user_id)").eq("result_id", result_id).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")
        video_record = res.data.get("video_record")
        if not video_record or video_record.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="권한이 없습니다.")

        del_res = (supabase.table("chat_history")
                   .delete()
                   .eq("result_id", result_id)
                   .eq("user_id", user_id)
                   .execute())
        deleted_count = len(del_res.data) if del_res.data else 0
        return {"message": f"채팅 기록 {deleted_count}건이 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/results/{result_id}")
def delete_result(result_id: int, authorization: Optional[str] = Header(None)):
    """특정 분석 결과 및 연관 데이터(video_record 등) 삭제."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        token = (authorization or "").replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        user_id = user.user.id if user and user.user else None
        if not user_id:
            raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

        # 1. 먼저 본인의 결과가 맞는지 확인하기 위해 조회
        res = supabase.table("analysis_result").select("*, video_record(*)").eq("result_id", result_id).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")
        
        video_record = res.data.get("video_record")
        if not video_record or video_record.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="권한이 없습니다.")

        video_id = video_record.get("video_id")

        # 2. 관련 하위 데이터들 순차적으로 삭제 (외래키 무결성 예방을 위해 자식 테이블부터 삭제)
        try:
            # 2-1. chat_history 삭제 (채팅 내역) - 본인의 해당 분석에 묶인 채팅만
            chat_del = (supabase.table("chat_history")
                        .delete()
                        .eq("result_id", result_id)
                        .eq("user_id", user_id)
                        .execute())
            deleted_count = len(chat_del.data) if chat_del.data else 0
            print(f"[Delete] chat_history {deleted_count}건 삭제 (result_id={result_id})")
        except Exception as e:
            print(f"[Delete] chat_history 삭제 실패 (result_id={result_id}): {e}")

        if video_id:
            try:
                # 2-2. event 삭제
                supabase.table("event").delete().eq("video_id", video_id).execute()
            except Exception as e:
                print(f"[Delete] event 삭제 실패: {e}")

            try:
                # 2-3. object_detection 삭제
                supabase.table("object_detection").delete().eq("video_id", video_id).execute()
            except Exception as e:
                print(f"[Delete] object_detection 삭제 실패: {e}")

            try:
                # 2-4. tracking 삭제
                supabase.table("tracking").delete().eq("video_id", video_id).execute()
            except Exception as e:
                print(f"[Delete] tracking 삭제 실패: {e}")

        # 2-5. 부모 테이블인 analysis_result 삭제
        supabase.table("analysis_result").delete().eq("result_id", result_id).execute()

        # 2-6. 최상위 부모 테이블인 video_record 삭제
        if video_id:
            try:
                supabase.table("video_record").delete().eq("video_id", video_id).execute()
            except Exception as e:
                print(f"[Delete] video_record 삭제 실패: {e}")

        return {"message": "기록이 성공적으로 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class RenameRequest(BaseModel):
    new_name: str

CHAT_DOMAIN_KEYWORDS = (
    "교통", "사고", "교통사고", "차량", "자동차", "차대차", "블랙박스", "블박",
    "과실", "과실비율", "가해", "피해", "위반", "법규", "도로교통법", "법률",
    "판례", "대법원", "법원", "소송", "합의", "보험", "보험사", "손해배상",
    "대인", "대물", "보상", "수리비", "정지선", "신호", "신호위반", "중앙선",
    "진로변경", "차선변경", "좌회전", "우회전", "직진", "교차로", "횡단보도",
    "노외진입", "회전교차로", "추돌", "충돌", "접촉", "후미", "급정거",
    "상대차", "운전자", "운행", "안전거리", "속도", "과속", "위자료",
    "차", "차선", "차로", "차주", "운전", "운전자", "상대", "상대방", "상대측",
    "내차", "내 차", "상대차량", "상대 차량", "사고처리", "사고 처리", "처리",
    "책임", "비율", "몇대몇", "몇 대 몇", "7:3", "8:2", "6:4", "5:5",
    "70:30", "80:20", "60:40", "50:50", "100:0", "0:100",
    "경찰", "신고", "진단서", "수리", "견적", "렌트", "렌트카", "대차",
    "분쟁", "분심위", "소송", "민사", "형사", "벌점", "범칙금", "과태료",
    "사거리", "삼거리", "골목", "주차장", "고속도로", "회전", "합류", "끼어들기",
    "일시정지", "정차", "주정차", "후진", "유턴", "양보", "방향지시등", "깜빡이",
    "속도위반", "안전운전", "전방주시", "급제동", "꼬리물기",
    "청구", "배상", "손해", "손실", "합의금", "치료비", "병원", "입원", "통원",
    "상해", "부상", "진료", "후유증", "휴업손해", "감가", "격락손해",
    "정비소", "공업사", "폐차", "견인", "견인비", "번호판", "차량번호",
    "목격자", "cctv", "CCTV", "영상", "증거", "진술", "조사", "현장",
    "가드레일", "표지판", "표지", "노면표시", "황색선", "백색선", "실선",
    "점선", "버스", "택시", "화물차", "트럭", "오토바이", "이륜차",
    "자전거", "보행자", "어린이보호구역", "스쿨존", "횡단", "불법주차",
    "주차", "출차", "입차", "개문", "문콕", "후방", "측면", "정면",
    "앞차", "뒷차", "선행차", "후행차", "차간거리", "끼어듦", "급차선",
    "항소", "고소", "고발", "처벌", "면허", "벌금", "합의서", "내용증명",
    "과실상계", "구상권", "자차", "자손", "자상", "무보험", "책임보험",
)

CHAT_EXCLUDED_KEYWORDS = (
    "점심", "저녁", "아침", "메뉴", "맛집", "레시피", "요리", "날씨", "여행",
    "숙소", "호텔", "게임", "영화", "드라마", "노래", "음악", "주식", "코인",
    "파이썬", "자바", "코딩", "코드", "프로그램", "개발", "수학", "번역",
)

CHAT_DOMAIN_REJECTION = (
    "저는 교통사고 법률 상담 전문 챗봇으로, 교통 관련 질문에만 답변드릴 수 있습니다. "
    "교통사고나 관련 법률에 대해 궁금하신 점이 있으시면 질문해 주세요."
)

def is_traffic_chat_question(question: str) -> bool:
    normalized = (question or "").replace(" ", "").lower()
    if not normalized:
        return False
    if any(keyword.replace(" ", "").lower() in normalized for keyword in CHAT_DOMAIN_KEYWORDS):
        return True
    if any(keyword.replace(" ", "").lower() in normalized for keyword in CHAT_EXCLUDED_KEYWORDS):
        return False

    # 분석 결과를 선택한 뒤 이어지는 짧은 후속 질문은 맥락상 교통사고 질문으로 허용합니다.
    followup_phrases = (
        "왜", "맞아", "맞나요", "틀려", "틀린", "이유", "근거", "설명", "자세히",
        "어떻게", "뭐야", "뭔데", "가능", "불가능", "더", "다시", "정리", "요약",
        "상세", "그러면", "그럼", "이거", "저거", "결과", "판단", "비교",
    )
    if any(phrase in normalized for phrase in followup_phrases):
        return len(normalized) <= 60

    # 아주 짧은 일상형 후속 질문은 분석 결과 맥락에서 나온 것으로 보고 허용합니다.
    # 명확히 제외된 주제는 위에서 이미 걸러집니다.
    return len(normalized) <= 18

def save_chat_history_safe(user_id: str, question: str, answer: str, result_id: Optional[int] = None):
    try:
        insert_payload = {
            "user_id": user_id,
            "question": question,
            "answer": answer,
        }
        if result_id is not None:
            insert_payload["result_id"] = result_id

        save_res = supabase.table("chat_history").insert(insert_payload).execute()
        if save_res.data:
            print(f"[DB] chat_history 저장 성공 (user_id={user_id}, result_id={result_id})")
        else:
            print(f"[DB] chat_history 저장 응답 비어있음: {save_res}")
    except Exception as e:
        print(f"[DB] chat_history 저장 실패 (user_id={user_id}, result_id={result_id}): {e}")

@app.put("/api/results/{result_id}/rename")
def rename_result(result_id: int, req: RenameRequest, authorization: Optional[str] = Header(None)):
    """분석 결과의 영상 파일 이름(제목) 변경."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        token = (authorization or "").replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        user_id = user.user.id if user and user.user else None
        if not user_id:
            raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

        res = supabase.table("analysis_result").select("*, video_record(*)").eq("result_id", result_id).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")

        video_record = res.data.get("video_record")
        if not video_record or video_record.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="권한이 없습니다.")

        video_id = video_record.get("video_id")
        if video_id:
            orig_name = video_record.get("original_name", "")
            ext = os.path.splitext(orig_name)[1] if orig_name else ".mp4"
            base_name = req.new_name if req.new_name.endswith(ext) else f"{req.new_name}{ext}"

            # 같은 사용자의 다른 영상과 이름 중복 방지
            existing = supabase.table("video_record").select("original_name").eq("user_id", user_id).neq("video_id", video_id).execute()
            existing_names = {r["original_name"] for r in (existing.data or [])}
            final_name = base_name
            counter = 1
            name_base = req.new_name if not req.new_name.endswith(ext) else req.new_name[:-len(ext)]
            while final_name in existing_names:
                final_name = f"{name_base}({counter}){ext}"
                counter += 1

            supabase.table("video_record").update({"original_name": final_name}).eq("video_id", video_id).execute()

        return {"message": "이름이 성공적으로 변경되었습니다.", "new_name": final_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# 중요: 이 코드가 제일 마지막에 와야 합니다! (api 라우팅이 먼저 적용되어야 함)
FRONTEND_DIR = os.path.join(CURRENT_DIR, "..", "frontend")

# HTML 파일은 캐시 없이 항상 최신 버전을 서빙 (JS/CSS 변경 시 즉시 반영)
from fastapi.responses import FileResponse

@app.get("/")
@app.get("/index.html")
async def serve_index():
    resp = FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# JS/CSS 등 정적 파일은 StaticFiles로 서빙
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
