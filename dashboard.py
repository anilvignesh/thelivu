"""Thelivu — Management Dashboard. Run: streamlit run dashboard.py"""

import os
import time
import json
import requests
import psycopg2
import psycopg2.extras
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
DB_URL         = os.environ.get("DATABASE_URL", "postgresql://postgres:BuxogDsXgJmVnccpWPVYwKvGBksNBfyq@reseau.proxy.rlwy.net:43183/railway")
BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "8548128849:AAHMuf4gL3g092AhqwQL_MeMcp9NVjss6YE")
CHANNEL_ID     = os.environ.get("TELEGRAM_CHANNEL_ID", "@thelivu")
DRAFT_CHAT_ID  = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "7307159646")
TG_API        = f"https://api.telegram.org/bot{BOT_TOKEN}"

_CLAUDE_IN = 3.00; _CLAUDE_OUT = 15.00
_GEMINI_IN = 0.30; _GEMINI_OUT = 1.00
_INR = 84

st.set_page_config(page_title="Thelivu", page_icon="📰", layout="wide")

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
    if model and "gemini" in model.lower():
        return (i/1e6*_GEMINI_IN) + (o/1e6*_GEMINI_OUT)
    return (i/1e6*_CLAUDE_IN) + (o/1e6*_CLAUDE_OUT)

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

# ── Status helpers ────────────────────────────────────────────────────────────
STATUS_ICON = {
    "investigating": "🔍", "writing": "✍️", "pending_human": "📬",
    "published": "✅", "killed": "❌", "kill": "❌", "held": "⏸", "hold": "⏸",
}
SKILL_ICON = {
    "news-investigator": "🔍", "source-verifier": "🔎", "news-monitor": "📡",
    "article-writer": "✍️", "editorial-reviewer": "📝", "pattern-synthesizer": "🧩",
    "topic-intake": "📥", "source-scout": "🕵️", "beat-monitor": "📻",
    "story-scout": "🗺️", "publisher": "📤", "finance-manager": "💰",
    "source-ingestor": "📼",
}

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_refresh, col_time = st.columns([4, 1, 2])
with col_title:
    st.title("📰 Thelivu")
with col_refresh:
    st.write("")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear(); st.rerun()
with col_time:
    st.caption(f"Updated {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

# ── Tabs ──────────────────────────────────────────────────────────────────────
t_overview, t_drafts, t_pipeline, t_sources, t_costs = st.tabs(
    ["Overview", "Drafts", "Pipeline", "Sources", "Costs"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with t_overview:
    # Metrics row
    runs = q("SELECT status, COUNT(*) as n FROM pipeline_runs GROUP BY status")
    rm = {r["status"]: r["n"] for r in runs}
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Live", rm.get("investigating",0)+rm.get("writing",0))
    c2.metric("Pending review", rm.get("pending_human",0))
    c3.metric("Published", scalar("SELECT COUNT(*) FROM publications"))
    c4.metric("Killed", rm.get("killed",0)+rm.get("kill",0))
    c5.metric("Held", rm.get("held",0)+rm.get("hold",0))

    st.divider()
    left, right = st.columns([3,2])

    with left:
        # Live agents
        agents = q("""
            SELECT skill, model, topic,
                   EXTRACT(EPOCH FROM (NOW()-started_at))::int AS secs
            FROM active_agents ORDER BY started_at
        """)
        if agents:
            st.subheader(f"⚡ Live agents — {len(agents)} running")
            cols = st.columns(min(len(agents), 4))
            for i, ag in enumerate(agents):
                m, s = divmod(ag["secs"] or 0, 60)
                icon = SKILL_ICON.get(ag["skill"], "🤖")
                model_s = "Gemini" if ag["model"] and "gemini" in ag["model"].lower() else "Claude"
                with cols[i % 4]:
                    st.metric(f"{icon} {ag['skill']}", model_s, f"{m}m {s}s" if m else f"{s}s")
                    if ag["topic"]: st.caption(ag["topic"][:55])
        else:
            st.subheader("⚡ Live agents")
            st.caption("Idle — no skills running right now.")

        st.divider()

        # Recent runs
        st.subheader("Recent runs")
        recent = q("SELECT id, created_at::date as date, source, LEFT(throughline,70) as story, trust_gate, status, updated_at::time(0) as updated FROM pipeline_runs ORDER BY id DESC LIMIT 10")
        if recent:
            df = pd.DataFrame(recent)
            df["status"] = df["status"].apply(lambda s: f"{STATUS_ICON.get(s,'?')} {s}")
            st.dataframe(df, use_container_width=True, hide_index=True,
                column_config={"id": st.column_config.NumberColumn("Run", width="small"),
                                "date": st.column_config.TextColumn("Date", width="small"),
                                "trust_gate": st.column_config.TextColumn("Gate", width="small"),
                                "updated": st.column_config.TextColumn("At", width="small")})
        else:
            st.info("No pipeline runs yet.")

    with right:
        # Quick actions
        st.subheader("Actions")
        with st.form("topic_form"):
            topic_input = st.text_area("Submit a topic", placeholder="What's the story?", height=80)
            submitted = st.form_submit_button("Submit topic →", use_container_width=True)
            if submitted and topic_input.strip():
                execute("INSERT INTO pending_topics (topic, source) VALUES (%s, %s)",
                        (topic_input.strip(), "dashboard"))
                st.success("Queued — agent picks it up within 2 minutes.")
                st.cache_data.clear()

        if st.button("Force RSS cycle now", use_container_width=True):
            execute("INSERT INTO kv_store (key, value, updated_at) VALUES ('force_rss_run','1',NOW()) ON CONFLICT (key) DO UPDATE SET value='1', updated_at=NOW()")
            st.success("Signalled — agent will run RSS cycle on next tick.")

        st.divider()

        # Queue
        st.subheader("Queue")
        topics = q("SELECT id, LEFT(topic,65) as topic, status, submitted_at::date as date FROM pending_topics WHERE status IN ('queued','running') ORDER BY id")
        if topics:
            for t in topics:
                icon = "🔄" if t["status"] == "running" else "⏳"
                st.write(f"{icon} **#{t['id']}** {t['topic']}")
        else:
            st.caption("Queue is empty.")

        st.divider()

        # Today's cost
        st.subheader("Cost today")
        usage = q("""SELECT model, SUM(input_tokens) as i, SUM(output_tokens) as o
                     FROM token_usage WHERE recorded_at::date = CURRENT_DATE GROUP BY model""")
        today_usd = sum(cost(r["model"], r["i"] or 0, r["o"] or 0) for r in usage)
        st.metric("Today", f"₹{today_usd*_INR:.2f}", f"${today_usd:.4f}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DRAFTS
# ══════════════════════════════════════════════════════════════════════════════
with t_drafts:
    drafts = q("""SELECT id, created_at::date as date, source, throughline,
                         trust_gate, draft_text, review_text, verification_report
                  FROM pipeline_runs WHERE status='pending_human' ORDER BY id DESC""")

    held = q("""SELECT id, created_at::date as date, source, throughline, trust_gate
                FROM pipeline_runs WHERE status IN ('held','hold') ORDER BY id DESC""")

    if not drafts and not held:
        st.info("No drafts pending review. Stories will appear here when ready.")
    else:
        st.caption(f"{len(drafts)} pending review · {len(held)} on hold")

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
                    draft_text = run.get("draft_text") or ""
                    msg_ids = tg_post_channel(draft_text)
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
                hc1, hc2 = st.columns([5,1])
                with hc1:
                    st.markdown(f"**#{run['id']}** — {(run['throughline'] or '')[:100]}")
                    st.caption(f"{run['date']} · {run['source']}")
                with hc2:
                    if st.button("Requeue", key=f"req_{run['id']}", use_container_width=True):
                        execute("UPDATE pipeline_runs SET status='pending_human', updated_at=NOW() WHERE id=%s", (run['id'],))
                        st.cache_data.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PIPELINE
# ══════════════════════════════════════════════════════════════════════════════
with t_pipeline:
    status_filter = st.selectbox("Filter by status", ["all","investigating","writing","pending_human","published","killed","held"], index=0)

    sql = "SELECT id, created_at, source, throughline, trust_gate, status, updated_at FROM pipeline_runs"
    if status_filter != "all":
        sql += f" WHERE status='{status_filter}'"
    sql += " ORDER BY id DESC LIMIT 50"

    all_runs = q(sql)
    if not all_runs:
        st.info("No runs match this filter.")
    else:
        for run in all_runs:
            icon = STATUS_ICON.get(run["status"], "?")
            label = f"{icon} **#{run['id']}** {(run['throughline'] or 'Untitled')[:80]}"
            with st.expander(label):
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("Status", run["status"])
                dc2.metric("Gate", run["trust_gate"] or "—")
                dc3.metric("Source", run["source"] or "—")
                st.caption(f"Created: {run['created_at']} · Updated: {run['updated_at']}")

                detail = q("SELECT draft_text, review_text, verification_report FROM pipeline_runs WHERE id=%s", (run["id"],))
                if detail:
                    d = detail[0]
                    t1, t2, t3 = st.tabs(["Draft", "Review", "Verification"])
                    with t1: st.markdown(d.get("draft_text") or "_Not yet written._")
                    with t2: st.text(d.get("review_text") or "_No review._")
                    with t3: st.text(d.get("verification_report") or "_No verification._")

                if run["status"] == "pending_human":
                    bc1, bc2, bc3 = st.columns(3)
                    if bc1.button("✓ Approve", key=f"pa_{run['id']}", type="primary"):
                        draft_text = (detail[0].get("draft_text") or "") if detail else ""
                        try:
                            msg_ids = tg_post_channel(draft_text)
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
# TAB 4 — SOURCES
# ══════════════════════════════════════════════════════════════════════════════
with t_sources:
    import yaml, pathlib
    src_left, src_right = st.columns(2)

    with src_left:
        st.subheader("Active sources")
        sources_path = pathlib.Path(__file__).parent / "engine" / "sources.yaml"
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
                    st.caption(p.get("lean","") + " · " + (p.get("notes","")[:80]))
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
# TAB 5 — COSTS
# ══════════════════════════════════════════════════════════════════════════════
with t_costs:
    import plotly.express as px
    import plotly.graph_objects as go

    # Summary metrics
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
        # Daily spend chart
        daily = q("""
            SELECT recorded_at::date as date, model,
                   SUM(input_tokens) as i, SUM(output_tokens) as o
            FROM token_usage GROUP BY date, model ORDER BY date
        """)
        if daily:
            df_daily = pd.DataFrame(daily)
            df_daily["usd"] = df_daily.apply(lambda r: cost(r["model"], r["i"] or 0, r["o"] or 0), axis=1)
            df_daily["inr"] = df_daily["usd"] * _INR
            fig = px.bar(df_daily, x="date", y="inr", color="model", title="Daily spend (₹)",
                         color_discrete_map={"claude-sonnet-4-6": "#6366f1", "gemini-2.5-flash": "#10b981"})
            fig.update_layout(height=300, margin=dict(t=40,b=0,l=0,r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No usage data yet.")

    with ch2:
        # Per-model pie
        if usage_summary:
            df_model = pd.DataFrame([{
                "model": r["model"],
                "cost_usd": cost(r["model"], r["ai"] or 0, r["ao"] or 0)
            } for r in usage_summary])
            fig2 = px.pie(df_model, values="cost_usd", names="model", title="All-time spend by model")
            fig2.update_layout(height=300, margin=dict(t=40,b=0,l=0,r=0))
            st.plotly_chart(fig2, use_container_width=True)

    # Per-skill breakdown
    st.subheader("By skill (all time)")
    skill_usage = q("""
        SELECT skill, model, SUM(input_tokens) as i, SUM(output_tokens) as o, COUNT(*) as runs
        FROM token_usage GROUP BY skill, model ORDER BY i+o DESC
    """)
    if skill_usage:
        df_skill = pd.DataFrame(skill_usage)
        df_skill["cost_inr"] = df_skill.apply(lambda r: cost(r["model"], r["i"] or 0, r["o"] or 0)*_INR, axis=1)
        df_skill["cost_inr"] = df_skill["cost_inr"].map("₹{:.4f}".format)
        df_skill["tokens"] = df_skill["i"].astype(str) + " in + " + df_skill["o"].astype(str) + " out"
        st.dataframe(df_skill[["skill","model","tokens","runs","cost_inr"]],
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No skill usage recorded yet.")

    # Published stories
    st.divider()
    st.subheader("Published")
    pubs = q("""SELECT p.id, p.published_at::date as date, r.throughline, r.source, r.trust_gate
                FROM publications p JOIN pipeline_runs r ON r.id=p.run_id ORDER BY p.id DESC""")
    if pubs:
        st.dataframe(pd.DataFrame(pubs), use_container_width=True, hide_index=True)
    else:
        st.info("Nothing published yet.")
