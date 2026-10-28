import streamlit as st

from auth_view import render_auth
from theme import apply_theme

st.set_page_config(
    page_title="FinVest Trading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()

PAGES = [
    "Portfolio Overview",
    "Live Market & AI",
    "Watchlist",
    "Transactions",
    "AI Chat",
]
ICONS = {
    "Portfolio Overview": "💼",
    "Live Market & AI": "📈",
    "Watchlist": "⭐",
    "Transactions": "🧾",
    "AI Chat": "🤖",
}

# ---------- SESSION DEFAULTS ----------
st.session_state.setdefault("authenticated", False)
st.session_state.setdefault("nav_page", "Portfolio Overview")

# ---------- AUTHENTICATION ----------
if not st.session_state["authenticated"]:
    render_auth()
    st.stop()

# Page jumps requested by other pages (e.g. Watchlist -> Live Market & AI).
# Must be applied BEFORE the navigation radio is created.
goto = st.session_state.pop("goto_page", None)
if goto in PAGES:
    st.session_state["nav_page"] = goto

# ---------- SIDEBAR ----------
with st.sidebar:
    st.markdown("# 📈 FinVest")
    st.caption(f"Welcome, {st.session_state.get('user_name', 'Investor')}")
    st.divider()

    selected_page = st.radio(
        "Navigation",
        PAGES,
        key="nav_page",
        format_func=lambda p: f"{ICONS[p]}  {p}",
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ---------- PAGE ROUTING ----------
try:
    if selected_page == "Portfolio Overview":
        from portfolio import show_portfolio
        show_portfolio()

    elif selected_page == "Live Market & AI":
        from live_market import show_live_market
        show_live_market()

    elif selected_page == "Watchlist":
        from watchlist import show_watchlist
        show_watchlist()

    elif selected_page == "Transactions":
        from transactions import show_transactions
        show_transactions()

    elif selected_page == "AI Chat":
        from ai_chat import show_ai_chat
        show_ai_chat()

except ImportError as e:
    st.error("A page module or function could not be imported.")
    st.code(str(e))
    st.info("Check that the Python file exists and all packages in requirements.txt are installed.")

except Exception as e:
    st.error("Something went wrong while loading this page.")
    st.code(str(e))
