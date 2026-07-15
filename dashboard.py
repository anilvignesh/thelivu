"""Thelivu — Command Center. Run: streamlit run dashboard.py

The owner's single screen. Reads and drives the deployed engine (Railway) over the
shared Postgres DB: ingest links, work persistent digs, run the proactive
follow-up sweep, manage sources and scheduled jobs, review drafts. The ONE gated
action is publishing — approving a draft posts it to the channel; everything else
is autonomous (see docs/command-center.md, memory thelivu-autonomy).
"""

import os
import re
import time
import json
import requests
import psycopg2
import psycopg2.extras
import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime, timezone

# Shared engine helpers (respect DATABASE_URL — same DB the dashboard talks to).
from shared.db import (
    list_digs, get_dig, get_dig_updates, create_dig, update_dig, add_dig_update,
    queue_ingest, kv_get, kv_set,
)

# ── Config ────────────────────────────────────────────────────────────────────
DB_URL         = os.environ.get("DATABASE_URL", "")
BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("TELEGRAM_CHANNEL_ID", "")
DRAFT_CHAT_ID  = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "")
TG_API        = f"https://api.telegram.org/bot{BOT_TOKEN}"
REPO_ROOT     = Path(__file__).parent

_INR = 84
_MODEL_COSTS = {
    "claude":     {"in": 3.00, "out": 15.00},
    "gemini":     {"in": 0.30, "out": 1.00},
    "gemini-pro": {"in": 1.25, "out": 10.00},
}

st.set_page_config(page_title="Thelivu — Command Center", page_icon="📰", layout="wide")


# ── Auth gate ─────────────────────────────────────────────────────────────────
def _require_auth():
    expected = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected:
        st.error("Server misconfigured: DASHBOARD_PASSWORD is not set. "
                 "Refusing to start unprotected.")
        st.stop()
    if st.session_state.get("auth_ok"):
        return
    st.title("Thelivu — sign in")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Enter")
    if submitted and pw == expected:
        st.session_state["auth_ok"] = True
        st.rerun()
    elif submitted:
        st.error("Wrong password.")
    st.stop()


_require_auth()


# ── Brand / dossier styling ───────────────────────────────────────────────────
# The Thelivu palette (mirrors publishing/slides.py). Dark, kraft-on-ink, with
# gold and brick accents. Mono for headers/labels — the "dossier" feel.
KRAFT, INK, BRICK, GOLD = "#E6DCC3", "#17140D", "#8C2A1B", "#D2AA6D"
SURFACE, LINE, MUTED = "#221C13", "#3A3123", "#A79876"
_MONO = "'DejaVu Sans Mono','JetBrains Mono','SFMono-Regular',Menlo,Consolas,monospace"

# Semantic colors for status pills.
_PILL = {
    "pending_human": ("#3a2f14", GOLD),   "published": ("#173a22", "#7fd1a0"),
    "investigating": ("#14304a", "#8fc7ff"), "writing": ("#14304a", "#8fc7ff"),
    "killed": ("#3a1713", "#e39a8f"), "kill": ("#3a1713", "#e39a8f"),
    "held": ("#332a12", "#e6c86a"), "hold": ("#332a12", "#e6c86a"),
    "recheck_requested": ("#2a2340", "#c3b3ff"),
    # dig statuses
    "scoping": ("#2a2512", "#e6c86a"), "records-pending": ("#14304a", "#8fc7ff"),
    "verifying": ("#2a2340", "#c3b3ff"), "ready-to-write": ("#173a22", "#7fd1a0"),
    "parked": ("#2b2b2b", "#b9b9b9"),
    "queued": ("#2b2b2b", "#c9bfa6"), "running": ("#14304a", "#8fc7ff"), "done": ("#173a22", "#7fd1a0"),
}

def pill(status):
    bg, fg = _PILL.get(status, ("#2b2b2b", KRAFT))
    return (f"<span style='background:{bg};color:{fg};padding:2px 9px;border-radius:999px;"
            f"font-family:{_MONO};font-size:11px;font-weight:700;letter-spacing:.04em;"
            f"white-space:nowrap'>{status}</span>")

st.markdown(f"""
<style>
:root {{ --kraft:{KRAFT}; --ink:{INK}; --gold:{GOLD}; --brick:{BRICK}; --surface:{SURFACE}; --line:{LINE}; }}

/* hide Streamlit chrome for a product feel */
#MainMenu, footer, header[data-testid="stHeader"] {{ visibility:hidden; height:0; }}
[data-testid="stToolbar"], [data-testid="stDecoration"] {{ display:none; }}
.block-container {{ padding-top:1.2rem; max-width:1400px; }}

/* headers + labels in the dossier mono */
h1,h2,h3,h4 {{ font-family:{_MONO} !important; letter-spacing:-.01em; color:var(--kraft); }}
h1 {{ font-weight:700; }}
[data-testid="stMetricLabel"], [data-testid="stWidgetLabel"] label,
.stTabs [data-baseweb="tab"] {{ font-family:{_MONO} !important; }}

/* brand header bar */
.thv-hero {{ display:flex; align-items:center; gap:14px; padding:14px 18px; margin-bottom:8px;
  background:linear-gradient(90deg, {SURFACE}, {INK}); border:1px solid var(--line);
  border-left:4px solid var(--gold); border-radius:12px; }}
.thv-hero .mark {{ font-family:{_MONO}; font-size:22px; font-weight:800; color:var(--gold);
  letter-spacing:-.02em; }}
.thv-hero .sub {{ font-family:{_MONO}; font-size:12px; color:var(--muted,{'#A79876'}); letter-spacing:.06em; text-transform:uppercase; }}
.thv-hero .mal {{ color:var(--kraft); font-size:20px; margin-left:2px; opacity:.85; }}

/* tabs → nav strip */
.stTabs [data-baseweb="tab-list"] {{ gap:2px; border-bottom:1px solid var(--line); }}
.stTabs [data-baseweb="tab"] {{ padding:8px 16px; font-size:13px; color:{'#A79876'}; letter-spacing:.03em; }}
.stTabs [aria-selected="true"] {{ color:var(--gold) !important; border-bottom:2px solid var(--gold); }}

/* metrics as cards */
[data-testid="stMetric"] {{ background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:14px 16px; }}
[data-testid="stMetricValue"] {{ font-family:{_MONO}; color:var(--kraft); }}

/* bordered containers → dossier cards */
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:12px !important;
  border-color:var(--line) !important; background:rgba(255,255,255,.012); }}

/* buttons */
.stButton button {{ border-radius:9px; font-family:{_MONO}; font-size:13px; border:1px solid var(--line); }}
.stButton button[kind="primary"] {{ background:var(--gold); color:{INK}; border:none; font-weight:700; }}
.stButton button[kind="primary"]:hover {{ background:#e6bd82; color:{INK}; }}

/* inputs + expanders */
[data-testid="stExpander"] {{ border:1px solid var(--line); border-radius:10px; background:var(--surface); }}
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb] {{ border-radius:8px; }}
.stDataFrame {{ border:1px solid var(--line); border-radius:10px; }}

/* section labels */
.thv-eyebrow {{ font-family:{_MONO}; font-size:11px; letter-spacing:.14em; text-transform:uppercase;
  color:{'#A79876'}; margin:2px 0 6px; }}
hr {{ border-color:var(--line); }}
</style>
""", unsafe_allow_html=True)


def eyebrow(text):
    st.markdown(f"<div class='thv-eyebrow'>{text}</div>", unsafe_allow_html=True)

def empty_state(icon, title, hint):
    st.markdown(
        f"<div style='text-align:center;padding:34px 12px;border:1px dashed {LINE};"
        f"border-radius:12px;background:{SURFACE}'>"
        f"<div style='font-size:30px'>{icon}</div>"
        f"<div style='font-family:{_MONO};color:{KRAFT};margin-top:6px;font-size:14px'>{title}</div>"
        f"<div style='color:#A79876;font-size:12px;margin-top:3px'>{hint}</div></div>",
        unsafe_allow_html=True)


# ── DB helpers ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=10)
def q(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def execute(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
    finally:
        conn.close()

def scalar(sql, params=None):
    rows = q(sql, params)
    return list(rows[0].values())[0] if rows else 0

def cost(model, i, o):
    m = (model or "").lower()
    if "gemini" in m and "pro" in m: tier = "gemini-pro"
    elif "gemini" in m: tier = "gemini"
    else: tier = "claude"
    c = _MODEL_COSTS[tier]
    return (i/1e6 * c["in"]) + (o/1e6 * c["out"])

def signal(key, value="1"):
    """Write a kv_store signal the orchestrator tick loop reads."""
    kv_set(key, value)

def _age_days(ts):
    if not ts:
        return 0
    try:
        dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0

def _since(ts):
    """Human 'x ago' from an ISO timestamp string in kv_store."""
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs < 3600:   return f"{int(secs//60)}m ago"
        if secs < 86400:  return f"{int(secs//3600)}h ago"
        return f"{int(secs//86400)}d ago"
    except Exception:
        return str(ts)[:16]

@st.cache_data(ttl=30)
def load_watchlist():
    import yaml
    p = REPO_ROOT / "engine" / "watchlist.yaml"
    if not p.exists():
        return []
    try:
        return yaml.safe_load(p.read_text()).get("themes", []) or []
    except Exception:
        return []


# ── Telegram helpers ───────────────────────────────────────────────────────────
TG_LIMIT = 4096

def _tg_chunks(text):
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        cand = (cur + "\n\n" + para).strip() if cur else para
        if len(cand) <= TG_LIMIT:
            cur = cand
        else:
            if cur: chunks.append(cur)
            while len(para) > TG_LIMIT:
                chunks.append(para[:TG_LIMIT]); para = para[TG_LIMIT:]
            cur = para
    if cur: chunks.append(cur)
    return chunks or ["(empty)"]

FOOTER = "\n\n—\nSources above. Drafted with AI assistance, reviewed by a human editor before publishing."

def tg_post_channel(text):
    if FOOTER not in text: text += FOOTER
    msg_ids = []
    for chunk in _tg_chunks(text):
        r = requests.post(f"{TG_API}/sendMessage", json={"chat_id": CHANNEL_ID, "text": chunk}, timeout=30)
        r.raise_for_status()
        msg_ids.append(r.json()["result"]["message_id"])
        time.sleep(0.3)
    return msg_ids

def tg_notify(text):
    for chunk in _tg_chunks(text):
        requests.post(f"{TG_API}/sendMessage", json={"chat_id": DRAFT_CHAT_ID, "text": chunk}, timeout=15)

# ── Icons ──────────────────────────────────────────────────────────────────────
STATUS_ICON = {
    "investigating": "🔍", "writing": "✍️", "pending_human": "📬",
    "published": "✅", "killed": "❌", "kill": "❌", "held": "⏸", "hold": "⏸",
}
SKILL_ICON = {
    "news-investigator": "🔍", "source-verifier": "🔎", "news-monitor": "📡",
    "article-writer": "✍️", "editorial-reviewer": "📝", "pattern-synthesizer": "🧩",
    "topic-intake": "📥", "source-scout": "🕵️", "beat-monitor": "📻",
    "story-scout": "🗺️", "story-tracker": "📌", "newsworthiness-gate": "🚦",
    "meta-synthesizer": "🧭", "source-ingestor": "📼", "chief-of-staff": "🧑‍💼",
}
DIG_STATUS_ICON = {
    "scoping": "🔦", "records-pending": "📂", "verifying": "🔬",
    "ready-to-write": "✅", "parked": "🅿️", "killed": "❌",
}

# ── Header ────────────────────────────────────────────────────────────────────
col_brand, col_time, col_refresh = st.columns([5, 2, 1])
with col_brand:
    st.markdown(
        "<div class='thv-hero'>"
        "<span class='mark'>THELIVU</span><span class='mal'>തെളിവ്</span>"
        "<span class='sub'>· command center</span></div>",
        unsafe_allow_html=True)
with col_time:
    st.write("")
    st.caption(f"🟢 live · {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
with col_refresh:
    st.write("")
    if st.button("🔄", use_container_width=True, help="Refresh data"):
        st.cache_data.clear(); st.rerun()

# ── Tabs ──────────────────────────────────────────────────────────────────────
(t_overview, t_ingest, t_drafts, t_pipeline, t_digs,
 t_followups, t_sources, t_tasks, t_costs) = st.tabs(
    ["Overview", "Ingest", "Drafts", "Pipeline", "Digs",
     "Follow-ups", "Sources", "Tasks", "Costs"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with t_overview:
    runs = q("SELECT status, COUNT(*) as n FROM pipeline_runs GROUP BY status")
    rm = {r["status"]: r["n"] for r in runs}
    n_gate = rm.get("pending_human", 0)
    n_held = rm.get("held", 0) + rm.get("hold", 0)
    n_live = rm.get("investigating", 0) + rm.get("writing", 0)
    _db_published = scalar("SELECT COUNT(*) FROM publications")
    try:
        active_digs = list_digs(include_closed=False)
    except Exception:
        active_digs = []
    usage = q("""SELECT model, SUM(input_tokens) as i, SUM(output_tokens) as o
                 FROM token_usage WHERE recorded_at::date = CURRENT_DATE GROUP BY model""")
    today_usd = sum(cost(r["model"], r["i"] or 0, r["o"] or 0) for r in usage)

    # ── "Needs you" banner — the one thing that gates on Anil ──────────────────
    if n_gate:
        st.markdown(
            f"<div style='background:{SURFACE};border:1px solid {LINE};border-left:4px solid {GOLD};"
            f"border-radius:12px;padding:14px 18px;margin-bottom:14px;display:flex;align-items:center;gap:12px'>"
            f"<span style='font-size:22px'>📬</span>"
            f"<span style='font-family:{_MONO};color:{KRAFT};font-size:15px'>"
            f"<b style='color:{GOLD}'>{n_gate}</b> draft{'s' if n_gate!=1 else ''} waiting at your gate"
            f"</span><span style='color:{MUTED};font-size:12px'>— review in the Drafts tab</span></div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div style='color:{MUTED};font-family:{_MONO};font-size:13px;margin-bottom:14px'>"
            f"✓ Gate clear — nothing waiting on you.</div>", unsafe_allow_html=True)

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("At the gate", n_gate)
    c2.metric("Live now", n_live)
    c3.metric("Held", n_held)
    c4.metric("Active digs", len(active_digs))
    c5.metric("Published", _db_published)

    st.divider()
    left, right = st.columns([3,2])

    with left:
        # Live agents
        agents = q("""SELECT skill, model, topic, EXTRACT(EPOCH FROM (NOW()-started_at))::int AS secs
                      FROM active_agents ORDER BY started_at""")
        eyebrow(f"⚡ Live agents — {len(agents)} running" if agents else "⚡ Live agents — idle")
        if agents:
            cols = st.columns(min(len(agents), 4))
            for i, ag in enumerate(agents):
                m, s = divmod(ag["secs"] or 0, 60)
                icon = SKILL_ICON.get(ag["skill"], "🤖")
                model_s = "Gemini" if ag["model"] and "gemini" in ag["model"].lower() else "Claude"
                with cols[i % 4]:
                    st.metric(f"{icon} {ag['skill']}", model_s, f"{m}m {s}s" if m else f"{s}s")
                    if ag["topic"]: st.caption(ag["topic"][:55])
        else:
            st.caption("No skills running right now.")

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # Recent runs — as cards with pills
        eyebrow("Recent runs")
        recent = q("SELECT id, created_at::date as date, source, LEFT(throughline,74) as story, trust_gate, status FROM pipeline_runs ORDER BY id DESC LIMIT 8")
        if recent:
            for r in recent:
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;"
                    f"padding:9px 12px;border:1px solid {LINE};border-radius:9px;background:{SURFACE};margin-bottom:6px'>"
                    f"<div style='min-width:0'>"
                    f"<span style='font-family:{_MONO};color:{GOLD};font-size:12px'>#{r['id']}</span> "
                    f"<span style='color:{KRAFT};font-size:13px'>{(r['story'] or 'Untitled')}</span><br>"
                    f"<span style='color:{MUTED};font-size:11px'>{r['date']} · {r['source']} · gate {r['trust_gate'] or '—'}</span>"
                    f"</div>{pill(r['status'])}</div>",
                    unsafe_allow_html=True)
        else:
            empty_state("📭", "No pipeline runs yet", "They'll appear here as the engine works.")

    with right:
        eyebrow("Quick submit")
        with st.form("topic_form_ov"):
            topic_input = st.text_area("Submit a topic", placeholder="What's the story?", height=70, label_visibility="collapsed")
            if st.form_submit_button("Submit topic →", use_container_width=True, type="primary") and topic_input.strip():
                execute("INSERT INTO pending_topics (topic, source) VALUES (%s, %s)",
                        (topic_input.strip(), "dashboard"))
                st.success("Queued — agent picks it up within 2 minutes.")
                st.cache_data.clear()

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        eyebrow("Digs in flight")
        if active_digs:
            for d in active_digs[:6]:
                st.markdown(
                    f"<div style='padding:8px 11px;border:1px solid {LINE};border-radius:9px;"
                    f"background:{SURFACE};margin-bottom:6px'>"
                    f"<span style='font-family:{_MONO};color:{GOLD};font-size:12px'>#{d['id']}</span> "
                    f"<span style='color:{KRAFT};font-size:13px'>{d['title'][:44]}</span><br>"
                    f"<span style='color:{MUTED};font-size:11px'>updated {_since(d.get('updated_at'))}</span> "
                    f"{pill(d['status'])}</div>", unsafe_allow_html=True)
        else:
            empty_state("🗺️", "No active digs", "Open one in the Digs tab.")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        eyebrow("Cost today")
        st.metric("Today", f"₹{today_usd*_INR:.2f}", f"${today_usd:.4f}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — INGEST
# ══════════════════════════════════════════════════════════════════════════════
with t_ingest:
    st.subheader("📥 Paste a link to pick up")
    st.caption("Article or YouTube URLs. The engine fetches the content, triages it "
               "through topic-intake, verifies on the open web, and brings a draft to "
               "your gate. Nothing auto-publishes.")
    with st.form("ingest_form"):
        urls_raw = st.text_area("URL(s) — one per line",
                                placeholder="https://www.thehindu.com/...\nhttps://youtu.be/...", height=110)
        note = st.text_input("Angle / note (optional)", placeholder="Why this, what to look for")
        if st.form_submit_button("Ingest →", use_container_width=True, type="primary"):
            urls = [u.strip() for u in urls_raw.splitlines() if u.strip().startswith("http")]
            if not urls:
                st.warning("No valid http(s) URL found.")
            else:
                for u in urls:
                    queue_ingest(u, note.strip())
                st.success(f"Queued {len(urls)} link(s). The agent picks them up within ~2 minutes.")
                st.cache_data.clear()

    st.divider()
    st.subheader("Recent ingests")
    ingests = q("""SELECT id, LEFT(topic, 90) AS topic, status, submitted_at::timestamp(0) AS at
                   FROM pending_topics WHERE source='ingest' ORDER BY id DESC LIMIT 20""")
    if ingests:
        idf = pd.DataFrame(ingests)
        idf["status"] = idf["status"].apply(lambda s: {"queued":"⏳ queued","running":"🔄 running","done":"✅ done"}.get(s, s))
        st.dataframe(idf, use_container_width=True, hide_index=True)
        st.caption("A finished ingest becomes a pipeline run — see it in Pipeline / Drafts.")
    else:
        st.caption("No links ingested yet.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — DRAFTS
# ══════════════════════════════════════════════════════════════════════════════
def _load_file_drafts():
    drafts_dir = REPO_ROOT / "articles" / "drafts"
    if not drafts_dir.exists():
        return []
    files = []
    for f in sorted(drafts_dir.glob("*.md"), reverse=True):
        text = f.read_text(encoding="utf-8")
        m = re.search(r'^#\s+(.+)', text, re.MULTILINE)
        title = m.group(1).strip() if m else f.stem
        files.append({"path": f, "name": f.name, "title": title, "text": text})
    return files

with t_drafts:
    drafts = q("""SELECT id, created_at::date as date, source, throughline,
                         trust_gate, draft_text, review_text, verification_report
                  FROM pipeline_runs WHERE status='pending_human' ORDER BY id DESC""")
    held = q("""SELECT id, created_at::date as date, source, throughline, trust_gate
                FROM pipeline_runs WHERE status IN ('held','hold') ORDER BY id DESC""")

    if not drafts and not held:
        st.info("No drafts pending review. Stories will appear here when ready.")
    else:
        st.caption(f"{len(drafts)} pending review · {len(held)} on hold  ·  "
                   "**Approving is the only action that publishes.**")

    for run in drafts:
        run_id = run["id"]
        with st.container(border=True):
            hc1, hc2 = st.columns([5,2])
            with hc1:
                st.markdown(f"**#{run_id}** — {(run['throughline'] or '')[:100]}")
                st.caption(f"{run['date']} · {run['source']} · Trust gate: {run['trust_gate'] or '—'}")
            with hc2:
                a1, a2, a3 = st.columns(3)
                approve = a1.button("✓ Approve", key=f"app_{run_id}", type="primary", use_container_width=True)
                kill    = a2.button("✗ Kill",    key=f"kil_{run_id}", use_container_width=True)
                hold    = a3.button("⏸ Hold",   key=f"hld_{run_id}", use_container_width=True)

            if approve:
                try:
                    msg_ids = tg_post_channel(run.get("draft_text") or "")
                    execute("UPDATE pipeline_runs SET status='published', updated_at=NOW() WHERE id=%s", (run_id,))
                    execute("INSERT INTO publications (run_id, channel_msg_ids, confidence) VALUES (%s,%s,%s)",
                            (run_id, json.dumps(msg_ids), "Confirmed"))
                    tg_notify(f"✅ Published run #{run_id} ({len(msg_ids)} message(s)).")
                    st.success(f"Published! {len(msg_ids)} message(s) posted to {CHANNEL_ID}")
                    st.cache_data.clear(); time.sleep(1); st.rerun()
                except Exception as e:
                    st.error(f"Publish failed: {e}")
            if kill:
                execute("UPDATE pipeline_runs SET status='killed', updated_at=NOW() WHERE id=%s", (run_id,))
                tg_notify(f"❌ Story #{run_id} killed from dashboard.")
                st.cache_data.clear(); st.rerun()
            if hold:
                execute("UPDATE pipeline_runs SET status='held', updated_at=NOW() WHERE id=%s", (run_id,))
                tg_notify(f"⏸ Story #{run_id} held from dashboard.")
                st.cache_data.clear(); st.rerun()

            with st.expander("Read draft"):
                st.markdown(run.get("draft_text") or "_No draft text saved._")
            with st.expander("Review notes"):
                st.text(run.get("review_text") or "_No review notes._")
            with st.expander("Verification report"):
                st.text(run.get("verification_report") or "_No verification report._")

    if held:
        st.subheader("On hold")
        for run in held:
            with st.container(border=True):
                hc1, hc2 = st.columns([5,2])
                with hc1:
                    st.markdown(f"**#{run['id']}** — {(run['throughline'] or '')[:100]}")
                    st.caption(f"{run['date']} · {run['source']}")
                with hc2:
                    b1, b2 = st.columns(2)
                    if b1.button("Requeue", key=f"req_{run['id']}", use_container_width=True):
                        execute("UPDATE pipeline_runs SET status='pending_human', updated_at=NOW() WHERE id=%s", (run['id'],))
                        st.cache_data.clear(); st.rerun()
                    if b2.button("Recheck", key=f"rck_{run['id']}", use_container_width=True):
                        execute("UPDATE pipeline_runs SET status='recheck_requested', updated_at=NOW() WHERE id=%s", (run['id'],))
                        st.success("Queued for recheck."); st.cache_data.clear(); st.rerun()

    file_drafts = _load_file_drafts()
    if file_drafts:
        st.subheader(f"File drafts ({len(file_drafts)})")
        published_dir = REPO_ROOT / "articles" / "published"
        killed_dir    = REPO_ROOT / "articles" / "killed"
        published_dir.mkdir(parents=True, exist_ok=True)
        killed_dir.mkdir(parents=True, exist_ok=True)
        for fd in file_drafts:
            slug = fd["name"].replace(".md", "")
            with st.container(border=True):
                hc1, hc2 = st.columns([5, 2])
                with hc1:
                    st.markdown(f"**{fd['title']}**"); st.caption(fd["name"])
                with hc2:
                    a1, a2 = st.columns(2)
                    approve = a1.button("✓ Approve", key=f"fapp_{slug}", type="primary", use_container_width=True)
                    kill    = a2.button("✗ Kill",    key=f"fkil_{slug}", use_container_width=True)
                if approve:
                    try:
                        msg_ids = tg_post_channel(fd["text"])
                        fd["path"].rename(published_dir / fd["name"])
                        execute("INSERT INTO publications (run_id, channel_msg_ids, confidence) VALUES (%s,%s,%s)",
                                (None, json.dumps(msg_ids), "Confirmed"))
                        tg_notify(f"✅ Published file draft: {fd['name']} ({len(msg_ids)} message(s)).")
                        st.success(f"Published! {len(msg_ids)} message(s) posted.")
                        st.cache_data.clear(); time.sleep(1); st.rerun()
                    except Exception as e:
                        st.error(f"Publish failed: {e}")
                if kill:
                    fd["path"].rename(killed_dir / fd["name"])
                    tg_notify(f"❌ File draft killed: {fd['name']}")
                    st.cache_data.clear(); st.rerun()
                with st.expander("Read draft"):
                    st.markdown(fd["text"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PIPELINE
# ══════════════════════════════════════════════════════════════════════════════
with t_pipeline:
    status_filter = st.selectbox("Filter by status",
        ["all","investigating","writing","pending_human","published","killed","held"], index=0)
    sql = "SELECT id, created_at, source, throughline, trust_gate, status, updated_at FROM pipeline_runs"
    if status_filter != "all":
        sql += " WHERE status=%(s)s"
    sql += " ORDER BY id DESC LIMIT 50"
    all_runs = q(sql, {"s": status_filter} if status_filter != "all" else None)

    if not all_runs:
        st.info("No runs match this filter.")
    else:
        for run in all_runs:
            icon = STATUS_ICON.get(run["status"], "?")
            with st.expander(f"{icon} **#{run['id']}** {(run['throughline'] or 'Untitled')[:80]}"):
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("Status", run["status"])
                dc2.metric("Gate", run["trust_gate"] or "—")
                dc3.metric("Source", (run["source"] or "—")[:18])
                st.caption(f"Created: {run['created_at']} · Updated: {run['updated_at']}")
                detail = q("SELECT draft_text, review_text, verification_report FROM pipeline_runs WHERE id=%(i)s", {"i": run["id"]})
                if detail:
                    d = detail[0]
                    dt1, dt2, dt3 = st.tabs(["Draft", "Review", "Verification"])
                    with dt1: st.markdown(d.get("draft_text") or "_Not yet written._")
                    with dt2: st.text(d.get("review_text") or "_No review._")
                    with dt3: st.text(d.get("verification_report") or "_No verification._")
                if run["status"] == "pending_human":
                    bc1, bc2, bc3 = st.columns(3)
                    if bc1.button("✓ Approve", key=f"pa_{run['id']}", type="primary"):
                        try:
                            msg_ids = tg_post_channel((detail[0].get("draft_text") or "") if detail else "")
                            execute("UPDATE pipeline_runs SET status='published', updated_at=NOW() WHERE id=%s", (run["id"],))
                            execute("INSERT INTO publications (run_id,channel_msg_ids,confidence) VALUES (%s,%s,%s)",
                                    (run["id"], json.dumps(msg_ids), "Confirmed"))
                            st.success("Published!"); st.cache_data.clear(); st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
                    if bc2.button("✗ Kill", key=f"pk_{run['id']}"):
                        execute("UPDATE pipeline_runs SET status='killed', updated_at=NOW() WHERE id=%s", (run["id"],))
                        st.cache_data.clear(); st.rerun()
                    if bc3.button("⏸ Hold", key=f"ph_{run['id']}"):
                        execute("UPDATE pipeline_runs SET status='held', updated_at=NOW() WHERE id=%s", (run["id"],))
                        st.cache_data.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — DIGS  (persistent, multi-day investigations)
# ══════════════════════════════════════════════════════════════════════════════
with t_digs:
    st.subheader("🗺️ Persistent digs")
    st.caption("A thread worked over days: scope → pull records → try to disprove → "
               "promote only when it holds. Advance runs the next step; promote sends "
               "it into the pipeline (still ends at your gate).")

    with st.expander("➕ Open a new dig"):
        with st.form("new_dig"):
            nd_title = st.text_input("Title")
            nd_q     = st.text_area("Falsifiable question", height=60,
                                    placeholder="Who controls X, and how did they get it?")
            nd_anchor = st.text_input("Kerala anchor (optional)")
            nd_hyp    = st.text_area("Working hypothesis (optional)", height=60)
            nd_pri    = st.selectbox("Priority", [1,2,3], index=1, format_func=lambda p: f"{p} ({'high' if p==1 else 'normal' if p==2 else 'low'})")
            nd_start  = st.checkbox("Advance immediately (queue first step)", value=True)
            if st.form_submit_button("Open dig", type="primary", use_container_width=True) and nd_title.strip():
                did = create_dig(title=nd_title.strip(), question=nd_q.strip(),
                                 kerala_anchor=nd_anchor.strip(), hypothesis=nd_hyp.strip(),
                                 priority=nd_pri, owner_note="opened from dashboard")
                if nd_start:
                    signal("advance_dig_id", str(did))
                st.success(f"Dig #{did} opened." + (" First step queued." if nd_start else ""))
                st.cache_data.clear(); st.rerun()

    # Watchlist → start-as-dig
    themes = load_watchlist()
    if themes:
        with st.expander(f"📋 Watchlist ({len(themes)} themes) — start any as a dig"):
            for th in themes:
                wc1, wc2 = st.columns([5,1])
                with wc1:
                    st.markdown(f"**{th.get('id','?')}** — {(th.get('question') or '')[:110]}")
                    st.caption(f"anchor: {th.get('kerala_anchor','—')} · status: {th.get('status','—')}")
                with wc2:
                    if st.button("Start", key=f"wl_{th.get('id')}", use_container_width=True):
                        did = create_dig(title=th.get("id","watchlist theme").replace("-"," ").title(),
                                         question=th.get("question",""),
                                         kerala_anchor=th.get("kerala_anchor",""),
                                         watchlist_id=th.get("id",""), owner_note="from watchlist")
                        signal("advance_dig_id", str(did))
                        st.success(f"Dig #{did} opened + first step queued.")
                        st.cache_data.clear(); st.rerun()

    st.divider()
    show_closed = st.checkbox("Show parked/killed", value=False)
    try:
        digs = list_digs(include_closed=show_closed)
    except Exception as e:
        digs = []; st.error(f"Could not load digs: {e}")

    if not digs:
        st.info("No digs yet. Open one above, or start a watchlist theme.")
    for d in digs:
        icon = DIG_STATUS_ICON.get(d["status"], "🕳️")
        with st.expander(f"{icon} **#{d['id']}** {d['title'][:70]}  ·  {d['status']}"):
            st.caption(f"Updated {_since(d.get('updated_at'))} · priority {d.get('priority')} "
                       f"· next action: {_since(d.get('next_action_at')) if d.get('next_action_at') else '—'}")
            if d.get("question"):     st.markdown(f"**Q:** {d['question']}")
            if d.get("kerala_anchor"): st.caption(f"Anchor: {d['kerala_anchor']}")
            if d.get("hypothesis"):   st.caption(f"Hypothesis: {d['hypothesis']}")

            bc1, bc2, bc3, bc4 = st.columns(4)
            if bc1.button("⏭️ Advance", key=f"dadv_{d['id']}", use_container_width=True):
                signal("advance_dig_id", str(d["id"]))
                st.success("Next step queued (~2 min)."); st.cache_data.clear()
            if bc2.button("📝 Promote", key=f"dpro_{d['id']}", use_container_width=True):
                signal("promote_dig_id", str(d["id"]))
                st.success("Promoting to pipeline."); st.cache_data.clear()
            if bc3.button("🅿️ Park", key=f"dpark_{d['id']}", use_container_width=True):
                update_dig(d["id"], status="parked", next_action_at=None); st.cache_data.clear(); st.rerun()
            if bc4.button("❌ Kill", key=f"dkill_{d['id']}", use_container_width=True):
                update_dig(d["id"], status="killed", next_action_at=None); st.cache_data.clear(); st.rerun()

            # Investigation timeline
            try:
                ups = get_dig_updates(d["id"])
            except Exception:
                ups = []
            st.markdown("**Investigation log**")
            if ups:
                for u in ups:
                    st.markdown(f"`{str(u['created_at'])[:16]}` · **{u['kind']}**")
                    st.markdown(u["body"][:4000])
                    st.divider()
            else:
                st.caption("No steps yet.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — FOLLOW-UPS  (chief of staff)
# ══════════════════════════════════════════════════════════════════════════════
with t_followups:
    hc1, hc2 = st.columns([4,1])
    with hc1:
        st.subheader("🧑‍💼 Chief of staff")
        st.caption("Works the neglected backlog on its own — held stories, drafts going "
                   "stale, dropped digs — rerunning, reviving, opening new threads, and "
                   "clearing dead ones. Autonomous; only your review gate is reserved.")
    with hc2:
        st.write("")
        if st.button("▶ Run sweep now", use_container_width=True, type="primary"):
            signal("run_chief_of_staff", "1")
            st.success("Sweep queued (~2 min)."); st.cache_data.clear()

    st.caption(f"Last sweep: {_since(kv_get('last_cos_at'))}")
    st.divider()

    brief = kv_get("latest_cos_brief")
    if not brief:
        empty_state("🧑‍💼", "No sweep has run yet",
                    "Hit ‘Run sweep now’ — the chief of staff will work the backlog and act.")
    else:
        # What it DID this sweep (executed autonomously)
        try:
            acted = json.loads(kv_get("latest_cos_actions") or "[]")
        except Exception:
            acted = []
        eyebrow("Acted autonomously")
        if acted:
            for a in acted:
                st.markdown(
                    f"<div style='padding:8px 12px;border:1px solid {LINE};border-left:3px solid {GOLD};"
                    f"border-radius:8px;background:{SURFACE};margin-bottom:6px;font-size:13px;color:{KRAFT}'>"
                    f"{a}</div>", unsafe_allow_html=True)
            st.caption("Done automatically — review results in Drafts / Digs. Nothing was published.")
        else:
            st.caption("No backlog actions needed this sweep.")

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # The reasoning (rationale for each recommendation the sweep acted on)
        m = re.search(r"RECOMMENDATIONS\s*(\[.*?\])\s*END_RECOMMENDATIONS", brief, re.DOTALL)
        recs = []
        if m:
            try: recs = json.loads(m.group(1))
            except Exception: recs = []
        if recs:
            with st.expander(f"Why — reasoning for {len(recs)} call(s)"):
                for rec in recs:
                    st.markdown(f"**{rec.get('ref','')}** → `{rec.get('action','')}` — {rec.get('why','')}")

        prose = re.split(r"RECOMMENDATIONS\s*\[", brief)[0].strip()
        if prose:
            with st.expander("Full sweep brief"):
                st.markdown(prose)

        # New digs the sweep opened
        mnd = re.search(r"NEW_DIGS\s*(\[.*?\])\s*END_NEW_DIGS", brief, re.DOTALL)
        if mnd:
            try: newdigs = json.loads(mnd.group(1))
            except Exception: newdigs = []
            if newdigs:
                st.subheader(f"New threads proposed ({len(newdigs)})")
                st.caption("These were auto-opened as scoping digs — see the Digs tab.")
                for nd in newdigs:
                    st.markdown(f"- **{nd.get('title','')}** — {nd.get('question','')}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — SOURCES  (+ analyse)
# ══════════════════════════════════════════════════════════════════════════════
with t_sources:
    import yaml, pathlib
    st.subheader("Source performance")
    st.caption("Judge sources on what they actually produced — leads → drafts → "
               "published, and how often their leads get killed.")
    perf = q("""
        SELECT source,
               COUNT(*)                                                   AS runs,
               COUNT(*) FILTER (WHERE status='published')                 AS published,
               COUNT(*) FILTER (WHERE status IN ('killed','kill'))        AS killed,
               COUNT(*) FILTER (WHERE status IN ('held','hold'))          AS held,
               MAX(created_at)::date                                      AS last_seen
        FROM pipeline_runs
        GROUP BY source ORDER BY runs DESC
    """)
    if perf:
        pdf = pd.DataFrame(perf)
        pdf["kill_rate"] = (pdf["killed"] / pdf["runs"].replace(0, 1) * 100).map("{:.0f}%".format)
        pdf["pub_rate"]  = (pdf["published"] / pdf["runs"].replace(0, 1) * 100).map("{:.0f}%".format)
        st.dataframe(pdf[["source","runs","published","pub_rate","killed","kill_rate","held","last_seen"]],
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No runs yet to analyse.")

    st.divider()
    src_left, src_right = st.columns(2)

    with src_left:
        st.subheader("Active sources")
        sources_path = pathlib.Path(REPO_ROOT) / "engine" / "sources.yaml"
        if sources_path.exists():
            src_data = yaml.safe_load(sources_path.read_text())
            for s in src_data.get("sources", []):
                if s.get("status") == "active":
                    icon = "🎬" if s.get("platform") == "youtube" else "📰"
                    st.markdown(f"{icon} **{s['name']}** `{s.get('platform','')}` Tier {s.get('tier',3)}")
                    st.caption(f"  {s.get('lean','')[:60]}")
        st.divider()
        st.subheader("Approved via bot")
        approved = q("SELECT name, platform, lean, tier, added_at::date as added FROM approved_sources WHERE status='active'")
        if approved:
            st.dataframe(pd.DataFrame(approved), use_container_width=True, hide_index=True)
        else:
            st.caption("None yet.")

    with src_right:
        st.subheader("Pending proposals")
        proposals = q("""SELECT id, name, platform, lean, tier, role, notes, status
                         FROM source_proposals WHERE status='pending' ORDER BY id DESC""")
        if proposals:
            for p in proposals:
                with st.container(border=True):
                    st.markdown(f"**{p['name']}** — {p['platform']} · Tier {p['tier']}")
                    st.caption((p.get("lean","") or "") + " · " + (p.get("notes","") or "")[:80])
                    pc1, pc2 = st.columns(2)
                    if pc1.button("✓ Add", key=f"add_{p['id']}", type="primary", use_container_width=True):
                        execute("""INSERT INTO approved_sources (name,platform,lean,tier,role,notes)
                                   SELECT name,platform,lean,tier,role,notes FROM source_proposals WHERE id=%s""", (p["id"],))
                        execute("UPDATE source_proposals SET status='approved' WHERE id=%s", (p["id"],))
                        st.cache_data.clear(); st.rerun()
                    if pc2.button("✗ Skip", key=f"skp_{p['id']}", use_container_width=True):
                        execute("UPDATE source_proposals SET status='skipped' WHERE id=%s", (p["id"],))
                        st.cache_data.clear(); st.rerun()
        else:
            st.caption("No pending proposals.")

        st.divider()
        st.subheader("Add RSS source manually")
        with st.form("add_source_form"):
            s_name = st.text_input("Name")
            s_url  = st.text_input("RSS feed URL")
            s_plat = st.selectbox("Platform", ["web","youtube"])
            s_lean = st.text_input("Lean / description")
            s_tier = st.selectbox("Tier", [1,2,3], index=1)
            if st.form_submit_button("Add source", use_container_width=True):
                if s_name and s_url:
                    execute("""INSERT INTO approved_sources (name,platform,feed_url,lean,tier,role)
                               VALUES (%s,%s,%s,%s,%s,'lead')""",
                            (s_name, s_plat, s_url, s_lean, s_tier))
                    st.success(f"Added {s_name}. Active on next cycle.")
                    st.cache_data.clear()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — TASKS / SCHEDULES
# ══════════════════════════════════════════════════════════════════════════════
with t_tasks:
    st.subheader("Scheduled jobs")
    st.caption("Every periodic job the engine runs, with last-run and a manual trigger. "
               "Triggers write a signal the orchestrator picks up on its next 2-min tick.")

    # (label, last_at kv key, cadence text, signal key or None, signal value)
    JOBS = [
        ("📰 RSS / daily cycle",       "last_cycle_at",       "hourly-ish",  "force_rss_run", "1"),
        ("🕵️ Source scout",            "last_scout_at",       "weekly",      "force_scout_run", "1"),
        ("🗺️ Story scout (dig brief)",  "last_scout_at",       "weekly",      "dig_request",
         "infrastructure-concentration — Adani infrastructure footprint, anchored on Vizhinjam"),
        ("📌 Story tracker",           "last_tracker_at",     "weekly",      "force_tracker_run", "1"),
        ("🧑‍💼 Chief of staff",         "last_cos_at",         "daily",       "run_chief_of_staff", "1"),
        ("🔬 Dig auto-advance",        "last_dig_sweep_at",   "~6h",         None, None),
        ("🔁 Auto-recheck (held)",     "last_auto_recheck_at","~daily",      None, None),
        ("🧭 Meta-synthesis",          "last_meta_at",        "monthly",     "force_meta_run", "1"),
    ]
    for label, last_key, cadence, sig_key, sig_val in JOBS:
        jc1, jc2, jc3, jc4 = st.columns([3, 2, 2, 2])
        jc1.markdown(f"**{label}**")
        jc2.caption(f"cadence: {cadence}")
        jc3.caption(f"last: {_since(kv_get(last_key))}")
        if sig_key:
            if jc4.button("Run now", key=f"job_{last_key}_{sig_key}", use_container_width=True):
                signal(sig_key, sig_val)
                st.success(f"Signalled — runs within ~2 min."); st.cache_data.clear()
        else:
            jc4.caption("automatic")

    st.divider()
    st.subheader("⚡ Live agents")
    agents = q("""SELECT skill, model, topic, EXTRACT(EPOCH FROM (NOW()-started_at))::int AS secs
                  FROM active_agents ORDER BY started_at""")
    if agents:
        for ag in agents:
            m, s = divmod(ag["secs"] or 0, 60)
            st.write(f"{SKILL_ICON.get(ag['skill'],'🤖')} **{ag['skill']}** · "
                     f"{'Gemini' if ag['model'] and 'gemini' in ag['model'].lower() else 'Claude'} · "
                     f"{m}m {s}s" + (f" · {ag['topic'][:50]}" if ag["topic"] else ""))
    else:
        st.caption("Idle — nothing running.")

    st.divider()
    st.subheader("Queue")
    topics = q("""SELECT id, LEFT(topic,70) as topic, source, status
                  FROM pending_topics WHERE status IN ('queued','running') ORDER BY id""")
    if topics:
        for t in topics:
            icon = "🔄" if t["status"] == "running" else "⏳"
            st.write(f"{icon} **#{t['id']}** [{t['source']}] {t['topic']}")
    else:
        st.caption("Queue is empty.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 — COSTS
# ══════════════════════════════════════════════════════════════════════════════
with t_costs:
    import plotly.express as px

    usage_summary = q("""
        SELECT model,
            SUM(input_tokens)  FILTER (WHERE recorded_at::date=CURRENT_DATE) as ti,
            SUM(output_tokens) FILTER (WHERE recorded_at::date=CURRENT_DATE) as to_,
            SUM(input_tokens)  FILTER (WHERE DATE_TRUNC('month',recorded_at)=DATE_TRUNC('month',NOW())) as mi,
            SUM(output_tokens) FILTER (WHERE DATE_TRUNC('month',recorded_at)=DATE_TRUNC('month',NOW())) as mo,
            SUM(input_tokens)  as ai,
            SUM(output_tokens) as ao
        FROM token_usage GROUP BY model
    """)
    today_usd = month_usd = total_usd = 0.0
    for r in usage_summary:
        today_usd += cost(r["model"], r["ti"] or 0, r["to_"] or 0)
        month_usd += cost(r["model"], r["mi"] or 0, r["mo"] or 0)
        total_usd += cost(r["model"], r["ai"] or 0, r["ao"] or 0)
    mc1,mc2,mc3 = st.columns(3)
    mc1.metric("Today", f"₹{today_usd*_INR:.2f}", f"${today_usd:.4f}")
    mc2.metric("This month", f"₹{month_usd*_INR:.2f}", f"${month_usd:.4f}")
    mc3.metric("All time", f"₹{total_usd*_INR:.2f}", f"${total_usd:.4f}")

    st.divider()
    ch1, ch2 = st.columns(2)
    with ch1:
        daily = q("""SELECT recorded_at::date as date, model,
                            SUM(input_tokens) as i, SUM(output_tokens) as o
                     FROM token_usage GROUP BY date, model ORDER BY date""")
        if daily:
            df_daily = pd.DataFrame(daily)
            df_daily["inr"] = df_daily.apply(lambda r: cost(r["model"], r["i"] or 0, r["o"] or 0), axis=1) * _INR
            fig = px.bar(df_daily, x="date", y="inr", color="model", title="Daily spend (₹)")
            fig.update_layout(height=300, margin=dict(t=40,b=0,l=0,r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No usage data yet.")
    with ch2:
        if usage_summary:
            df_model = pd.DataFrame([{"model": r["model"],
                                      "cost_usd": cost(r["model"], r["ai"] or 0, r["ao"] or 0)}
                                     for r in usage_summary])
            fig2 = px.pie(df_model, values="cost_usd", names="model", title="All-time spend by model")
            fig2.update_layout(height=300, margin=dict(t=40,b=0,l=0,r=0))
            st.plotly_chart(fig2, use_container_width=True)

    st.subheader("By skill (all time)")
    skill_usage = q("""SELECT skill, model, SUM(input_tokens) as i, SUM(output_tokens) as o, COUNT(*) as runs
                       FROM token_usage GROUP BY skill, model ORDER BY SUM(input_tokens)+SUM(output_tokens) DESC""")
    if skill_usage:
        df_skill = pd.DataFrame(skill_usage)
        df_skill["cost_inr"] = df_skill.apply(lambda r: cost(r["model"], r["i"] or 0, r["o"] or 0)*_INR, axis=1).map("₹{:.4f}".format)
        df_skill["tokens"] = df_skill["i"].astype(str) + " in + " + df_skill["o"].astype(str) + " out"
        st.dataframe(df_skill[["skill","model","tokens","runs","cost_inr"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No skill usage recorded yet.")

    st.divider()
    st.subheader("Published")
    pubs = q("""SELECT p.id, p.published_at::date as date, r.throughline, r.source, r.trust_gate
                FROM publications p JOIN pipeline_runs r ON r.id=p.run_id ORDER BY p.id DESC""")
    if pubs:
        st.dataframe(pd.DataFrame(pubs), use_container_width=True, hide_index=True)
    else:
        st.info("Nothing published yet.")
