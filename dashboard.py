"""
Thelivu local dashboard — run with:
    streamlit run dashboard.py
"""

import os
import psycopg2
import psycopg2.extras
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:BuxogDsXgJmVnccpWPVYwKvGBksNBfyq@reseau.proxy.rlwy.net:43183/railway"
)

st.set_page_config(page_title="Thelivu", page_icon="📰", layout="wide")

_CLAUDE_IN  = 3.00;  _CLAUDE_OUT = 15.00
_GEMINI_IN  = 0.30;  _GEMINI_OUT = 1.00
_INR        = 84


def calc_cost(model, i, o):
    if model and "gemini" in model.lower():
        return (i / 1e6 * _GEMINI_IN) + (o / 1e6 * _GEMINI_OUT)
    return (i / 1e6 * _CLAUDE_IN) + (o / 1e6 * _CLAUDE_OUT)


@st.cache_data(ttl=15)
def query(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def scalar(sql, params=None):
    rows = query(sql, params)
    if rows:
        return list(rows[0].values())[0]
    return 0


# ── Header ──────────────────────────────────────────────────────────────────
st.title("📰 Thelivu Dashboard")
st.caption(f"Live — refreshes every 15s · {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

if st.button("🔄 Refresh now"):
    st.cache_data.clear()
    st.rerun()

# ── Top metrics ──────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)

runs = query("SELECT status, COUNT(*) as n FROM pipeline_runs GROUP BY status")
run_map = {r["status"]: r["n"] for r in runs}

c1.metric("Investigating", run_map.get("investigating", 0) + run_map.get("writing", 0))
c2.metric("Pending review", run_map.get("pending_human", 0))
c3.metric("Published", scalar("SELECT COUNT(*) FROM publications"))
c4.metric("Killed", run_map.get("killed", 0) + run_map.get("kill", 0))
c5.metric("Held", run_map.get("held", 0) + run_map.get("hold", 0))

st.divider()

# ── Live agents ──────────────────────────────────────────────────────────────
agents = query("""
    SELECT a.skill, a.model, a.topic,
           EXTRACT(EPOCH FROM (NOW() - a.started_at))::int AS elapsed_secs,
           a.run_id
    FROM active_agents a
    ORDER BY a.started_at
""")

SKILL_ICON = {
    "news-investigator": "🔍", "source-verifier": "🔎", "news-monitor": "📡",
    "article-writer": "✍️", "editorial-reviewer": "📝", "pattern-synthesizer": "🧩",
    "topic-intake": "📥", "source-scout": "🕵️", "beat-monitor": "📻",
    "story-scout": "🗺️", "publisher": "📤", "finance-manager": "💰",
}

if agents:
    st.subheader(f"⚡ Live agents ({len(agents)} running)")
    cols = st.columns(len(agents)) if len(agents) <= 4 else st.columns(4)
    for i, ag in enumerate(agents):
        mins, secs = divmod(ag["elapsed_secs"] or 0, 60)
        elapsed = f"{mins}m {secs}s" if mins else f"{secs}s"
        icon = SKILL_ICON.get(ag["skill"], "🤖")
        model_short = "Gemini" if ag["model"] and "gemini" in ag["model"].lower() else "Claude"
        with cols[i % 4]:
            st.metric(
                label=f"{icon} {ag['skill']}",
                value=model_short,
                delta=f"running {elapsed}",
            )
            if ag["topic"]:
                st.caption(ag["topic"][:60])
else:
    st.subheader("⚡ Live agents")
    st.caption("No agents running right now.")

st.divider()

# ── Live pipeline & costs ────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("Pipeline runs")
    runs_data = query("""
        SELECT id, created_at::date as date, source, throughline,
               trust_gate, status, updated_at
        FROM pipeline_runs
        ORDER BY id DESC LIMIT 30
    """)
    if runs_data:
        STATUS_ICON = {
            "investigating": "🔍", "writing": "✍️",
            "pending_human": "📬", "published": "✅",
            "killed": "❌", "kill": "❌",
            "held": "⏸", "hold": "⏸",
        }
        df = pd.DataFrame(runs_data)
        df["status"] = df["status"].apply(lambda s: f"{STATUS_ICON.get(s,'?')} {s}")
        df["throughline"] = df["throughline"].apply(lambda t: (t or "")[:80])
        df["updated_at"] = pd.to_datetime(df["updated_at"]).dt.strftime("%H:%M")
        st.dataframe(
            df[["id", "date", "source", "throughline", "trust_gate", "status", "updated_at"]],
            use_container_width=True, hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("Run", width="small"),
                "date": st.column_config.TextColumn("Date", width="small"),
                "trust_gate": st.column_config.TextColumn("Gate", width="small"),
                "updated_at": st.column_config.TextColumn("Updated", width="small"),
            }
        )
    else:
        st.info("No pipeline runs yet.")

with right:
    st.subheader("Costs")

    usage = query("""
        SELECT model,
            SUM(input_tokens)  FILTER (WHERE recorded_at::date = CURRENT_DATE)  as today_in,
            SUM(output_tokens) FILTER (WHERE recorded_at::date = CURRENT_DATE)  as today_out,
            SUM(input_tokens)  FILTER (WHERE DATE_TRUNC('month', recorded_at) = DATE_TRUNC('month', NOW())) as month_in,
            SUM(output_tokens) FILTER (WHERE DATE_TRUNC('month', recorded_at) = DATE_TRUNC('month', NOW())) as month_out,
            SUM(input_tokens)  as total_in,
            SUM(output_tokens) as total_out
        FROM token_usage GROUP BY model
    """)

    today_usd = month_usd = total_usd = 0.0
    for row in usage:
        today_usd += calc_cost(row["model"], row["today_in"] or 0, row["today_out"] or 0)
        month_usd += calc_cost(row["model"], row["month_in"] or 0, row["month_out"] or 0)
        total_usd += calc_cost(row["model"], row["total_in"] or 0, row["total_out"] or 0)

    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Today", f"₹{today_usd * _INR:.2f}")
    cc2.metric("This month", f"₹{month_usd * _INR:.2f}")
    cc3.metric("All time", f"₹{total_usd * _INR:.2f}")

    if usage:
        st.caption("By model:")
        for row in usage:
            c = calc_cost(row["model"], row["today_in"] or 0, row["today_out"] or 0)
            in_tok  = (row["today_in"] or 0)
            out_tok = (row["today_out"] or 0)
            st.caption(f"  {row['model']}: {in_tok:,} in + {out_tok:,} out = ${c:.4f} today")

    st.divider()

    st.subheader("Queue")
    topics = query("""
        SELECT id, topic, status, submitted_at::date as date
        FROM pending_topics WHERE status IN ('queued','running')
        ORDER BY id
    """)
    if topics:
        for t in topics:
            icon = "🔄" if t["status"] == "running" else "⏳"
            st.write(f"{icon} **#{t['id']}** {t['topic'][:70]}")
    else:
        st.caption("No topics queued.")

st.divider()

# ── Sources ──────────────────────────────────────────────────────────────────
st.subheader("RSS Sources")
sc1, sc2 = st.columns(2)

with sc1:
    st.caption("Active (from sources.yaml)")
    import yaml, pathlib
    sources_path = pathlib.Path(__file__).parent / "engine" / "sources.yaml"
    if sources_path.exists():
        src_data = yaml.safe_load(sources_path.read_text())
        for s in src_data.get("sources", []):
            icon = "✓" if s.get("status") == "active" else "?"
            st.caption(f"  {icon} {s['name']} — {s.get('lean','')[:40]}")

with sc2:
    st.caption("Approved via bot")
    approved = query("SELECT name, platform, lean, added_at::date as added FROM approved_sources WHERE status='active'")
    if approved:
        st.dataframe(pd.DataFrame(approved), use_container_width=True, hide_index=True)
    else:
        st.caption("None yet.")

# ── Recent publications ───────────────────────────────────────────────────────
st.divider()
st.subheader("Published")
pubs = query("""
    SELECT p.id, p.published_at::date as date, r.throughline, r.source
    FROM publications p JOIN pipeline_runs r ON r.id = p.run_id
    ORDER BY p.id DESC LIMIT 10
""")
if pubs:
    st.dataframe(pd.DataFrame(pubs), use_container_width=True, hide_index=True)
else:
    st.info("Nothing published yet — approve your first story to see it here.")
