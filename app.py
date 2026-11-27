import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3, os
from streamlit_auth import is_auth_configured, verify_streamlit_password
from audit_log import safe_record_event as record_event
from review_workflow import claim_upload, upload_result_stage
from datetime import datetime, timedelta
import yt_uploader

st.set_page_config(page_title="NEXUS STUDIO PRO", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

# The Streamlit app is a separate entry point from the FastAPI browser studio.
# Fail closed before creating directories, opening the database, or starting workers.
if not is_auth_configured():
    st.error("Streamlit 인증 설정이 없습니다. NEXUS_API_PASSWORD를 12자 이상으로 설정해 주세요.")
    st.stop()

if not st.session_state.get("nexus_streamlit_authenticated", False):
    st.title("⚡ NEXUS STUDIO PRO")
    st.subheader("운영자 로그인")
    st.caption("로컬 스튜디오 접근을 위해 API와 동일한 운영자 비밀번호가 필요합니다.")
    with st.form("nexus_streamlit_login"):
        password = st.text_input("운영자 비밀번호", type="password")
        submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
    if submitted:
        if verify_streamlit_password(password):
            st.session_state["nexus_streamlit_authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

# Reuse the FastAPI-owned durable queue; do not render inside Streamlit callbacks.
from api_server import enqueue_topic, init_app_db
init_app_db()

st.markdown("""
<style>
    @import url('https://jsdelivr.net');
    html, body, [class*="css"] { font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif; }
    .stApp { background-color: #050811; color: #F1F5F9; }
    header[data-testid="stHeader"] { background: transparent; }
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1480px; }
    
    /* 사이드바 정밀 스타일 */
    section[data-testid="stSidebar"] { background-color: #090D16; border-right: 1px solid #161E31; }
    
    /* 엔터프라이즈 탑바 */
    .nexus-header {
        display: flex; justify-content: space-between; align-items: center;
        background: linear-gradient(90deg, #0B101D 0%, #11182B 100%);
        border: 1px solid #1E293B; border-radius: 14px;
        padding: 16px 24px; margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }
    .nh-brand { display: flex; align-items: center; gap: 12px; }
    .nh-logo {
        width: 36px; height: 36px; border-radius: 10px;
        background: linear-gradient(135deg, #2563EB, #7C3AED);
        display: flex; align-items: center; justify-content: center;
        font-weight: 900; font-size: 18px; color: #FFF;
    }
    .nh-title { font-size: 19px; font-weight: 800; color: #F8FAFC; letter-spacing: -0.4px; }
    .nh-meta { font-size: 12px; color: #64748B; margin-top: 2px; }
    .nh-badges { display: flex; gap: 10px; align-items: center; }
    .pill-live { background: rgba(16,185,129,0.12); color: #34D399; border: 1px solid rgba(16,185,129,0.3); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; }
    .pill-queue { background: rgba(59,130,246,0.12); color: #60A5FA; border: 1px solid rgba(59,130,246,0.3); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; }

    /* KPI 카드 */
    div[data-testid="metric-container"] {
        background: #0B101D; border: 1px solid #182236;
        padding: 18px 22px; border-radius: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    }
    div[data-testid="metric-container"] label { color: #94A3B8 !important; font-size: 12px !important; font-weight: 600 !important; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #F8FAFC !important; font-size: 28px !important; font-weight: 800 !important; }

    /* 탭 내비게이션 */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background: #0B101D; padding: 6px; border-radius: 12px; border: 1px solid #182236; margin-bottom: 16px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px; padding: 9px 20px; color: #94A3B8; font-size: 13px; font-weight: 600; }
    .stTabs [aria-selected="true"] { background: linear-gradient(90deg, #2563EB, #4F46E5) !important; color: #FFFFFF !important; box-shadow: 0 2px 10px rgba(37,99,235,0.4); }

    /* 카드 컨테이너 */
    div[data-testid="stVerticalBlockBorderWrapper"] { background: #0B101D; border: 1px solid #182236 !important; border-radius: 14px !important; padding: 6px; }
    
    /* 모바일 쇼츠 프레임 헤더 */
    .phone-cap { text-align: center; font-size: 12px; color: #64748B; font-weight: 600; margin-bottom: 8px; letter-spacing: 0.5px; }

    /* 10대 브랜드 쇼케이스 */
    .b-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 14px 0; }
    .b-card { background: #0F1626; border: 1px solid #1E293B; border-radius: 12px; padding: 14px; }
    .b-card b { color: #F8FAFC; font-size: 14px; display: block; margin-bottom: 4px; }
    .b-card span { color: #38BDF8; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

os.makedirs("data", exist_ok=True)
os.makedirs("output", exist_ok=True)
os.makedirs("tokens", exist_ok=True)
conn = sqlite3.connect("data/studio_data.db", check_same_thread=False, timeout=30)
conn.execute("PRAGMA busy_timeout=30000")
conn.executescript("""
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
""")
conn.executescript("INSERT OR IGNORE INTO channels (name, platform, yt_id, persona) VALUES\n        ('Brain Glitch', 'YouTube', '', '심리 전문가 톤'),\n        ('Silent Signals', 'YouTube', '', '인간관계 전문가 톤'),\n        ('Unseen Truth', 'YouTube', '', '팩트체크 전문가 톤'),\n        ('Dark Files Global', 'YouTube', '', '미스터리 다큐 톤'),\n        ('99% Missed', 'YouTube', '', '생활 정보 전문가 톤'),\n        ('Money Glitch', 'YouTube', '', '경제 분석가 톤'),\n        ('Secret Vault 24', 'YouTube', '', '자산·습관 전문가 톤'),\n        ('Future Leak', 'YouTube', '', 'AI·기술 분석가 톤'),\n        ('30Sec Shift', 'YouTube', '', '건강 정보 전문가 톤'),\n        ('Why Nobody Tells', 'YouTube', '', '지식 큐레이터 톤');")
conn.commit()

def get_set(k):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return next(iter(r)) if r else ""

# The FastAPI process is the single owner of topics.txt import and the durable
# SQLite topic queue. Keeping a second Streamlit file watcher here could race
# with the API importer and consume the same file twice or lose entries.
df = pd.read_sql_query("SELECT * FROM channels", conn)
jobs = pd.read_sql_query("SELECT * FROM pipeline_jobs ORDER BY id DESC", conn)
pend = len(jobs[jobs["stage"] == "최종컨펌 대기"])
q_file_cnt = conn.execute("SELECT COUNT(*) FROM topic_queue WHERE status IN ('pending', 'running')").fetchone()[0]

with st.sidebar:
    st.markdown("### ⚡ NEXUS STUDIO")
    st.caption("Autonomous Short-Form Engine")
    if st.button("로그아웃", use_container_width=True):
        st.session_state.pop("nexus_streamlit_authenticated", None)
        st.rerun()
    st.divider()
    if st.button("⚡ 전 채널 1편씩 제작 큐 등록", type="primary", use_container_width=True):
        queued = 0
        for _, r in df.iterrows():
            queued += enqueue_topic(
                f"{r['name']} | 오늘의 글로벌 핵심 트렌드",
                source="streamlit_create_all",
            )
        st.success(f"{queued}건을 내구성 제작 큐에 등록했습니다.")
        st.rerun()
    st.markdown("")
    with st.expander("🔑 글로벌 API 키 설정"):
        yk = st.text_input("YouTube Data API Key", value=get_set("yt"), type="password")
        ok = st.text_input("OpenAI API Key (DALL-E 3 / GPT)", value=get_set("oa"), type="password")
        if st.button("API 키 저장", use_container_width=True):
            conn.execute("REPLACE INTO settings VALUES ('yt', ?), ('oa', ?)", (yk, ok))
            conn.commit()
            st.success("저장 완료")
    with st.expander("➕ 채널 계정 일괄 추가"):
        bulk = st.text_area("채널명 | 플랫폼 | 채널ID | AI말투", height=95, placeholder="Brain Glitch | YouTube | UC... | 심리 전문가 톤")
        if st.button("채널 등록 실행", use_container_width=True):
            for l in bulk.strip().split("\n"):
                p = [x.strip() for x in l.split("|")]
                if p and p:
                    try:
                        conn.execute("INSERT INTO channels (name, platform, yt_id, persona) VALUES (?, ?, ?, ?)",
                                     (p.pop(0), p.pop(0) if p else "YouTube", p.pop(0) if p else "", p.pop(0) if p else "전문가 톤"))
                    except Exception:
                        pass
            conn.commit()
            st.rerun()

st.markdown(f"""
<div class="nexus-header">
    <div class="nh-brand">
        <div class="nh-logo">N</div>
        <div>
            <div class="nh-title">NEXUS STUDIO PRO</div>
            <div class="nh-meta">멀티 채널 AI 숏폼 통합 제작 및 배포 관제 시스템</div>
        </div>
    </div>
    <div class="nh-badges">
        <span class="pill-queue">📥 자동 큐 대기: {q_file_cnt}건</span>
        <span class="pill-live">● ENGINE ONLINE</span>
    </div>
</div>
""", unsafe_allow_html=True)

t1, t2, t3, t4, t5 = st.tabs([
    "📊 대시보드 & 채널 현황",
    "🎬 스튜디오 & 자동 큐",
    f"🛡️ 검수 & 유튜브 배포 ({pend})",
    "🌐 브랜드 포트폴리오",
    "📖 전체 메뉴 사용 설명서"
])

with t1:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("운영 중인 채널", f"{len(df)} 개")
    c2.metric("통합 구독자 수", f"{int(df['subs'].sum()):,} 명")
    c3.metric("누적 조회수", f"{df['views'].sum()/10000:,.1f}만 회")
    c4.metric("컨펌 대기 영상", f"{pend} 편")
    g1, g2 = st.columns([1.65, 1])
    with g1:
        with st.container(border=True):
            st.markdown("**📈 최근 7일 채널별 조회수 성장 추이**")
            dates = [(datetime.now() - timedelta(days=i)).strftime("%m/%d") for i in range(6, -1, -1)]
            cdf = pd.DataFrame({"날짜": dates*len(df), "채널": sum([[n]*7 for n in df["name"]], []), "조회수": [int(v*(0.03+(i%3)*0.01)) for v in df["views"] for i in range(7)]})
            fig = px.area(cdf, x="날짜", y="조회수", color="채널", template="plotly_dark", color_discrete_sequence=["#3B82F6", "#8B5CF6", "#10B981", "#F59E0B"])
            fig.update_layout(height=265, margin=dict(l=0,r=0,t=10,b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    with g2:
        with st.container(border=True):
            st.markdown("**🍩 채널별 트래픽 점유율**")
            fig2 = px.pie(df, values="views", names="name", hole=0.65, template="plotly_dark", color_discrete_sequence=["#3B82F6", "#8B5CF6", "#10B981", "#F59E0B"])
            fig2.update_layout(height=265, margin=dict(l=0,r=0,t=10,b=0), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)
    with st.container(border=True):
        st.markdown("**🎛️ 등록 채널 마스터 리스트**")
        st.dataframe(df[["id", "name", "platform", "subs", "views", "persona"]], use_container_width=True, hide_index=True)

with t2:
    col_single, col_queue = st.columns([1, 1.2], gap="large")
    with col_single:
        with st.container(border=True):
            st.markdown("#### 🎯 단건 즉시 렌더링")
            st.caption("특정 채널 1개를 지정해 지금 바로 시네마틱 쇼츠를 생성합니다.")
            ch = st.selectbox("대상 채널 선택", df["name"].tolist())
            row = df[df["name"] == ch].iloc[0]
            tp = st.text_input("영상 주제 입력", placeholder="예: 2026년 달라지는 AI 산업 핵심 요약")
            if st.button("🚀 선택한 채널 톤으로 즉시 생성", type="primary", use_container_width=True):
                if tp:
                    queued = enqueue_topic(f"{row['name']} | {tp}", source="streamlit_create")
                    if queued:
                        st.success("제작 요청을 내구성 큐에 등록했습니다. 완료 후 검수 탭에 표시됩니다.")
                    else:
                        st.info("같은 채널·주제가 이미 대기 또는 실행 중입니다.")
                    st.rerun()
                else:
                    st.warning("영상 주제를 입력해주세요.")
    with col_queue:
        with st.container(border=True):
            st.markdown("#### 📥 대량 자동 제작 큐 (`topics.txt` 실시간 연동)")
            st.caption("주제를 여러 줄 입력해 저장하면 백그라운드 워커가 15초마다 자동 감지해 순차 제작합니다.")
            cur_topics = open("topics.txt", "r", encoding="utf-8").read().strip() if os.path.exists("topics.txt") else ""
            new_topics = st.text_area("주제 목록 (한 줄에 1개 / 특정 채널 지정 시 '채널명 | 주제')", value=cur_topics, height=175,
                                      placeholder="2026년 연말정산 환급금 늘리는 핵심 팁\nFuture Leak | 지금 당장 써야 할 무료 AI 툴 3선")
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("📥 일괄 등록", type="primary", use_container_width=True):
                    with open("topics.txt", "w", encoding="utf-8") as f:
                        f.write(new_topics.strip() + ("\n" if new_topics.strip() else ""))
                    st.success("등록 완료! 15초 내 자동 제작 시작")
                    st.rerun()
            with b2:
                if st.button("🗑️ 비우기", use_container_width=True):
                    open("topics.txt", "w", encoding="utf-8").write("")
                    st.rerun()
            with b3:
                if st.button("🔄 새로고침", use_container_width=True):
                    st.rerun()
with t3:
    if jobs.empty:
        st.info("대기 중인 영상이 없습니다. [🎬 스튜디오 & 자동 큐] 탭에서 영상을 먼저 생성해 보세요.")
    else:
        w_left, w_mid, w_right = st.columns([0.9, 1.35, 0.9], gap="medium")
        with w_left:
            with st.container(border=True):
                st.markdown("#### 📋 작업 대기열")
                only_pend = st.checkbox("컨펌 대기 항목만 보기", value=False)
                view_jobs = jobs[jobs["stage"] == "최종컨펌 대기"] if only_pend else jobs
                if view_jobs.empty:
                    view_jobs = jobs
                sid = st.radio(
                    "검수할 영상 선택",
                    view_jobs["id"].tolist(),
                    format_func=lambda x: f"#{x} · {view_jobs.loc[view_jobs['id']==x, 'channel_name'].item()} ({'대기' if '대기' in view_jobs.loc[view_jobs['id']==x, 'stage'].item() else '완료'})"
                )
        jb = jobs[jobs["id"] == sid].iloc[0]
        ch_n = jb["channel_name"]
        with w_mid:
            with st.container(border=True):
                st.markdown(f"#### ✍️ 메타데이터 & 대본 검수 (`{ch_n}`)")
                et = st.text_input("유튜브 업로드 제목", value=jb["title"])
                edited_script = st.text_area("전체 내레이션 대본 확인", value=jb["script"], height=320)
                if st.button("💾 검수 내용 저장", use_container_width=True):
                    resubmitted = jb["stage"] == "반려(수정 필요)"
                    if resubmitted:
                        conn.execute("UPDATE pipeline_jobs SET title=?, script=?, stage='최종컨펌 대기' WHERE id=?",
                                     (et, edited_script, int(jb["id"])))
                    else:
                        conn.execute("UPDATE pipeline_jobs SET title=?, script=? WHERE id=?",
                                     (et, edited_script, int(jb["id"])))
                    conn.commit()
                    if resubmitted:
                        record_event("review.resubmitted", entity_type="pipeline_job", entity_id=int(jb["id"]),
                                     payload={"channel": ch_n, "source": "streamlit"})
                    st.success("검수 내용이 저장되었습니다.")
                    st.rerun()
                c1 = st.checkbox("AI 생성 콘텐츠 라벨 적용 및 1차 비공개(Private) 안전 업로드 동의", value=True)
                safe_channel = "".join(ch for ch in ch_n if ch.isalnum() or ch in ("-", "_"))
                token_status = yt_uploader.get_channel_token_status(ch_n)
                token_ok = bool(token_status.get("upload"))
                if not token_ok:
                    st.warning(f"⚠️ [{ch_n}] YouTube 업로드 인증이 필요합니다.")
                    if token_status.get("error"):
                        st.caption("기존 토큰을 읽지 못했습니다. 다시 인증해 주세요.")
                    if st.button("🔗 YouTube 업로드 + Analytics 읽기 권한 연결", key=f"oauth-link-{safe_channel}", use_container_width=True):
                        flow, url = yt_uploader.get_auth_url(ch_n)
                        if flow:
                            st.session_state["oauth_flow"] = flow
                            st.session_state["oauth_channel"] = ch_n
                            st.markdown(f"👉 **[Google 로그인 페이지 열기]({url})** 후 리다이렉트된 주소창 URL 전체를 아래에 붙여넣으세요.")
                        else:
                            st.error(url)
                    auth_code = st.text_input("리다이렉트 URL(또는 인증 코드) 붙여넣기", key=f"oauth-code-{safe_channel}")
                    if st.button("인증 토큰 저장", key=f"oauth-save-{safe_channel}", use_container_width=True) and auth_code and st.session_state.get("oauth_channel") == ch_n:
                        yt_uploader.save_auth_code(ch_n, st.session_state["oauth_flow"], auth_code)
                        st.session_state.pop("oauth_flow", None)
                        st.session_state.pop("oauth_channel", None)
                        st.success("인증 완료!")
                        st.rerun()
                else:
                    st.caption(f"🟢 `{ch_n}` YouTube 업로드 토큰 연결됨")
                    if (not token_status.get("analytics") or token_status.get("error") or
                            (token_status.get("expired") and not token_status.get("refreshable"))):
                        st.warning("YouTube Analytics 읽기 전용 권한이 없습니다. 실제 조회수/구독자/참여율을 보려면 다시 동의해 주세요.")
                        if st.button("🔐 Analytics 읽기 전용 권한 추가", key=f"analytics-oauth-link-{safe_channel}", use_container_width=True):
                            flow, url = yt_uploader.get_auth_url(ch_n)
                            if flow:
                                st.session_state["oauth_flow"] = flow
                                st.session_state["oauth_channel"] = ch_n
                                st.markdown(f"👉 **[Google 권한 동의 페이지 열기]({url})** 후 리다이렉트 URL 전체를 아래에 붙여넣으세요.")
                            else:
                                st.error(url)
                        auth_code = st.text_input("Analytics 권한 리다이렉트 URL", key=f"analytics-oauth-code-{safe_channel}")
                        if st.button("Analytics 권한 저장", key=f"analytics-oauth-save-{safe_channel}", use_container_width=True) and auth_code and st.session_state.get("oauth_channel") == ch_n:
                            yt_uploader.save_auth_code(ch_n, st.session_state["oauth_flow"], auth_code)
                            st.session_state.pop("oauth_flow", None)
                            st.session_state.pop("oauth_channel", None)
                            st.success("읽기 전용 Analytics 권한이 저장되었습니다.")
                            st.rerun()
                    else:
                        st.caption("🟢 YouTube Analytics 읽기 전용 권한 연결됨")
                    if jb["stage"] == "업로드 상태 확인 필요":
                        st.warning("YouTube 업로드는 생성됐지만 Private 상태를 확인하지 못했습니다. 중복 업로드를 막기 위해 재시도를 차단했습니다.")
                    if st.button("✅ 최종 컨펌 승인 및 유튜브 비공개 업로드", type="primary", use_container_width=True,
                                 disabled=jb["stage"] != "최종컨펌 대기"):
                        if c1:
                            output_root = os.path.realpath("output")
                            video_path = os.path.realpath(jb["video_path"])
                            if os.path.commonpath([output_root, video_path]) != output_root or not os.path.isfile(video_path):
                                st.error("output 폴더 안의 실제 영상 파일만 업로드할 수 있습니다.")
                                st.stop()
                            if not claim_upload(conn, int(jb["id"])):
                                st.error("다른 요청에서 이미 검수 또는 업로드를 처리하고 있습니다.")
                                st.rerun()
                            conn.commit()
                            record_event("review.approved", entity_type="pipeline_job", entity_id=int(jb["id"]),
                                         payload={"channel": ch_n, "approval_source": "streamlit"})
                            with st.spinner("YouTube Studio로 영상 전송 중..."):
                                ok, msg = yt_uploader.upload_to_youtube(ch_n, jb["video_path"], et, jb["script"])
                            privacy_unverified = msg.startswith("UPLOAD_CREATED_PRIVACY_UNVERIFIED:") or msg.startswith("UPLOAD_RESULT_UNCERTAIN:")
                            event_type = "upload.completed" if ok else ("upload.privacy_unverified" if privacy_unverified else "upload.failed")
                            record_event(event_type, entity_type="pipeline_job", entity_id=int(jb["id"]),
                                         payload={"channel": ch_n, "privacy_status": "private" if ok else "unverified"})
                            conn.execute("UPDATE pipeline_jobs SET title=?, stage=? WHERE id=?",
                                         (et, upload_result_stage(ok, privacy_unverified), int(jb["id"])))
                            conn.commit()
                            if ok:
                                st.success(msg)
                                st.balloons()
                            elif privacy_unverified:
                                st.error("업로드 결과 또는 Private 상태를 확인하지 못했습니다. 중복 업로드를 방지하기 위해 재시도를 차단했습니다.")
                            else:
                                st.error(f"업로드 실패: {msg}")
        reject_note = st.text_input("반려 사유 (선택)", max_chars=2000, key=f"reject-note-{int(jb['id'])}")
        if st.button("↩ 반려 및 수정 요청", use_container_width=True,
                     disabled=jb["stage"] != "최종컨펌 대기"):
            cur = conn.execute("UPDATE pipeline_jobs SET stage='반려(수정 필요)' WHERE id=? AND stage='최종컨펌 대기'", (int(jb["id"]),))
            conn.commit()
            if cur.rowcount != 1:
                st.error("다른 요청에서 이미 검수 또는 업로드를 처리하고 있습니다.")
                st.rerun()
            record_event("review.rejected", entity_type="pipeline_job", entity_id=int(jb["id"]),
                         payload={"channel": ch_n, "note": reject_note.strip(), "source": "streamlit"})
            st.success("반려 및 수정 요청이 기록되었습니다.")
            st.rerun()
        with w_right:
            with st.container(border=True):
                st.markdown('<div class="phone-cap">📱 9:16 SHORTS PREVIEW</div>', unsafe_allow_html=True)
                if jb["video_path"] and os.path.exists(jb["video_path"]):
                    st.video(jb["video_path"])
                else:
                    st.warning("영상 파일이 존재하지 않습니다.")
                if st.button("🗑️ 현재 작업 삭제", use_container_width=True):
                    conn.execute("DELETE FROM pipeline_jobs WHERE id=?", (int(jb["id"]),))
                    conn.commit()
                    record_event("pipeline_job.deleted", entity_type="pipeline_job", entity_id=int(jb["id"]),
                                 payload={"channel": ch_n, "source": "streamlit"})
                    st.rerun()

with t4:
    st.markdown("### 🌐 글로벌 10대 추천 브랜드 포트폴리오")
    st.markdown("""<div class="b-grid">
    <div class="b-card"><b>▶️ Brain Glitch</b><span>심리 · 뇌과학 트릭</span></div>
    <div class="b-card"><b>🎵 Silent Signals</b><span>인간관계 · 바디랭귀지</span></div>
    <div class="b-card"><b>🔍 Unseen Truth</b><span>사건의 숨은 이면</span></div>
    <div class="b-card"><b>📁 Dark Files</b><span>실화 기반 미스터리</span></div>
    <div class="b-card"><b>💡 99% Missed</b><span>일상 착시 · 팩트체크</span></div>
    <div class="b-card"><b>💲 Money Glitch</b><span>글로벌 경제 · 수익구조</span></div>
    <div class="b-card"><b>🔐 Secret Vault</b><span>상위 1% 부자 습관</span></div>
    <div class="b-card"><b>🚀 Future Leak</b><span>최신 AI · 미래 기술</span></div>
    <div class="b-card"><b>💓 30Sec Shift</b><span>30초 건강 · 저속노화</span></div>
    <div class="b-card"><b>🧠 Why Nobody</b><span>학교서 안알려주는 꿀팁</span></div>
    </div>""", unsafe_allow_html=True)

with t5:
    st.markdown("### 📖 NEXUS STUDIO PRO — 전체 메뉴 상세 사용 설명서")
    with st.expander("🎛️ [좌측 사이드바] 제어 메뉴 사용법", expanded=True):
        st.markdown("""
        * **⚡ [전 채널 1편씩 즉시 일괄 생성]**: 등록된 모든 채널의 말투(페르소나)에 맞춰 시네마틱 숏폼을 1편씩 자동 생성해 **[🛡️ 검수 & 유튜브 배포]** 대기열로 보냅니다.
        * **🔑 [글로벌 API 키 설정]**: YouTube Data API 키와 OpenAI API 키를 등록합니다. OpenAI 키를 넣으면 AI 맞춤형 대본과 **DALL-E 3 세로형 고화질 배경**이 자동 적용됩니다.
        * **➕ [채널 계정 일괄 추가]**: `채널명 | 플랫폼 | 채널ID | AI말투` 형식으로 여러 계정을 한 번에 등록합니다.
        """)
    with st.expander("📊 [1번 탭] 대시보드 & 채널 현황", expanded=True):
        st.markdown("""
        * 상단 4개 지표 카드와 최근 7일 조회수 추이 그래프, 채널별 점유율 차트, 전체 채널 마스터 테이블을 실시간으로 모니터링합니다.
        """)
    with st.expander("🎬 [2번 탭] 스튜디오 & 자동 큐 (`topics.txt`)", expanded=True):
        st.markdown("""
        * **단건 즉시 렌더링**: 채널 1개를 지정해 주제를 입력하면 즉시 MP4 쇼츠를 렌더링합니다.
        * **대량 자동 제작 큐**: 여러 주제를 입력하고 **[📥 일괄 등록]**을 누르거나, 외부 스마트폰 OneDrive 앱에서 폴더 내 `topics.txt`에 주제를 적어 저장하면 **15초마다 자동 감지**해 순차 제작합니다.
        """)
    with st.expander("🛡️ [3번 탭] 3단 워크스테이션 검수 & 유튜브 배포", expanded=True):
        st.markdown("""
        * **좌측 작업 대기열**: 검수할 영상을 선택합니다 (`컨펌 대기 항목만 보기` 필터 지원).
        * **중앙 메타데이터 & 대본 검수**: 업로드 제목과 전체 내레이션 대본(320px 대형 창)을 확인하고, 최초 1회 구글 로그인 인증 후 **[✅ 최종 컨펌 승인 및 유튜브 비공개 업로드]**를 누르면 실제 YouTube Studio(`콘텐츠 → Shorts` 탭)에 비공개 상태로 업로드됩니다.
        * **우측 9:16 쇼츠 미리보기**: 실제 화면·자막·음성 싱크를 재생해 최종 확인하고 불필요한 작업은 삭제할 수 있습니다.
        """)

