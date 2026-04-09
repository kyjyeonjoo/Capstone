from fastapi import FastAPI
from supabase import create_client
from dotenv import load_dotenv

import os

app = FastAPI()

load_dotenv()

# 🔑 Supabase 연결
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase = create_client(url, key)

@app.get("/")
def home():
    return {"message": "server running"}

@app.get("/test-db")
def test_db():
    response = supabase.table("users").insert({
        "name": "test"
    }).execute()

    return {"result": response.data}