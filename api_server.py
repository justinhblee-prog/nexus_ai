import os, time, sqlite3, threading, logging, hmac, hashlib, secrets
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import video_maker, yt_uploader, trend_radar
from audit_log import safe_record_event as record_event, list_events, get_ops_metrics

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("nexus.api")

app = FastAPI(title="NEXUS STUDIO PRO API")
# Browser sessions are signed server-side and stored in HttpOnly cookies.
API_PASSWORD = os.getenv('NEXUS_API_PASSWORD', '')
SESSION_SECRET = os.getenv('NEXUS_SESSION_SECRET', '')
SESSION_COOKIE_NAME = 'nexus_session'
SESSION_TTL_SECONDS = 12 * 60 * 60

def auth_is_configured() -> bool:
    return len(API_PASSWORD) >= 12 and len(SESSION_SECRET) >= 32

def create_session_cookie(now: int | None = None) -> str:
    if not auth_is_configured():
        raise RuntimeError('API session secrets are not configured')
    issued = int(time.time() if now is None else now)
    payload = f'{issued + SESSION_TTL_SECONDS}.{secrets.token_urlsafe(18)}'
    signature = hmac.new(SESSION_SECRET.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{payload}.{signature}'

def verify_session_cookie(cookie: str | None, now: int | None = None) -> bool:
    if not auth_is_configured() or not cookie:
        return False
    try:
        expires_text, nonce, signature = cookie.split('.', 2)
        expires = int(expires_text)
        current = int(time.time() if now is None else now)
        if expires <= current or expires > current + SESSION_TTL_SECONDS + 60 or not nonce:
            return False
        payload = f'{expires_text}.{nonce}'
        expected = hmac.new(SESSION_SECRET.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (TypeError, ValueError):
        return False

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
async def enforce_local_origin_and_session(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in LOCAL_UI_ORIGINS:
        return JSONResponse(status_code=403, content={"detail": "Cross-origin mutation rejected"})
    path = request.url.path
    public_paths = {"/api/session/status", "/api/session/login", "/api/session/logout"}
    protected = (path.startswith("/api/") and path not in public_paths) or path.startswith("/output/")
    if protected:
        if not auth_is_configured():
            return JSONResponse(status_code=503, content={"detail": "Set NEXUS_API_PASSWORD and NEXUS_SESSION_SECRET to enable API authentication."})
        if not verify_session_cookie(request.cookies.get(SESSION_COOKIE_NAME)):
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
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
        CREATE TABLE IF NOT EXISTS auto_produced_topics (
            topic TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
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
    started = time.monotonic()
    record_event("render.started", entity_type="render", payload={"channel": ch_name, "topic_length": len(topic)})
    try:
        mp4, title, script = video_maker.render_pro_short(ch_name, persona, topic, get_oa_key())
        qa = validate_video(mp4)
        record_event("qa.passed" if qa["ok"] else "qa.failed", entity_type="render",
                     payload={"channel": ch_name, "checks": qa["checks"], "errors": qa["errors"]})
        if not qa["ok"]:
            raise RuntimeError("Video QA failed: " + ", ".join(qa["errors"]))
        db = get_db()
        try:
            cur = db.execute("INSERT INTO pipeline_jobs (channel_name, title, script, video_path, stage, created_at) VALUES (?,?,?,?,?,?)",
                             (ch_name, title, script, mp4, "최종컨펌 대기", datetime.now().strftime("%Y-%m-%d %H:%M")))
            db.commit()
            job_id = cur.lastrowid
        finally:
            db.close()
        record_event("render.completed", entity_type="pipeline_job", entity_id=job_id,
                     payload={"channel": ch_name, "elapsed_seconds": round(time.monotonic() - started, 3)})
        return job_id
    except Exception as exc:
        record_event("render.failed", entity_type="render",
                     payload={"channel": ch_name, "error_type": type(exc).__name__,
                              "elapsed_seconds": round(time.monotonic() - started, 3)})
        raise

def auto_produce_top_trends(count=3):
    """Queue daily radar picks durably; the queue worker performs the actual renders."""
    radar_db = trend_radar.init_radar_db()
    radar_db.row_factory = sqlite3.Row
    try:
        top_rows = [dict(row) for row in radar_db.execute(
            "SELECT * FROM trend_recommendations WHERE period_type='daily' AND is_global_top10 > 0 ORDER BY is_global_top10 ASC"
        ).fetchall()]
        channels = {row["name"]: row["persona"] for row in radar_db.execute("SELECT name, persona FROM channels")}
    finally:
        radar_db.close()

    db = get_db()
    try:
        produced = {row[0] for row in db.execute("SELECT topic FROM auto_produced_topics")}
        queued = {row[0] for row in db.execute(
            "SELECT topic FROM topic_queue WHERE source='daily_radar'"
        )}
    finally:
        db.close()

    date_key = datetime.now().strftime("%Y-%m-%d")
    queued_count = 0
    for trend in top_rows:
        if queued_count >= count:
            break
        topic = trend["topic"]
        channel = trend["matched_channel"]
        if topic in produced or topic in queued:
            continue
        if channel not in channels:
            logger.warning("Skipping trend with unknown channel: %s", channel)
            continue
        added = enqueue_topic(
            f"{channel} | {topic}",
            source="daily_radar",
            idempotency_key=f"daily-radar:{date_key}:{topic}",
        )
        if added:
            queued.add(topic)
            queued_count += 1
    return queued_count


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
        # Serialize the active-topic check and insert to prevent concurrent double-enqueue.
        db.execute("BEGIN IMMEDIATE")
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
            # Repeated UI clicks must not create concurrent copies of the same channel/topic.
            active = db.execute(
                """SELECT 1 FROM topic_queue
                   WHERE channel_name=? AND topic=? AND status IN ('pending', 'running')
                   LIMIT 1""",
                (name, topic),
            ).fetchone()
            if active:
                continue
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
        if added:
            record_event("queue.enqueued", entity_type="topic_queue",
                         payload={"source": source, "channel_count": added})
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
        record_event("queue.claimed", entity_type="topic_queue", entity_id=claimed["id"],
                     payload={"channel": claimed["channel_name"], "attempt": claimed["attempts"]})
        return claimed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def finish_topic(queue_id: int, error: str | None = None, max_attempts: int = 3):
    db = get_db()
    try:
        row = db.execute("SELECT attempts, topic, source FROM topic_queue WHERE id=?", (queue_id,)).fetchone()
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
        if error is None and row["source"] == "daily_radar":
            db.execute(
                "INSERT OR IGNORE INTO auto_produced_topics (topic, created_at) VALUES (?, ?)",
                (row["topic"], stamp),
            )
        db.commit()
        if error is None:
            event_type = "queue.completed"
            payload = {"status": "completed"}
        elif row["attempts"] >= max_attempts:
            event_type = "queue.failed"
            payload = {"status": "failed", "error_type": "processing_error"}
        else:
            event_type = "queue.retry_scheduled"
            payload = {"status": "pending", "attempt": row["attempts"]}
        record_event(event_type, entity_type="topic_queue", entity_id=queue_id, payload=payload)
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
        added = 0
        for index, line in enumerate(lines):
            key = hashlib.sha256(f"{digest}:{index}:{line}".encode("utf-8")).hexdigest()
            channel_name, topic = (line.split("|", 1) if "|" in line else (None, line))
            channel_name = channel_name.strip() if channel_name else None
            topic = topic.strip()
            targets = [channel_name] if channel_name else channels
            for target in targets:
                if topic and target:
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO topic_queue
                           (idempotency_key, channel_name, topic, source, status, attempts,
                            available_at, created_at, updated_at)
                           VALUES (?, ?, ?, 'topics.txt', 'pending', 0, ?, ?, ?)""",
                        (f"{key}:{target}", target, topic, int(time.time()), stamp, stamp),
                    )
                    added += max(0, cursor.rowcount)
        db.commit()
        if added:
            record_event("queue.enqueued", entity_type="topic_queue",
                         payload={"source": "topics.txt", "channel_count": added})
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
        record_event("scheduler.started", entity_type="scheduler_run", entity_id=schedule_key,
                     payload={"attempt": (row["attempts"] + 1) if row else 1})
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
        record_event("scheduler.failed" if error else "scheduler.completed",
                     entity_type="scheduler_run", entity_id=schedule_key,
                     payload={"error_type": "scheduler_error"} if error else {"status": "completed"})
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
            if AUTO_PRODUCE_ENABLED and now.hour >= 8 and claim_daily_schedule(today_str):
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

class LoginReq(BaseModel):
    password: str

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

class RejectReq(BaseModel):
    note: str = ""

@app.get("/")
def serve_home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"status": "OK"}

@app.get("/api/session/status")
def session_status(request: Request):
    return {"configured": auth_is_configured(), "authenticated": verify_session_cookie(request.cookies.get(SESSION_COOKIE_NAME))}

@app.post("/api/session/login")
def session_login(req: LoginReq):
    if not auth_is_configured():
        raise HTTPException(status_code=503, detail="서버 설정에 NEXUS_API_PASSWORD(12자 이상)와 NEXUS_SESSION_SECRET(32자 이상)을 지정해야 합니다.")
    if not hmac.compare_digest(req.password, API_PASSWORD):
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
    response = JSONResponse({"ok": True})
    response.set_cookie(key=SESSION_COOKIE_NAME, value=create_session_cookie(), max_age=SESSION_TTL_SECONDS, httponly=True, secure=os.getenv("NEXUS_COOKIE_SECURE", "false").lower() == "true", samesite="strict", path="/")
    return response

@app.post("/api/session/logout")
def session_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return response
@app.get("/api/events")
def get_events(limit: int = 50, event_type: str | None = None):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return {"items": list_events(limit=limit, event_type=event_type)}

@app.get("/api/ops/metrics")
def ops_metrics():
    return get_ops_metrics()

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
def create_single(req: CreateReq):
    if not req.channel_name.strip() or not req.topic.strip():
        raise HTTPException(status_code=400, detail="channel_name and topic are required")
    db = get_db()
    try:
        ch = db.execute("SELECT * FROM channels WHERE name=?", (req.channel_name,)).fetchone()
    finally:
        db.close()
    if not ch:
        raise HTTPException(status_code=404, detail="Unknown channel")
    queued = enqueue_topic(f"{req.channel_name} | {req.topic}", source="api_create")
    return {"ok": True, "queued": queued, "msg": f"[{req.channel_name}] 제작 요청을 내구성 큐에 등록했습니다."}

@app.post("/api/create-all")
def create_all():
    db = get_db()
    try:
        channels = db.execute("SELECT * FROM channels").fetchall()
    finally:
        db.close()
    queued = 0
    for ch in channels:
        queued += enqueue_topic(
            f"{ch['name']} | 오늘의 글로벌 핵심 트렌드",
            source="api_create_all",
        )
    return {"ok": True, "queued": queued, "msg": f"전 채널 제작 요청 {queued}건을 내구성 큐에 등록했습니다."}

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
    if jb["stage"] != "최종컨펌 대기":
        raise HTTPException(status_code=409, detail="이미 처리됐거나 업로드 상태 확인이 필요한 작업입니다.")
    output_root = os.path.realpath("output")
    video_path = os.path.realpath(jb["video_path"])
    if os.path.commonpath([output_root, video_path]) != output_root or not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail="output 폴더 안의 실제 영상 파일만 업로드할 수 있습니다.")
    db = get_db()
    try:
        if not claim_upload(db, job_id):
            raise HTTPException(status_code=409, detail="다른 요청에서 이미 검수 또는 업로드를 처리하고 있습니다.")
        db.commit()
    finally:
        db.close()
    record_event("review.approved", entity_type="pipeline_job", entity_id=job_id,
                 payload={"channel": jb["channel_name"], "approval_source": "api"})
    ok, msg = yt_uploader.upload_to_youtube(jb["channel_name"], video_path, jb["title"], jb["script"])
    privacy_unverified = msg.startswith("UPLOAD_CREATED_PRIVACY_UNVERIFIED:") or msg.startswith("UPLOAD_RESULT_UNCERTAIN:")
    event_type = "upload.completed" if ok else ("upload.privacy_unverified" if privacy_unverified else "upload.failed")
    record_event(event_type, entity_type="pipeline_job", entity_id=job_id,
                 payload={"channel": jb["channel_name"], "privacy_status": "private" if ok else "unverified"})
    db = get_db()
    try:
        db.execute("UPDATE pipeline_jobs SET stage=? WHERE id=?",
                   (upload_result_stage(ok, privacy_unverified), job_id))
        db.commit()
    finally:
        db.close()
    return {"ok": ok, "msg": msg}

@app.post("/api/reject/{job_id}")
def reject_job(job_id: int, req: RejectReq):
    note = (req.note or "").strip()
    if len(note) > 2000:
        raise HTTPException(status_code=400, detail="반려 사유는 2000자 이하여야 합니다.")
    db = get_db()
    try:
        job = db.execute("SELECT stage, channel_name FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        if job["stage"] != "최종컨펌 대기":
            raise HTTPException(status_code=409, detail="검수 대기 상태의 작업만 반려할 수 있습니다.")
        cur = db.execute("UPDATE pipeline_jobs SET stage='반려(수정 필요)' WHERE id=? AND stage='최종컨펌 대기'", (job_id,))
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="다른 요청에서 이미 검수 또는 업로드를 처리하고 있습니다.")
        db.commit()
    finally:
        db.close()
    record_event("review.rejected", entity_type="pipeline_job", entity_id=job_id,
                 payload={"channel": job["channel_name"], "note": note, "source": "browser_studio"})
    return {"ok": True, "msg": "반려 및 수정 요청이 기록되었습니다."}

@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, req: UpdateJobReq):
    db = get_db()
    try:
        job = db.execute("SELECT stage, channel_name FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        resubmitted = job["stage"] == "반려(수정 필요)"
        stage_sql = ", stage='최종컨펌 대기'" if resubmitted else ""
        db.execute(f"UPDATE pipeline_jobs SET title=?, script=?{stage_sql} WHERE id=?", (req.title, req.script, job_id))
        db.commit()
        if resubmitted:
            record_event("review.resubmitted", entity_type="pipeline_job", entity_id=job_id,
                         payload={"channel": job["channel_name"], "source": "browser_studio"})
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
