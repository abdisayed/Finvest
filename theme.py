"""Shared look & feel for FinVest (CSS + small UI helpers)."""
import html
import pandas as pd
import streamlit as st

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root{
  --ink:#080D1A; --panel:rgba(16,24,43,.78); --line:#1F2C45; --muted:#8B9AB5;
  --text:#E8EDF7; --accent:#5B8CFF; --up:#2DD4A0; --down:#FF5C7A; --warn:#FFB547;
}
html, body, .stApp { font-family:'Plus Jakarta Sans', system-ui, sans-serif; }
.stApp{
  color:var(--text);
  background:
    radial-gradient(1100px 520px at 8% -8%, rgba(91,140,255,.20), transparent 60%),
    radial-gradient(800px 480px at 100% 0%, rgba(45,212,160,.10), transparent 55%),
    var(--ink);
}
footer { visibility:hidden; }
header[data-testid="stHeader"]{ background:transparent !important; }
[data-testid="stDecoration"]{ display:none; }
.block-container{ padding-top:1.6rem; max-width:1280px; }

/* sidebar */
[data-testid="stSidebar"]{ background:#0B1226; border-right:1px solid var(--line); }
[data-testid="stSidebar"] h1{ font-weight:800; letter-spacing:-.5px; }

/* hero */
.fv-hero{
  padding:22px 28px; border-radius:20px; margin-bottom:18px;
  background:linear-gradient(120deg, rgba(91,140,255,.22), rgba(45,212,160,.08));
  border:1px solid rgba(91,140,255,.28);
}
.fv-hero h1{ margin:0; font-size:1.9rem; font-weight:800; letter-spacing:-.6px; padding:0; }
.fv-hero p{ margin:6px 0 0; color:var(--muted); font-size:.98rem; }
.fv-section{ font-size:1.15rem; font-weight:700; margin:18px 0 8px; letter-spacing:-.2px; }

/* metrics */
div[data-testid="stMetric"]{
  background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:16px 18px;
}
div[data-testid="stMetricLabel"] p{ color:var(--muted); font-weight:600; }
div[data-testid="stMetricValue"]{ font-weight:800; letter-spacing:-.5px; }

/* buttons */
div.stButton > button, div[data-testid="stFormSubmitButton"] > button{
  border-radius:12px; font-weight:600; min-height:42px; border:1px solid var(--line);
  transition:transform .12s ease, border-color .12s ease;
}
div.stButton > button:hover{ border-color:var(--accent); transform:translateY(-1px); }
button[kind="primary"], button[data-testid="stBaseButton-primary"]{
  background:linear-gradient(135deg,#4F7BFF,#2DD4A0) !important; color:#04101F !important;
  border:none !important; font-weight:700 !important;
}

/* inputs */
div[data-baseweb="input"], div[data-baseweb="select"] > div, textarea{ border-radius:12px !important; }

/* radio -> pill/circle options (used for USD / INR toggle) */
div[data-testid="stRadio"] div[role="radiogroup"]{ gap:.5rem; }
div[data-testid="stRadio"] div[role="radiogroup"] label{
  background:rgba(22,32,56,.75); border:1px solid var(--line); border-radius:999px;
  padding:6px 16px 6px 12px; transition:border-color .12s ease;
}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){
  border-color:var(--accent); background:rgba(91,140,255,.16);
}
[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label{ width:100%; border-radius:12px; }

/* tabs / containers / expander */
button[data-baseweb="tab"]{ font-weight:600; }
div[data-testid="stExpander"]{ border:1px solid var(--line); border-radius:14px; background:rgba(16,24,43,.5); }
div[data-testid="stVerticalBlockBorderWrapper"]{ border-radius:16px; }
div[data-testid="stDataFrame"]{ border:1px solid var(--line); border-radius:14px; overflow:hidden; }

/* AI verdict card */
.fv-verdict{
  display:flex; align-items:center; gap:22px; padding:22px 26px; border-radius:20px;
  border:1px solid; margin:8px 0 14px;
}
.fv-verdict.buy { background:rgba(45,212,160,.10); border-color:rgba(45,212,160,.55); }
.fv-verdict.sell{ background:rgba(255,92,122,.10); border-color:rgba(255,92,122,.55); }
.fv-verdict.hold{ background:rgba(255,181,71,.10); border-color:rgba(255,181,71,.55); }
.fv-verdict .tag{ font-size:2.4rem; font-weight:800; letter-spacing:-1px; line-height:1; min-width:120px; }
.fv-verdict.buy .tag{ color:var(--up); } .fv-verdict.sell .tag{ color:var(--down); } .fv-verdict.hold .tag{ color:var(--warn); }
.fv-verdict .headline{ font-size:1.08rem; font-weight:600; }
.fv-verdict .sub{ color:var(--muted); margin-top:4px; font-size:.93rem; line-height:1.5; }
.fv-chips{ display:flex; flex-wrap:wrap; gap:8px; margin:6px 0 14px; }
.fv-chip{ padding:5px 12px; border-radius:999px; background:rgba(22,32,56,.85); border:1px solid var(--line); font-size:.82rem; color:var(--muted); }
.fv-chip b{ color:var(--text); font-weight:700; }
.fv-card{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:16px 20px; height:100%; }
.fv-card h4{ margin:0 0 8px; font-size:1rem; }
.fv-card ul{ margin:0; padding-left:18px; color:#CBD5E8; line-height:1.65; }
.fv-action{ margin-top:12px; padding:14px 18px; border-radius:14px; border:1px dashed var(--accent); background:rgba(91,140,255,.08); }
.fv-note{ color:var(--muted); font-size:.8rem; margin-top:10px; }
"""


def apply_theme():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def page_header(icon, title, subtitle):
    st.markdown(
        f'<div class="fv-hero"><h1>{icon} {html.escape(title)}</h1>'
        f'<p>{html.escape(subtitle)}</p></div>',
        unsafe_allow_html=True,
    )


def section(title):
    st.markdown(f'<div class="fv-section">{html.escape(title)}</div>', unsafe_allow_html=True)


def note(text):
    st.markdown(f'<div class="fv-note">{html.escape(text)}</div>', unsafe_allow_html=True)


def currency_toggle(key, default="INR"):
    """Two circle (radio) options: USD ($) and INR (₹)."""
    return st.radio(
        "Currency",
        ["USD", "INR"],
        index=1 if default == "INR" else 0,
        horizontal=True,
        key=key,
        format_func=lambda c: "USD  ($)" if c == "USD" else "INR  (₹)",
    )


def pnl_color(value):
    """Styler helper: green for profit, red for loss."""
    try:
        if pd.isna(value):
            return ""
        return "color:#2DD4A0" if value > 0 else ("color:#FF5C7A" if value < 0 else "")
    except Exception:
        return ""


def style_map(styler, func, subset):
    """Works on both old (applymap) and new (map) pandas."""
    fn = getattr(styler, "map", None) or styler.applymap
    return fn(func, subset=subset)