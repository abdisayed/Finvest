import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

from db import run_query
from theme import page_header, section, note
from market_utils import (
    add_to_watchlist, convert, cur_symbol, fmt_big, get_fx_rate, get_history,
    record_trade, result_label, search_symbols, stock_currency,
)
from ai_insight import generate_stock_ai_insight, render_insight

QUICK_PICKS = [
    ("Apple", "AAPL"), ("Microsoft", "MSFT"), ("Tesla", "TSLA"),
    ("Reliance", "RELIANCE.NS"), ("TCS", "TCS.NS"), ("Infosys", "INFY.NS"),
]
PERIODS = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y", "2Y": "2y", "5Y": "5y"}


@st.cache_data(ttl=300, show_spinner=False)
def load_quote(ticker):
    stock = yf.Ticker(ticker)
    history = stock.history(period="1y", auto_adjust=False)
    if history.empty:
        return None

    close = history["Close"].dropna()
    if close.empty:
        return None

    try:
        info = stock.info or {}
    except Exception:
        info = {}

    price = info.get("currentPrice") or info.get("regularMarketPrice") or float(close.iloc[-1])
    prev = (
        info.get("regularMarketPreviousClose")
        or info.get("previousClose")
        or (float(close.iloc[-2]) if len(close) >= 2 else price)
    )
    change = float(price) - float(prev)

    return {
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency") or stock_currency(ticker),
        "price": float(price),
        "change": change,
        "pct": (change / prev * 100) if prev else 0.0,
        "high": float(history["High"].max()),
        "low": float(history["Low"].min()),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "exchange": info.get("exchange"),
    }


def _set_query(value):
    st.session_state["market_query"] = value


def _price_chart(ticker, name, period, kind, symbol):
    hist = get_history(ticker, period, auto_adjust=False)
    if hist.empty:
        st.warning("No chart data for this period.")
        return

    fig = go.Figure()
    if kind == "Line":
        up = hist["Close"].iloc[-1] >= hist["Close"].iloc[0]
        color = "#2DD4A0" if up else "#FF5C7A"
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["Close"], mode="lines", name="Close",
            line=dict(width=2.4, color=color),
        ))
    else:
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist["Open"], high=hist["High"],
            low=hist["Low"], close=hist["Close"], name="OHLC",
            increasing_line_color="#2DD4A0", decreasing_line_color="#FF5C7A",
        ))

    fig.update_layout(
        template="plotly_dark", height=460,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title=f"Price ({symbol.strip()})", hovermode="x unified",
        xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=20, b=10),
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,.10)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,.10)")
    st.plotly_chart(fig, use_container_width=True)


def _trade_panel(user_id, ticker, quote):
    """Buy/Sell box: shares default to 1 and the total updates as you change it."""
    section("🛒 Buy or sell this stock")

    if not user_id:
        st.warning("Please log in first.")
        return

    code = quote["currency"]
    sym = cur_symbol(code)
    price = quote["price"]

    try:
        portfolios = run_query(
            "SELECT portfolio_id, portfolio_name FROM portfolios WHERE user_id=%s ORDER BY portfolio_id",
            (user_id,), fetchall=True,
        ) or []
    except Exception as e:
        st.error(f"Could not load portfolios: {e}")
        return

    if not portfolios:
        st.info("Create a portfolio on the Portfolio Overview page to start trading.")
        return

    pmap = {p["portfolio_name"]: p["portfolio_id"] for p in portfolios}

    c1, c2, c3 = st.columns([1.2, 1, 1.4])
    side = c1.radio("Action", ["BUY", "SELL"], horizontal=True, key=f"trade_side_{ticker}")
    qty = c2.number_input("Shares", min_value=1, value=1, step=1, key=f"trade_qty_{ticker}")
    chosen = c3.selectbox(
        "Portfolio", list(pmap.keys()), index=None,
        placeholder="Choose portfolio", key=f"trade_pf_{ticker}",
    )

    total = price * qty
    m1, m2, m3 = st.columns(3)
    m1.metric("Price per share", f"{sym}{price:,.2f}")
    m2.metric("Shares", f"{qty:,}")
    m3.metric(f"Total {'cost' if side == 'BUY' else 'proceeds'}", f"{sym}{total:,.2f}")

    fx = None
    try:
        fx = get_fx_rate()
        if code == "USD":
            note(f"About ₹{total * fx:,.2f} (1 USD = ₹{fx:,.2f})")
        elif code == "INR":
            note(f"About ${total / fx:,.2f} (1 USD = ₹{fx:,.2f})")
    except Exception:
        pass

    if st.button(f"Confirm {side}: {qty} × {ticker}", type="primary",
                 use_container_width=True, key=f"trade_go_{ticker}"):
        if not chosen:
            st.warning("Choose a portfolio first.")
            return
        try:
            native = stock_currency(ticker)
            if code == native:
                native_price = price
            elif fx is not None:
                native_price = convert(price, code, native, fx)
            else:
                raise ValueError("USD/INR rate unavailable, try again in a moment.")

            record_trade(user_id, pmap[chosen], ticker, quote["name"], side, float(qty), native_price)
            st.success(
                f"{side} saved: {qty} × {ticker} at {sym}{price:,.2f} "
                f"(total {sym}{total:,.2f}) in '{chosen}'. See it on the Transactions page."
            )
        except Exception as e:
            st.error(str(e))


def show_live_market():
    page_header("📈", "Live Market & AI",
                "Search any stock by company name or ticker, see its performance and get a simple AI verdict.")

    user_id = st.session_state.get("user_id")

    # Coming from the Watchlist page ("Analyze with AI")
    pending = st.session_state.pop("selected_market_ticker", None)
    st.session_state.pop("selected_market_company", None)
    if pending:
        st.session_state["market_query"] = pending

    query = st.text_input(
        "Search stock",
        key="market_query",
        placeholder="Type a company or ticker: Apple, Reliance, TCS, AAPL, RELIANCE.NS ...",
        help="Any company on Yahoo Finance. Indian stocks use .NS (NSE) or .BO (BSE).",
    ).strip()

    if not query:
        st.markdown("**Popular searches**")
        cols = st.columns(len(QUICK_PICKS))
        for col, (label, sym) in zip(cols, QUICK_PICKS):
            col.button(label, key=f"quick_{sym}", on_click=_set_query,
                       args=(sym,), use_container_width=True)
        st.info("Search for a stock above to see price, chart and AI verdict.")
        return

    with st.spinner("Searching..."):
        results = search_symbols(query)

    if not results:
        st.warning("No stock found. Try the full company name or an exact ticker like AAPL or TCS.NS.")
        return

    idx = st.selectbox(
        "Matching stocks", range(len(results)),
        format_func=lambda i: result_label(results[i]),
    )
    ticker = results[idx]["symbol"]

    with st.spinner(f"Loading {ticker}..."):
        quote = load_quote(ticker)

    if not quote:
        st.warning(f"No market data found for {ticker}.")
        return

    code = quote["currency"]
    symbol = cur_symbol(code)

    # ---- header + add to watchlist
    head_l, head_r = st.columns([4, 1.4])
    with head_l:
        st.subheader(f"{quote['name']} ({ticker})")
        bits = [b for b in (quote.get("sector"), quote.get("exchange")) if b]
        if bits:
            note(" · ".join(bits))
    with head_r:
        if st.button("⭐ Add to watchlist", key="lm_add_watch", use_container_width=True):
            if not user_id:
                st.warning("Please log in first.")
            else:
                status, msg = add_to_watchlist(user_id, ticker, quote["name"])
                (st.success if status == "added" else st.info if status == "exists" else st.error)(msg)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current price", f"{symbol}{quote['price']:,.2f}",
              f"{quote['change']:+,.2f} ({quote['pct']:+.2f}%)")
    c2.metric("52-week high", f"{symbol}{quote['high']:,.2f}")
    c3.metric("52-week low", f"{symbol}{quote['low']:,.2f}")
    c4.metric("Market cap", fmt_big(quote["market_cap"], code))

    # ---- chart
    section("Price chart")
    o1, o2 = st.columns([3, 2])
    period_label = o1.radio("Period", list(PERIODS), index=3, horizontal=True, key="lm_period")
    kind = o2.radio("Chart type", ["Line", "Candlestick"], horizontal=True, key="lm_kind")
    _price_chart(ticker, quote["name"], PERIODS[period_label], kind, symbol)

    # ---- AI insight
    section("🤖 AI insight: Buy, Hold or Sell?")
    store_key = f"insight_{ticker}"

    if st.button("✨ Generate AI report", type="primary", use_container_width=True, key="lm_ai"):
        with st.spinner("AI is analysing this stock..."):
            insight = generate_stock_ai_insight(
                company_name=quote["name"], ticker=ticker,
                curr_price=quote["price"], percent_change=quote["pct"],
            )
        if insight:
            st.session_state[store_key] = insight
        else:
            st.error("Not enough market data to analyse this stock. Try another ticker.")

    if st.session_state.get(store_key):
        render_insight(st.session_state[store_key])

    # ---- buy / sell
    _trade_panel(user_id, ticker, quote)

    note("Market data may be delayed. AI reports are informational only and not financial advice.")


# Backward-compatible aliases
def show_live_market_page():
    show_live_market()


def render_market():
    show_live_market()