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
BARK_KEY = os.getenv("BARK_KEY", "你的Bark_Key_填在这里")  # 可通过环境变量传入
DB_FILE = "sub.db"

# --- 数据模型 ---
class Subscription(BaseModel):
    name: str
    price: float
    cycle_day: int
    category: str
    color: str = "blue"

# --- 数据库初始化 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, price REAL, cycle_day INTEGER, 
                  category TEXT, color TEXT)''')
    conn.commit()
    conn.close()

# --- 核心逻辑：计算下一次扣款日和剩余天数 ---
def calculate_next_bill(cycle_day):
    today = datetime.date.today()
    try:
        this_month_bill = datetime.date(today.year, today.month, cycle_day)
    except ValueError:
        this_month_bill = datetime.date(today.year, today.month, 28)

    if this_month_bill >= today:
        next_bill = this_month_bill
    else:
        if today.month == 12:
            next_bill = datetime.date(today.year + 1, 1, cycle_day)
        else:
            try:
                next_bill = datetime.date(today.year, today.month + 1, cycle_day)
            except ValueError:
                next_bill = datetime.date(today.year, today.month + 1, 28)
    
    days_left = (next_bill - today).days
    return next_bill.strftime("%Y-%m-%d"), days_left

# --- Bark 通知任务 ---
def check_and_notify():
    print(f"[{datetime.datetime.now()}] 开始检查订阅到期情况...")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, price, cycle_day FROM subs")
    subs = c.fetchall()
    conn.close()

    for sub in subs:
        name, price, cycle_day = sub
        _, days_left = calculate_next_bill(cycle_day)
        
        if days_left == 3 or days_left == 0:
            title = f"订阅续费提醒：{name}"
            body = f"您的 {name} 将在 {days_left} 天后扣款 {price} 元。"
            if days_left == 0:
                body = f"您的 {name} 今天扣款 {price} 元！"
            
            url = f"https://api.day.app/{BARK_KEY}/{title}/{body}"
            try:
                requests.get(url)
                print(f"推送成功: {name}")
            except Exception as e:
                print(f"推送失败: {e}")

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
    total_monthly = 0
    upcoming_count = 0
    
    for row in rows:
        next_date, days_left = calculate_next_bill(row[3])
        total_monthly += row[2]
        if days_left <= 7:
            upcoming_count += 1
            
        result.append({
            "id": row[0],
            "name": row[1],
            "price": row[2],
            "cycle_day": row[3],
            "category": row[4],
            "color": row[5],
            "next_date": next_date,
            "days_left": days_left
        })
    
    result.sort(key=lambda x: x['days_left'])
    
    return {
        "subscriptions": result,
        "summary": {
            "monthly_total": total_monthly,
            "yearly_total": total_monthly * 12,
            "upcoming": upcoming_count
        }
    }

@app.post("/api/subs")
def add_sub(sub: Subscription):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO subs (name, price, cycle_day, category, color) VALUES (?, ?, ?, ?, ?)",
              (sub.name, sub.price, sub.cycle_day, sub.category, sub.color))
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