"""
test_supabase.py
Supabase 연동 확인용 테스트 스크립트
실행: python test_supabase.py
"""

import os
from dotenv import load_dotenv

# .env 로드
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(CURRENT_DIR, "..", "..", "test", ".env")
load_dotenv(dotenv_path=ENV_PATH)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

print("=" * 50)
print("Supabase 연동 테스트")
print("=" * 50)

# 1. 환경변수 확인
print("\n[1] 환경변수 확인")
if SUPABASE_URL:
    print(f"  ✅ SUPABASE_URL: {SUPABASE_URL[:30]}...")
else:
    print("  ❌ SUPABASE_URL 없음 → .env 파일 확인 필요")

if SUPABASE_KEY:
    print(f"  ✅ SUPABASE_KEY: {SUPABASE_KEY[:20]}...")
else:
    print("  ❌ SUPABASE_KEY 없음 → .env 파일 확인 필요")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\n.env 파일 경로나 내용을 확인하세요.")
    exit(1)

# 2. 클라이언트 생성
print("\n[2] Supabase 클라이언트 생성")
try:
    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("  ✅ 클라이언트 생성 성공")
except Exception as e:
    print(f"  ❌ 클라이언트 생성 실패: {e}")
    exit(1)

# 3. 테이블 조회 테스트
tables = [
    "accident_type",
    "fault_modifier",
    "case_law",
    "analysis_result",
    "object_detection",
    "tracking",
    "event",
    "video_record",
    "law",
    "chat_history",
]

print("\n[3] 테이블 접근 확인")
for table in tables:
    try:
        res = supabase.table(table).select("*").limit(1).execute()
        count = len(res.data)
        print(f"  ✅ {table} (조회 성공, 데이터 {count}건)")
    except Exception as e:
        print(f"  ❌ {table} → {e}")

print("\n" + "=" * 50)
print("테스트 완료!")
print("=" * 50)
