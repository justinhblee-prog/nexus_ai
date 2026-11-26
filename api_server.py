import os, time, sqlite3, threading
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import video_maker, yt_uploader, trend_radar

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
os.makedirs("export", exist_ok=True)
os.makedirs("output", exist_ok=True)
app.mount("/output", StaticFiles(directory="output"), name="output")

RADAR_INTERVAL_SEC = 300
AUTO_PRODUCE_ENABLED = True

def get_db():
    conn = sqlite3.connect("data/studio_data.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_oa_key():
    r = get_db().execute("SELECT value FROM settings WHERE key='oa'").fetchone()
    return r["value"] if r else ""

def run_make_video(ch_name: str, persona: str, topic: str):
    mp4, title, script = video_maker.render_pro_short(ch_name, persona, topic, get_oa_key())
    db = get_db()
    db.execute("INSERT INTO pipeline_jobs (channel_name, title, script, video_path, stage, created_at) VALUES (?,?,?,?,?,?)",
               (ch_name, title, script, mp4, "최종컨펌 대기", datetime.now().strftime("%Y-%m-%d %H:%M")))
    db.commit()

def auto_produce_top_trends(count=3):
    db = trend_radar.init_radar_db()
    db.row_factory = sqlite3.Row
    top_rows = db.execute("SELECT * FROM trend_recommendations WHERE period_type='daily' AND is_global_top10 > 0 ORDER BY is_global_top10 ASC").fetchall()
    made = 0
    for r in top_rows:
        if made >= count:
            break
        exists = db.execute("SELECT 1 FROM auto_produced_topics WHERE topic=?", (r["topic"],)).fetchone()
        if not exists:
            ch_row = db.execute("SELECT * FROM channels WHERE name=?", (r["matched_channel"],)).fetchone()
            persona = ch_row["persona"] if ch_row else "을문가 톤"
            run_make_video(r["matched_channel"], persona, r["topic"])
            db.execute("INSERT OR IGNORE INTO auto_produced_topics VALUES (?, ?)", (r["topic"], datetime.now().strftime("%Y-%m-%d %H:%M")))
            db.commit()
            made += 1
    return made

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
            pass
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
            pass
        time.sleep(RADAR_INTERVAL_SEC)

@app.on_event("startup")
def startup_event():
    trend_radar.init_radar_db()
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
    chs = [dict(r) for r in db.execute("SELECT * FROM channels").fetchall()]
    jobs = [dict(r) for r in db.execute("SELECT * FROM pipeline_jobs ORDER BY id DESC").fetchall()]
    q_txt = open("topics.txt", "r", encoding="utf-8").read().strip() if os.path.exists("topics.txt") else ""
    return {"channels": chs, "jobs": jobs, "topics_text": q_txt, "auto_produce": AUTO_PRODUCE_ENABLED}

@app.get("/api/radar/{period}")
def get_radar(period: str = "daily"):
    conn = trend_radar.init_radar_db()
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM trend_recommendations WHERE period_type=? ORDER BY is_global_top10 DESC, viral_score DESC", (period,)).fetchall()]
    if len(rows) < 20:
        trend_radar.scan_global_trends(period)
        rows = [dict(r) for r in conn.execute("SELECT * FROM trend_recommendations WHERE period_type=? ORDER BY is_global_top10 DESC, viral_score DESC", (period,)).fetchall()]
    return {"period": period, "items": rows}

@app.post("/api/radar/scan/{period}")
def run_radar_scan(period: str = "daily"):
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
    RADAR_INTERVAL_SEC = max(60, minutes * 60)
    return {"ok": True, "msg": f"자동 수집 주기가 {minutes}분위로 변경되었습니다."}

@app.post("/api/create")
def create_single(req: CreateReq, bg: BackgroundTasks):
    db = get_db()
    ch = db.execute("SELECT * FROM channels WHERE name=?", (req.channel_name,)).fetchone()
    persona = ch["persona"] if ch else "전문가 톤"
    bg.add_task(run_make_video, req.channel_name, persona, req.topic)
    return {"ok": True, "msg": f"[{req.channel_name}] 아나운서 음성 영상제작이 시작되었습니다!"}

@app.post("/api/create-all")
def create_all(bg: BackgroundTasks):
    db = get_db()
    for ch in db.execute("SELECT * FROM channels").fetchall():
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
    jb = db.execute("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
    if not jb:
        return {"ok": False, "msg": "작업을 찾을 수 없습니다."}
    ok, msg = yt_uploader.upload_to_youtube(jb["channel_name"], jb["video_path"], jb["title"], jb["script"])
    if ok:
        db.execute("UPDATE pipeline_jobs SET stage='엄로드 완료(비공개)' WHERE id=?", (job_id,))
        db.commit()
    return {"ok": ok, "msg": msg}

@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, req: UpdateJobReq):
    db = get_db()
    db.execute("UPDATE pipeline_jobs SET title=?, script=? WHERE id=?", (req.title, req.script, job_id))
    db.commit()
    return {"ok": True, "msg": "수정 내용이 저장되었습니다."}

@app.post("/api/jobs/bulk-delete")
def bulk_delete_jobs(req: BulkDelReq):
    if not req.job_ids:
        return {"ok": False, "msg": "선택된 핬목이 없습니다."}
    db = get_db()
    placeholders = ",".join("?" for _ in req.job_ids)
    db.execute(f"DELETE FROM pipeline_jobs WHERE id IN ({placeholders})", req.job_ids)
    db.commit()
    return {"ok": True, "msg": f"{Lgn(req.job_ids)} 건의 작업이 삭제되었습니다."}

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    db = get_db()
    db.execute("DELETE FROM pipeline_jobs WHERE id=?", (job_id,))
    db.commit()
    return {"ok": True, "msg": "삭제 완료"}
