import streamlit as st
import plotly.graph_objects as go
from db import run_query

from theme import page_header, section, note, currency_toggle
from market_utils import (
    add_to_watchlist, convert, cur_symbol, get_fx_rate, get_history,
    result_label, search_symbols, stock_currency,
)

PERIODS = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y", "2Y": "2y"}


def show_watchlist():
    page_header("⭐", "My Watchlist", "Pick one of your saved stocks to see its chart and price.")

    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("Please log in first.")
        return

    flash = st.session_state.pop("wl_flash", None)
    if flash:
        st.success(flash)

    currency = currency_toggle("watchlist_currency")
    prefix = cur_symbol(currency)

    try:
        fx_rate = get_fx_rate()
    except Exception as e:
        st.error(f"Cannot load the USD/INR rate: {e}")
        return

    # ---------------- add stock ----------------
    with st.expander("➕ Add stock to watchlist", expanded=False):
        q = st.text_input(
            "Search by company name or ticker", key="wl_search",
            placeholder="Apple, Reliance, TCS, NVDA, INFY.NS ...",
        ).strip()
        if q:
            results = search_symbols(q)
            if not results:
                st.warning("No stock found. Try another name or an exact ticker.")
            else:
                idx = st.selectbox(
                    "Select stock", range(len(results)),
                    format_func=lambda i: result_label(results[i]), key="wl_pick",
                )
                if st.button("Add to watchlist", type="primary", key="wl_add"):
                    pick = results[idx]
                    status, msg = add_to_watchlist(user_id, pick["symbol"], pick["name"])
                    if status == "added":
                        st.session_state["wl_flash"] = msg
                        st.rerun()
                    elif status == "exists":
                        st.info(msg)
                    else:
                        st.error(msg)

    # ---------------- load watchlist ----------------
    try:
        rows = run_query(
            """
            SELECT w.watchlist_id, w.stock_id,
                   COALESCE(w.stock_ticker, s.symbol) AS symbol,
                   s.company_name, s.sector
            FROM watchlist w
            JOIN stocks s ON s.stock_id = w.stock_id
            WHERE w.user_id = %s
            ORDER BY w.watchlist_id DESC
            """,
            (user_id,), fetchall=True,
        ) or []
    except Exception as e:
        st.error(f"Could not load watchlist: {e}")
        return

    if not rows:
        st.info("Your watchlist is empty. Add a stock above to get started.")
        return

    by_symbol = {str(r["symbol"]).upper(): r for r in rows}
    symbols = list(by_symbol.keys())

    chosen = st.selectbox(
        f"Choose a stock ({len(symbols)} saved)", symbols, index=None,
        placeholder="Select a stock from your watchlist",
        format_func=lambda s: f"{s} — {by_symbol[s].get('company_name') or s}",
        key="wl_choice",
    )
    if not chosen:
        st.info("Select a stock to see its chart.")
        return

    row = by_symbol[chosen]
    company = row.get("company_name") or chosen
    source = stock_currency(chosen)

    try:
        hist = get_history(chosen, "1y")
        close = hist["Close"].dropna()
        if close.empty:
            st.warning(f"No price data available for {chosen}.")
            return
    except Exception as e:
        st.warning(f"Could not load {chosen}: {e}")
        return

    current = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) > 1 else current
    change_pct = (current / previous - 1) * 100 if previous else 0.0
    to_disp = lambda v: convert(v, source, currency, fx_rate)

    # ---------------- header ----------------
    left, right = st.columns([4, 2])
    with left:
        st.subheader(f"{company} ({chosen})")
        note(f"Sector: {row.get('sector') or 'Not specified'}")
    with right:
        b1, b2 = st.columns(2)
        if b1.button("🤖 Analyze", key="wl_ai", use_container_width=True,
                     help="Open Live Market & AI for this stock"):
            st.session_state["selected_market_ticker"] = chosen
            st.session_state["selected_market_company"] = company
            st.session_state["goto_page"] = "Live Market & AI"
            st.rerun()
        if b2.button("🗑️ Remove", key="wl_remove", use_container_width=True):
            run_query(
                "DELETE FROM watchlist WHERE watchlist_id=%s AND user_id=%s",
                (row["watchlist_id"], user_id),
            )
            st.session_state["wl_flash"] = f"{chosen} removed from watchlist."
            st.rerun()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Latest price", f"{prefix}{to_disp(current):,.2f}", f"{change_pct:+.2f}%")
    m2.metric("1Y high", f"{prefix}{to_disp(close.max()):,.2f}")
    m3.metric("1Y low", f"{prefix}{to_disp(close.min()):,.2f}")
    m4.metric("1Y return", f"{(current / float(close.iloc[0]) - 1) * 100:+.1f}%")

    # ---------------- chart ----------------
    section("Price chart")
    label = st.radio("Period", list(PERIODS), index=2, horizontal=True, key="wl_period")
    chart = get_history(chosen, PERIODS[label])
    if chart.empty:
        st.info("Chart data unavailable for this period.")
        return

    chart = chart.copy()
    factor = convert(1.0, source, currency, fx_rate)
    for col in ["Open", "High", "Low", "Close"]:
        chart[col] = chart[col] * factor

    line_tab, candle_tab = st.tabs(["📈 Line", "🕯️ Candlestick"])
    layout = dict(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title=f"Price ({currency})", hovermode="x unified",
        xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=20, b=10),
    )

    with line_tab:
        up = chart["Close"].iloc[-1] >= chart["Close"].iloc[0]
        fig = go.Figure(go.Scatter(
            x=chart.index, y=chart["Close"], mode="lines", name=chosen,
            line=dict(width=2.4, color="#2DD4A0" if up else "#FF5C7A"),
        ))
        fig.update_layout(height=400, **layout)
        st.plotly_chart(fig, use_container_width=True, key="wl_line")

    with candle_tab:
        fig = go.Figure(go.Candlestick(
            x=chart.index, open=chart["Open"], high=chart["High"],
            low=chart["Low"], close=chart["Close"], name=chosen,
            increasing_line_color="#2DD4A0", decreasing_line_color="#FF5C7A",
        ))
        fig.update_layout(height=430, **layout)
        st.plotly_chart(fig, use_container_width=True, key="wl_candle")

    note("Prices converted to your selected currency at the current USD/INR rate. Data may be delayed.")


def render_watchlist():
    show_watchlist()
