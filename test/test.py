from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

# 🔑 Supabase 연결
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase = create_client(url, key)

response = supabase.table("users").insert({
    "name": "kyj"
}).execute()

print(response.data)