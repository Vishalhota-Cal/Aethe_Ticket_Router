"""
ui/streamlit_app.py

A polished demo frontend: light background, soft purple/pink gradient
blur, a floating
pill-shaped header, black bold headlines, indigo-blue accents. Still
only ever talks to the FastAPI service over HTTP -- never imports the
orchestrator directly -- so there is exactly one code path that makes
routing decisions, not two that could drift apart.
"""

import io

import pandas as pd
import requests
import streamlit as st

API_URL = "http://127.0.0.1:8000/tickets/route"

st.set_page_config(
    page_title="AI Smart Ticket Router",
    page_icon="◈",
    layout="wide",
)

# ---------------------------------------------------------------------
# Styling -- light theme, soft gradient blur, pill badges. Visual layer
# only; none of the request logic below changes.
# ---------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Space Grotesk', sans-serif;
    }

    .stApp {
        background: radial-gradient(ellipse at 25% 0%, #E9D8FD 0%, #FBE4F0 32%, #FDFBFF 62%, #FFFFFF 100%);
        color: #111827;
    }

    #MainMenu, footer, header {visibility: hidden;}

    .header-pill {
        background: rgba(255,255,255,0.75);
        border: 1px solid rgba(0,0,0,0.05);
        border-radius: 999px;
        padding: 12px 24px;
        display: flex;
        align-items: center;
        gap: 10px;
        box-shadow: 0 8px 30px rgba(80,60,140,0.08);
        margin-bottom: 2.2rem;
        width: fit-content;
    }

    .header-logo {
        font-weight: 700;
        font-size: 1.05rem;
        color: #111827;
    }

    .nav-tag {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.03em;
        background: #F3F0FA;
        color: #6D5BD0;
        margin-left: 6px;
    }

    .hero-title {
        font-size: 2.8rem;
        font-weight: 700;
        line-height: 1.15;
        color: #0F172A;
        margin-bottom: 0.6rem;
    }

    .hero-subtitle {
        color: #4B5563;
        font-size: 1.02rem;
        max-width: 620px;
        margin-bottom: 1.4rem;
    }

    .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: #6D5BD0;
    }

    .stat-label {
        color: #6B7280;
        font-size: 0.85rem;
    }

    .glass-card {
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.05);
        border-radius: 20px;
        padding: 1.6rem 1.6rem 1.2rem 1.6rem;
        box-shadow: 0 10px 40px rgba(80,60,140,0.07);
    }

    .pipeline-step {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.82rem;
        color: #4B5563;
        margin-bottom: 6px;
    }

    .pipeline-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #34D399;
    }

    .badge-pill {
        display: inline-block;
        padding: 5px 14px;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 600;
        margin-right: 8px;
        margin-bottom: 8px;
    }

    .confidence-mono {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.7rem;
        font-weight: 600;
        color: #6D5BD0;
    }

    div.stButton > button {
        background: #3454F4;
        color: white;
        border: none;
        border-radius: 999px;
        padding: 0.6rem 1.6rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        transition: transform 0.15s ease;
    }
    div.stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 18px rgba(52,84,244,0.3);
    }

    .footer-note {
        color: #9CA3AF;
        font-size: 0.78rem;
        margin-top: 2.5rem;
        letter-spacing: 0.03em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Header + hero
# ---------------------------------------------------------------------
st.markdown(
    """
    <div class="header-pill">
        <span class="header-logo">◈ AI Smart Ticket Router</span>
        <span class="nav-tag">MULTI-AGENT</span>
        <span class="nav-tag">OPENAI-BACKED</span>
        <span class="nav-tag">SELF-REPAIRING</span>
    </div>
    <div class="hero-title">Intent is the ticket.<br/>Agents are the response.</div>
    <div class="hero-subtitle">
        Describe a ticket -- or upload a batch. Triage, validation, and
        review agents classify, prioritize, and route every one, with
        automatic repair on malformed AI output and a deterministic
        human-review check every time.
    </div>
    """,
    unsafe_allow_html=True,
)

if "result" not in st.session_state:
    st.session_state.result = None
if "error" not in st.session_state:
    st.session_state.error = None
if "batch_results" not in st.session_state:
    st.session_state.batch_results = None

PRIORITY_COLORS = {
    "Critical": ("#DC2626", "rgba(220,38,38,0.10)"),
    "High": ("#EA580C", "rgba(234,88,12,0.10)"),
    "Medium": ("#CA8A04", "rgba(202,138,4,0.10)"),
    "Low": ("#059669", "rgba(5,150,105,0.10)"),
}


def route_one(subject: str, description: str, ticket_id: str = "482") -> dict:
    """Call the API once for a single ticket, returning the parsed
    JSON response or raising for the caller to handle.
    """
    payload = {"id": ticket_id, "subject": subject, "description": description}
    response = requests.post(API_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


tab_single, tab_batch = st.tabs(["Single Ticket", "Batch Upload (CSV)"])

# ---------------------------------------------------------------------
# Tab 1 -- single ticket
# ---------------------------------------------------------------------
with tab_single:
    left, right = st.columns([1, 1], gap="large")

    with left:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("**Submit a ticket**")

        subject = st.text_input("Subject", "Can't log in - urgent, demo in 30 minutes")
        description = st.text_area(
            "Description",
            "I've been locked out of my account for the last 2 hours. "
            "I have a client demo in 30 minutes and really need this fixed immediately.",
            height=140,
        )

        st.markdown(
            """
            <div style="margin-top:8px; margin-bottom:14px;">
                <div class="pipeline-step"><div class="pipeline-dot"></div> Triage Agent -- classify, prioritize, assign</div>
                <div class="pipeline-step"><div class="pipeline-dot"></div> Validation Agent -- schema check + self-repair</div>
                <div class="pipeline-step"><div class="pipeline-dot"></div> Review Agent -- deterministic human-review rules</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Route ticket"):
            try:
                st.session_state.result = route_one(subject, description)
                st.session_state.error = None
            except requests.exceptions.RequestException as exc:
                st.session_state.result = None
                st.session_state.error = str(exc)

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("**Routing decision**")

        if st.session_state.error:
            st.markdown(
                f'<div class="badge-pill" style="background:rgba(220,38,38,0.10); color:#DC2626;">Request failed</div>'
                f'<p style="color:#B91C1C; font-size:0.85rem;">{st.session_state.error}</p>',
                unsafe_allow_html=True,
            )
        elif st.session_state.result:
            data = st.session_state.result
            r = data["result"]
            trace = data.get("trace", [])

            p_color, p_bg = PRIORITY_COLORS.get(r["priority"], ("#374151", "rgba(55,65,81,0.08)"))
            review_color, review_bg, review_text = (
                ("#DC2626", "rgba(220,38,38,0.10)", "Human review required")
                if r["needs_human_review"]
                else ("#059669", "rgba(5,150,105,0.10)", "Auto-approved")
            )

            st.markdown(
                f"""
                <span class="badge-pill" style="background:#F3F0FA; color:#6D5BD0;">{r['category']}</span>
                <span class="badge-pill" style="background:{p_bg}; color:{p_color};">{r['priority']} priority</span>
                <span class="badge-pill" style="background:#EFF4FF; color:#3454F4;">{r['assigned_team']}</span>
                <span class="badge-pill" style="background:{review_bg}; color:{review_color};">{review_text}</span>
                <p style="margin-top:14px; color:#374151; font-size:0.92rem;">{r['reason']}</p>
                <div style="margin-top:10px; color:#6B7280; font-size:0.78rem; text-transform:uppercase; letter-spacing:0.05em;">Confidence</div>
                <div class="confidence-mono">{r['confidence_score']}<span style="font-size:1rem; color:#9CA3AF;"> / 100</span></div>
                """,
                unsafe_allow_html=True,
            )

            if trace:
                st.markdown(
                    '<div style="margin-top:20px; color:#6B7280; font-size:0.78rem; text-transform:uppercase; letter-spacing:0.05em;">Live flow</div>',
                    unsafe_allow_html=True,
                )
                for step in trace:
                    dot_color = "#059669" if step["success"] else "#DC2626"
                    st.markdown(
                        f"""
                        <div class="pipeline-step" style="margin-top:6px;">
                            <div class="pipeline-dot" style="background:{dot_color};"></div>
                            {step['agent_name']}
                            <span style="margin-left:auto; font-family:'JetBrains Mono', monospace; color:#9CA3AF;">{step['duration_ms']:.0f} ms</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.markdown(
                '<p style="color:#9CA3AF; font-size:0.9rem;">Submit a ticket to see the routing decision here.</p>',
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Tab 2 -- batch CSV upload
# ---------------------------------------------------------------------
with tab_batch:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("**Upload a CSV of tickets**")
    st.markdown(
        '<p style="color:#6B7280; font-size:0.85rem;">Expected columns: <code>id</code> (optional), '
        '<code>subject</code>, <code>description</code>.</p>',
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader("CSV file", type=["csv"])

    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)

        if "subject" not in df.columns or "description" not in df.columns:
            st.error("CSV must have at least 'subject' and 'description' columns.")
        else:
            if "id" not in df.columns:
                df["id"] = [str(i + 1) for i in range(len(df))]

            st.markdown(f"**Preview** ({len(df)} tickets)")
            st.dataframe(df.head(10), use_container_width=True)

            if st.button("Route all tickets"):
                progress = st.progress(0.0, text="Starting...")
                results = []

                for i, row in df.iterrows():
                    progress.progress(
                        (i + 1) / len(df),
                        text=f"Routing ticket {i + 1} of {len(df)}...",
                    )
                    try:
                        data = route_one(row["subject"], row["description"], str(row["id"]))
                        r = data["result"]
                        results.append(
                            {
                                "id": row["id"],
                                "subject": row["subject"],
                                "category": r["category"],
                                "priority": r["priority"],
                                "assigned_team": r["assigned_team"],
                                "confidence_score": r["confidence_score"],
                                "needs_human_review": r["needs_human_review"],
                                "reason": r["reason"],
                                "status": "ok",
                            }
                        )
                    except requests.exceptions.RequestException as exc:
                        results.append(
                            {
                                "id": row["id"],
                                "subject": row["subject"],
                                "category": None,
                                "priority": None,
                                "assigned_team": None,
                                "confidence_score": None,
                                "needs_human_review": None,
                                "reason": str(exc),
                                "status": "failed",
                            }
                        )

                progress.empty()
                st.session_state.batch_results = pd.DataFrame(results)

    if st.session_state.batch_results is not None:
        results_df = st.session_state.batch_results

        st.markdown("**Results**")
        st.dataframe(results_df, use_container_width=True)

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown(
                f'<div class="stat-number">{len(results_df)}</div><div class="stat-label">Tickets processed</div>',
                unsafe_allow_html=True,
            )
        with col_b:
            flagged = int(results_df["needs_human_review"].fillna(False).sum())
            st.markdown(
                f'<div class="stat-number">{flagged}</div><div class="stat-label">Flagged for human review</div>',
                unsafe_allow_html=True,
            )
        with col_c:
            failed = int((results_df["status"] == "failed").sum())
            st.markdown(
                f'<div class="stat-number">{failed}</div><div class="stat-label">Failed requests</div>',
                unsafe_allow_html=True,
            )

        if results_df["category"].notna().any():
            st.markdown("**Category distribution**")
            st.bar_chart(results_df["category"].value_counts())

        csv_bytes = results_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download results as CSV",
            data=csv_bytes,
            file_name="routed_tickets.csv",
            mime="text/csv",
        )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown(
    '<div class="footer-note">AI Smart Ticket Router -- built by Vishal Hota, Calfus.</div>',
    unsafe_allow_html=True,
)