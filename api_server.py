import os, time, sqlite3, threading, logging
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import video_maker, yt_uploader, trend_radar

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("nexus.api")

app = FastAPI(title="NEXUS STUDIO PRO API")
# The compose file binds host ports to loopback; CORS is limited to local UI origins.
LOCAL_UI_ORIGINS = {
    "http://127.0.0.1:8502", "http://localhost:8502",
    "http://127.0.0.1:8503", "http://localhost:8503",
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(LOCAL_UI_ORIGINS),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

@app.middleware("http")
async def reject_cross_origin_mutations(request, call_next):
    # CORS alone does not prevent a browser from sending a forged state-changing request.
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in LOCAL_UI_ORIGINS:
        return JSONResponse(status_code=403, content={"detail": "Cross-origin mutation rejected"})
    return await call_next(request)

os.makedirs("export", exist_ok=True)
os.makedirs("output", exist_ok=True)
app.mount("/output", StaticFiles(directory="output"), name="output")

RADAR_INTERVAL_SEC = 300
AUTO_PRODUCE_ENABLED = True

def get_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/studio_data.db", check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_app_db():
    """Create the core application tables without overwriting existing user data."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL DEFAULT 'YouTube',
            yt_id TEXT NOT NULL DEFAULT '',
            persona TEXT NOT NULL DEFAULT '전문가 톤',
            subs INTEGER NOT NULL DEFAULT 0,
            views INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS pipeline_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT NOT NULL,
            title TEXT NOT NULL,
            script TEXT NOT NULL DEFAULT '',
            video_path TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT '최종컨펌 대기',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_created
            ON pipeline_jobs(id DESC);
    """)
    db.executescript("INSERT OR IGNORE INTO channels (name, platform, yt_id, persona) VALUES\n        ('Brain Glitch', 'YouTube', '', '심리 전문가 톤'),\n        ('Silent Signals', 'YouTube', '', '인간관계 전문가 톤'),\n        ('Unseen Truth', 'YouTube', '', '팩트체크 전문가 톤'),\n        ('Dark Files Global', 'YouTube', '', '미스터리 다큐 톤'),\n        ('99% Missed', 'YouTube', '', '생활 정보 전문가 톤'),\n        ('Money Glitch', 'YouTube', '', '경제 분석가 톤'),\n        ('Secret Vault 24', 'YouTube', '', '자산·습관 전문가 톤'),\n        ('Future Leak', 'YouTube', '', 'AI·기술 분석가 톤'),\n        ('30Sec Shift', 'YouTube', '', '건강 정보 전문가 톤'),\n        ('Why Nobody Tells', 'YouTube', '', '지식 큐레이터 톤');")
    db.commit()
    db.close()

def get_oa_key():
    db = get_db()
    try:
        r = db.execute("SELECT value FROM settings WHERE key='oa'").fetchone()
        return r["value"] if r else ""
    finally:
        db.close()

def run_make_video(ch_name: str, persona: str, topic: str):
    if not topic or not topic.strip():
        raise ValueError("topic must not be empty")
    mp4, title, script = video_maker.render_pro_short(ch_name, persona, topic, get_oa_key())
    db = get_db()
    try:
        db.execute("INSERT INTO pipeline_jobs (channel_name, title, script, video_path, stage, created_at) VALUES (?,?,?,?,?,?)",
                   (ch_name, title, script, mp4, "최종컨펌 대기", datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.commit()
    finally:
        db.close()

def auto_produce_top_trends(count=3):
    db = trend_radar.init_radar_db()
    db.row_factory = sqlite3.Row
    made = 0
    try:
        top_rows = db.execute("SELECT * FROM trend_recommendations WHERE period_type='daily' AND is_global_top10 > 0 ORDER BY is_global_top10 ASC").fetchall()
        for r in top_rows:
            if made >= count:
                break
            exists = db.execute("SELECT 1 FROM auto_produced_topics WHERE topic=?", (r["topic"],)).fetchone()
            if exists:
                continue
            ch_row = db.execute("SELECT * FROM channels WHERE name=?", (r["matched_channel"],)).fetchone()
            if not ch_row:
                logger.warning("Skipping trend with unknown channel: %s", r["matched_channel"])
                continue
            run_make_video(r["matched_channel"], ch_row["persona"], r["topic"])
            db.execute("INSERT OR IGNORE INTO auto_produced_topics VALUES (?, ?)", (r["topic"], datetime.now().strftime("%Y-%m-%d %H:%M")))
            db.commit()
            made += 1
        return made
    finally:
        db.close()

def watch_topics_loop():
    while True:
        try:
            if os.path.exists("topics.txt"):
                with open("topics.txt", "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
                if lines:
                    with open("topics.txt", "w", encoding="utf-8") as f:
                        f.write("")
                    db = get_db()
                    chs = db.execute("SELECT * FROM channels").fetchall()
                    for line in lines:
                        if "|" in line:
                            t_name, t_str = [x.strip() for x in line.split("|", 1)]
                            for c in chs: 
                                if c["name"] == t_name:
                                    run_make_video(c["name"], c["persona"], t_str)
                        else:
                            for c in chs:
                                run_make_video(c["name"], c["persona"], line)
        except Exception:
            logger.exception("Topic queue worker failed")
        time.sleep(15)

def auto_radar_and_scheduler_loop():
    last_auto_date = ""
    time.sleep(5)
    while True:
        try:
            trend_radar.scan_global_trends("daily")
            trend_radar.scan_global_trends("weekly")
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            if AUTO_PRODUCE_ENABLED and now.hour == 8 and last_auto_date != today_str:
                auto_produce_top_trends(count=3)
                last_auto_date = today_str
        except Exception:
            logger.exception("Radar scheduler failed")
        time.sleep(RADAR_INTERVAL_SEC)

@app.on_event("startup")
def startup_event():
    init_app_db()
    radar_db = trend_radar.init_radar_db()
    radar_db.close()
    threading.Thread(target=watch_topics_loop, daemon=True).start()
    threading.Thread(target=auto_radar_and_scheduler_loop, daemon=True).start()

class CreateReq(BaseModel):
    channel_name: str
    topic: str

class QueueReq(BaseModel):
    topics_text: str

class BulkDelReq(BaseModel):
    job_ids: list[int]

class UpdateJobReq(BaseModel):
    title: str
    script: str

@app.get("/")
def serve_home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"status": "OK"}

@app.get("/api/overview")
def overview():
    db = get_db()
    try:
        chs = [dict(r) for r in db.execute("SELECT * FROM channels").fetchall()]
        jobs = [dict(r) for r in db.execute("SELECT * FROM pipeline_jobs ORDER BY id DESC").fetchall()]
    finally:
        db.close()
    q_txt = open("topics.txt", "r", encoding="utf-8").read().strip() if os.path.exists("topics.txt") else ""
    return {"channels": chs, "jobs": jobs, "topics_text": q_txt, "auto_produce": AUTO_PRODUCE_ENABLED}

@app.get("/api/radar/{period}")
def get_radar(period: str = "daily"):
    if period not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="period must be daily or weekly")
    conn = trend_radar.init_radar_db()
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM trend_recommendations WHERE period_type=? ORDER BY is_global_top10 DESC, viral_score DESC", (period,)).fetchall()]
    finally:
        conn.close()
    if len(rows) < 20:
        trend_radar.scan_global_trends(period)
        conn = trend_radar.init_radar_db()
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute("SELECT * FROM trend_recommendations WHERE period_type=? ORDER BY is_global_top10 DESC, viral_score DESC", (period,)).fetchall()]
        finally:
            conn.close()
    return {"period": period, "items": rows}

@app.post("/api/radar/scan/{period}")
def run_radar_scan(period: str = "daily"):
    if period not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="period must be daily or weekly")
    trend_radar.scan_global_trends(period)
    return {"ok": True, "msg": "글로벌 4개국 40개 순위 & TOP 10 스캔 완료"}

@app.post("/api/radar/auto-produce-now")
def trigger_auto_produce(bg: BackgroundTasks):
    bg.add_task(auto_produce_top_trends, 3)
    return {"ok": True, "msg": "ꮀ로벌 종핹 TOP 10 상위 3편의 완전 자동 AI 영상제작이 시작되었습니다!"}

@app.post("/api/radar/toggle-auto/{enabled}")
def toggle_auto_produce(enabled: int):
    global AUTO_PRODUCE_ENABLED
    AUTO_PRODUCE_ENABLED = bool(enabled)
    return {"ok": True, "enabled": AUTO_PRODUCE_ENABLED, "msg": "자동 제작 설정 변경 완료"}

@app.post("/api/radar/interval/{minutes}")
def set_radar_interval(minutes: int):
    global RADAR_INTERVAL_SEC
    if minutes < 1 or minutes > 1440:
        raise HTTPException(status_code=400, detail="minutes must be between 1 and 1440")
    RADAR_INTERVAL_SEC = minutes * 60
    return {"ok": True, "msg": f"자동 수집 주기가 {minutes}분위로 변경되었습니다."}

@app.post("/api/create")
def create_single(req: CreateReq, bg: BackgroundTasks):
    if not req.channel_name.strip() or not req.topic.strip():
        raise HTTPException(status_code=400, detail="channel_name and topic are required")
    db = get_db()
    try:
        ch = db.execute("SELECT * FROM channels WHERE name=?", (req.channel_name,)).fetchone()
    finally:
        db.close()
    if not ch:
        raise HTTPException(status_code=404, detail="Unknown channel")
    bg.add_task(run_make_video, req.channel_name, ch["persona"], req.topic)
    return {"ok": True, "msg": f"[{req.channel_name}] 아나운서 음성 영상제작이 시작되었습니다!"}

@app.post("/api/create-all")
def create_all(bg: BackgroundTasks):
    db = get_db()
    try:
        channels = db.execute("SELECT * FROM channels").fetchall()
    finally:
        db.close()
    for ch in channels:
        bg.add_task(run_make_video, ch["name"], ch["persona"], "오늘의 글로벌 핵심 트렌드")
    return {"ok": True, "msg": "전 채널 일괄제작이 시작되었습니다!"}

@app.post("/api/queue")
def save_queue(req: QueueReq):
    with open("topics.txt", "w", encoding="utf-8") as f:
        f.write(req.topics_text.strip() + ("\n" if req.topics_text.strip() else ""))
    return {"ok": True, "msg": "자동 제작 큐 저장 완료"}

@app.post("/api/approve/{job_id}")
def approve_job(job_id: int):
    db = get_db()
    try:
        jb = db.execute("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        db.close()
    if not jb:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    output_root = os.path.realpath("output")
    video_path = os.path.realpath(jb["video_path"])
    if os.path.commonpath([output_root, video_path]) != output_root or not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail="output 폴더 안의 실제 영상 파일만 업로드할 수 있습니다.")
    ok, msg = yt_uploader.upload_to_youtube(jb["channel_name"], video_path, jb["title"], jb["script"])
    if ok:
        db = get_db()
        try:
            db.execute("UPDATE pipeline_jobs SET stage='업로드 완료(비공개)' WHERE id=?", (job_id,))
            db.commit()
        finally:
            db.close()
    return {"ok": ok, "msg": msg}

@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, req: UpdateJobReq):
    db = get_db()
    try:
        cur = db.execute("UPDATE pipeline_jobs SET title=?, script=? WHERE id=?", (req.title, req.script, job_id))
        db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        return {"ok": True, "msg": "수정 내용이 저장되었습니다."}
    finally:
        db.close()

@app.post("/api/jobs/bulk-delete")
def bulk_delete_jobs(req: BulkDelReq):
    if not req.job_ids:
        return {"ok": False, "msg": "선택된 핬목이 없습니다."}
    db = get_db()
    try:
        placeholders = ",".join("?" for _ in req.job_ids)
        cur = db.execute(f"DELETE FROM pipeline_jobs WHERE id IN ({placeholders})", req.job_ids)
        db.commit()
        return {"ok": True, "msg": f"{cur.rowcount}건의 작업이 삭제되었습니다."}
    finally:
        db.close()

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    db = get_db()
    try:
        cur = db.execute("DELETE FROM pipeline_jobs WHERE id=?", (job_id,))
        db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        return {"ok": True, "msg": "삭제 완료"}
    finally:
        db.close()
