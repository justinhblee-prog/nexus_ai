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

        CREATE TABLE IF NOT EXISTS topic_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            channel_name TEXT,
            topic TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'api',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at INTEGER NOT NULL,
            lease_until INTEGER,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_topic_queue_claim
            ON topic_queue(status, available_at, lease_until, id);
        CREATE TABLE IF NOT EXISTS scheduler_runs (
            schedule_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_until INTEGER,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
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


def enqueue_topic(topic_line: str, source: str = "api", idempotency_key: str | None = None):
    """Persist one topic per channel so retries cannot duplicate earlier channel renders."""
    import uuid
    raw = topic_line.strip()
    if not raw:
        return 0
    channel_name = None
    topic = raw
    if "|" in raw:
        channel_name, topic = [part.strip() for part in raw.split("|", 1)]
        if not channel_name or not topic:
            raise ValueError("queue lines must be 'channel | topic' or 'topic'")
    db = get_db()
    try:
        if channel_name is None:
            channels = [row["name"] for row in db.execute("SELECT name FROM channels ORDER BY id")]
            if not channels:
                raise RuntimeError("No channels are configured")
        else:
            channels = [channel_name]
        now = int(time.time())
        stamp = datetime.now().isoformat(timespec="seconds")
        added = 0
        for name in channels:
            key = f"{idempotency_key or uuid.uuid4().hex}:{name}"
            cur = db.execute(
                """INSERT OR IGNORE INTO topic_queue
                   (idempotency_key, channel_name, topic, source, status, attempts,
                    available_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                (key, name, topic, source, now, stamp, stamp),
            )
            added += max(0, cur.rowcount)
        db.commit()
        return added
    finally:
        db.close()

def claim_next_topic(lease_seconds: int = 900):
    """Atomically claim one pending or expired lease so concurrent workers cannot double-run it."""
    now = int(time.time())
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE topic_queue SET status='failed', lease_until=NULL,
               last_error=COALESCE(last_error, 'Worker lease expired after maximum attempts'),
               updated_at=?
               WHERE status='running' AND lease_until < ? AND attempts >= 3""",
            (datetime.now().isoformat(timespec="seconds"), now),
        )
        row = db.execute(
            """SELECT * FROM topic_queue
               WHERE available_at <= ? AND attempts < 3
                 AND (status='pending' OR (status='running' AND lease_until < ?))
               ORDER BY id LIMIT 1""",
            (now, now),
        ).fetchone()
        if not row:
            db.commit()
            return None
        db.execute(
            """UPDATE topic_queue SET status='running', attempts=attempts+1,
               lease_until=?, updated_at=? WHERE id=?""",
            (now + lease_seconds, datetime.now().isoformat(timespec="seconds"), row["id"]),
        )
        claimed = dict(row)
        claimed["attempts"] += 1
        db.commit()
        return claimed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def finish_topic(queue_id: int, error: str | None = None, max_attempts: int = 3):
    db = get_db()
    try:
        row = db.execute("SELECT attempts FROM topic_queue WHERE id=?", (queue_id,)).fetchone()
        if not row:
            return
        now = int(time.time())
        stamp = datetime.now().isoformat(timespec="seconds")
        if error is None:
            db.execute(
                "UPDATE topic_queue SET status='completed', lease_until=NULL, last_error=NULL, updated_at=? WHERE id=?",
                (stamp, queue_id),
            )
        elif row["attempts"] >= max_attempts:
            db.execute(
                "UPDATE topic_queue SET status='failed', lease_until=NULL, last_error=?, updated_at=? WHERE id=?",
                (error[:2000], stamp, queue_id),
            )
        else:
            delay = min(3600, 30 * (2 ** max(0, row["attempts"] - 1)))
            db.execute(
                """UPDATE topic_queue SET status='pending', lease_until=NULL,
                   available_at=?, last_error=?, updated_at=? WHERE id=?""",
                (now + delay, error[:2000], stamp, queue_id),
            )
        db.commit()
    finally:
        db.close()

def import_legacy_topics_file():
    """Import the legacy OneDrive topics.txt without losing content on worker crashes."""
    path = "topics.txt"
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        snapshot = handle.read()
    lines = [line.strip() for line in snapshot.splitlines() if line.strip()]
    if not lines:
        return
    import hashlib
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        stamp = datetime.now().isoformat(timespec="seconds")
        channels = [row["name"] for row in db.execute("SELECT name FROM channels ORDER BY id")]
        for index, line in enumerate(lines):
            key = hashlib.sha256(f"{digest}:{index}:{line}".encode("utf-8")).hexdigest()
            channel_name, topic = (line.split("|", 1) if "|" in line else (None, line))
            channel_name = channel_name.strip() if channel_name else None
            topic = topic.strip()
            targets = [channel_name] if channel_name else channels
            for target in targets:
                if topic and target:
                    db.execute(
                        """INSERT OR IGNORE INTO topic_queue
                           (idempotency_key, channel_name, topic, source, status, attempts,
                            available_at, created_at, updated_at)
                           VALUES (?, ?, ?, 'topics.txt', 'pending', 0, ?, ?, ?)""",
                        (f"{key}:{target}", target, topic, int(time.time()), stamp, stamp),
                    )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    # Clear only if no external edit occurred after the snapshot was read.
    with open(path, "r", encoding="utf-8") as handle:
        current = handle.read()
    if current == snapshot:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")

def watch_topics_loop():
    while True:
        item = None
        try:
            import_legacy_topics_file()
            item = claim_next_topic()
            if item:
                db = get_db()
                try:
                    channel = db.execute("SELECT * FROM channels WHERE name=?", (item["channel_name"],)).fetchone()
                    if not channel:
                        raise ValueError(f"Unknown channel: {item['channel_name']}")
                    run_make_video(channel["name"], channel["persona"], item["topic"])
                finally:
                    db.close()
                finish_topic(item["id"])
        except Exception as exc:
            logger.exception("Topic queue worker failed")
            if "item" in locals() and item:
                try:
                    finish_topic(item["id"], str(exc))
                except Exception:
                    logger.exception("Could not update failed queue item")
        time.sleep(5)


def claim_daily_schedule(schedule_key: str, lease_seconds: int = 21600, max_attempts: int = 3):
    """Persistently claim one daily production run across process restarts/replicas."""
    now = int(time.time())
    stamp = datetime.now().isoformat(timespec="seconds")
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM scheduler_runs WHERE schedule_key=?", (schedule_key,)).fetchone()
        if row and row["status"] == "completed":
            db.commit()
            return False
        if row and row["status"] == "running" and row["lease_until"] and row["lease_until"] > now:
            db.commit()
            return False
        if row and row["attempts"] >= max_attempts:
            db.execute(
                "UPDATE scheduler_runs SET status='failed', lease_until=NULL, updated_at=? WHERE schedule_key=?",
                (stamp, schedule_key),
            )
            db.commit()
            return False
        if row:
            db.execute(
                """UPDATE scheduler_runs SET status='running', attempts=attempts+1,
                   lease_until=?, last_error=NULL, updated_at=? WHERE schedule_key=?""",
                (now + lease_seconds, stamp, schedule_key),
            )
        else:
            db.execute(
                """INSERT INTO scheduler_runs
                   (schedule_key, status, attempts, lease_until, created_at, updated_at)
                   VALUES (?, 'running', 1, ?, ?, ?)""",
                (schedule_key, now + lease_seconds, stamp, stamp),
            )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def finish_daily_schedule(schedule_key: str, error: str | None = None):
    db = get_db()
    try:
        stamp = datetime.now().isoformat(timespec="seconds")
        if error is None:
            db.execute(
                "UPDATE scheduler_runs SET status='completed', lease_until=NULL, last_error=NULL, updated_at=? WHERE schedule_key=?",
                (stamp, schedule_key),
            )
        else:
            db.execute(
                "UPDATE scheduler_runs SET status='failed', lease_until=NULL, last_error=?, updated_at=? WHERE schedule_key=?",
                (error[:2000], stamp, schedule_key),
            )
        db.commit()
    finally:
        db.close()

def auto_radar_and_scheduler_loop():
    time.sleep(5)
    while True:
        try:
            trend_radar.scan_global_trends("daily")
            trend_radar.scan_global_trends("weekly")
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            if AUTO_PRODUCE_ENABLED and now.hour == 8 and claim_daily_schedule(today_str):
                try:
                    auto_produce_top_trends(count=3)
                    finish_daily_schedule(today_str)
                except Exception as exc:
                    finish_daily_schedule(today_str, str(exc))
                    raise
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
    queue_db = get_db()
    try:
        pending = queue_db.execute(
            "SELECT channel_name, topic FROM topic_queue WHERE status IN ('pending','running') ORDER BY id"
        ).fetchall()
    finally:
        queue_db.close()
    q_txt = "\\n".join(
        (f"{row['channel_name']} | " if row["channel_name"] else "") + row["topic"]
        for row in pending
    )
    return {"channels": chs, "jobs": jobs, "topics_text": q_txt, "auto_produce": AUTO_PRODUCE_ENABLED,
            "queue_pending": len(pending)}

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
    lines = [line.strip() for line in req.topics_text.splitlines() if line.strip()]
    added = sum(enqueue_topic(line, source="api") for line in lines)
    return {"ok": True, "queued": added, "msg": f"{added}건을 채널별 내구성 제작 큐에 등록했습니다."}

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
