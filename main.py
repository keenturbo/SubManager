import sqlite3
import datetime
import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import os

# --- 配置区 ---
BARK_KEY = os.getenv("BARK_KEY", "你的barkkey")
DB_FILE = "/data/sub.db"  # 修改：数据库放在 /data 目录

# --- 数据模型（支持到期日期） ---
class Subscription(BaseModel):
    name: str
    price: float
    expire_date: str  # 格式：2026-01-18
    category: str
    color: str = "blue"

# --- 数据库初始化 ---
def init_db():
    # 确保 /data 目录存在
    os.makedirs("/data", exist_ok=True)
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, price REAL, expire_date TEXT, 
                  category TEXT, color TEXT)''')
    conn.commit()
    conn.close()

# --- 核心逻辑：计算剩余天数 ---
def calculate_days_left(expire_date_str):
    today = datetime.date.today()
    expire_date = datetime.datetime.strptime(expire_date_str, "%Y-%m-%d").date()
    days_left = (expire_date - today).days
    return expire_date_str, days_left

# --- Bark 通知任务 ---
def check_and_notify():
    print(f"[{datetime.datetime.now()}] 开始检查订阅到期情况...")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, price, expire_date FROM subs")
    subs = c.fetchall()
    conn.close()

    for sub in subs:
        name, price, expire_date = sub
        _, days_left = calculate_days_left(expire_date)
        
        # 提前7天内提醒
        if days_left <= 7 and days_left >= 0:
            title = f"【订阅提醒】{name} 即将到期"
            if days_left == 0:
                body = f"您的 {name} (¥{price}) 今天到期！"
            else:
                body = f"您的 {name} (¥{price}) 将在 {days_left} 天后到期！"
            
            url = f"https://api.day.app/{BARK_KEY}/{title}/{body}"
            try:
                requests.get(url, timeout=5)
                print(f"✅ 推送成功: {name}")
            except Exception as e:
                print(f"❌ 推送失败: {e}")

# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_notify, 'cron', hour=9, minute=0)
    scheduler.start()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 提供前端页面 ---
@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

# --- API 接口 ---
@app.get("/api/subs")
def get_subs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM subs")
    rows = c.fetchall()
    conn.close()
    
    result = []
    total_cost = 0
    upcoming_count = 0
    
    for row in rows:
        expire_date, days_left = calculate_days_left(row[3])
        total_cost += row[2]
        if days_left <= 7:
            upcoming_count += 1
            
        result.append({
            "id": row[0],
            "name": row[1],
            "price": row[2],
            "expire_date": row[3],
            "category": row[4],
            "color": row[5],
            "days_left": days_left
        })
    
    result.sort(key=lambda x: x['days_left'])
    
    return {
        "subscriptions": result,
        "summary": {
            "total_cost": round(total_cost, 2),
            "upcoming": upcoming_count
        }
    }

@app.post("/api/subs")
def add_sub(sub: Subscription):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO subs (name, price, expire_date, category, color) VALUES (?, ?, ?, ?, ?)",
              (sub.name, sub.price, sub.expire_date, sub.category, sub.color))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/subs/{sub_id}")
def delete_sub(sub_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM subs WHERE id=?", (sub_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}