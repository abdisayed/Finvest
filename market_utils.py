"""Shared helpers: currency, Yahoo Finance search, stock + watchlist DB helpers."""
import streamlit as st
import yfinance as yf
from db import run_query

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€", "JPY": "¥"}
BUY_TYPES = ("BUY", "PURCHASE")
SELL_TYPES = ("SELL", "SALE")


def cur_symbol(code):
    return CURRENCY_SYMBOLS.get(code, f"{code} ")


def stock_currency(symbol):
    return "INR" if str(symbol).upper().endswith((".NS", ".BO")) else "USD"


def convert(value, source, target, rate):
    value = float(value)
    if source == target:
        return value
    if source == "USD" and target == "INR":
        return value * rate
    if source == "INR" and target == "USD":
        return value / rate
    return value


def fmt_big(n, code="USD"):
    """Readable market cap: 1.2T, 340.5B, 12.3M ..."""
    if not n:
        return "N/A"
    sym = cur_symbol(code)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(n) >= div:
            return f"{sym}{n / div:,.2f}{unit}"
    return f"{sym}{n:,.0f}"


@st.cache_data(ttl=300, show_spinner=False)
def get_fx_rate():
    hist = yf.Ticker("USDINR=X").history(period="5d")
    if hist.empty:
        raise ValueError("USD/INR rate unavailable.")
    return float(hist["Close"].dropna().iloc[-1])


@st.cache_data(ttl=300, show_spinner=False)
def get_history(symbol, period="1y", auto_adjust=True):
    return yf.Ticker(symbol).history(period=period, auto_adjust=auto_adjust)


@st.cache_data(ttl=300, show_spinner=False)
def get_last_price(symbol):
    hist = yf.Ticker(symbol).history(period="5d")
    if hist.empty:
        return None
    close = hist["Close"].dropna()
    return float(close.iloc[-1]) if not close.empty else None


@st.cache_data(ttl=600, show_spinner=False)
def search_symbols(query, limit=8):
    """Search Yahoo Finance by company name OR ticker. Returns list of dicts."""
    q = (query or "").strip()
    if not q:
        return []

    results, seen = [], set()
    try:
        search = yf.Search(q, max_results=limit)
        for item in (getattr(search, "quotes", None) or []):
            sym = item.get("symbol")
            if not sym or sym in seen:
                continue
            if item.get("quoteType") not in ("EQUITY", "ETF", None):
                continue
            seen.add(sym)
            results.append({
                "symbol": sym,
                "name": item.get("longname") or item.get("shortname") or sym,
                "exchange": item.get("exchDisp") or item.get("exchange") or "",
            })
    except Exception:
        pass

    # Exact ticker typed by the user (works even if search misses it)
    direct = q.upper().replace(" ", "")
    if " " not in q:
        if direct in seen:
            results.sort(key=lambda r: r["symbol"] != direct)
        else:
            try:
                if not yf.Ticker(direct).history(period="5d").empty:
                    results.append({"symbol": direct, "name": direct, "exchange": ""})
            except Exception:
                pass
    return results


def result_label(r):
    extra = f" ({r['exchange']})" if r.get("exchange") else ""
    return f"{r['symbol']} — {r['name']}{extra}"


def ensure_stock(symbol, company=None):
    """Return stock_id, inserting the stock into `stocks` if needed."""
    symbol = str(symbol).strip().upper()
    row = run_query(
        "SELECT stock_id FROM stocks WHERE UPPER(symbol)=%s LIMIT 1",
        (symbol,), fetchone=True,
    )
    if row:
        return row["stock_id"]

    if get_history(symbol, "5d").empty:
        raise ValueError(f"Ticker {symbol} was not found on Yahoo Finance.")

    sector = None
    try:
        info = yf.Ticker(symbol).info or {}
        company = company if company and company != symbol else (
            info.get("longName") or info.get("shortName") or company
        )
        sector = info.get("sector")
    except Exception:
        pass

    run_query(
        "INSERT INTO stocks (symbol, company_name, sector) VALUES (%s, %s, %s)",
        (symbol, company or symbol, sector),
    )
    row = run_query(
        "SELECT stock_id FROM stocks WHERE UPPER(symbol)=%s ORDER BY stock_id DESC LIMIT 1",
        (symbol,), fetchone=True,
    )
    return row["stock_id"]


def add_to_watchlist(user_id, symbol, company=None):
    """Returns (status, message) where status is 'added', 'exists' or 'error'."""
    symbol = str(symbol).strip().upper()
    try:
        stock_id = ensure_stock(symbol, company)
        existing = run_query(
            "SELECT watchlist_id FROM watchlist WHERE user_id=%s AND stock_id=%s LIMIT 1",
            (user_id, stock_id), fetchone=True,
        )
        if existing:
            return "exists", f"{symbol} is already in your watchlist."
        run_query(
            "INSERT INTO watchlist (user_id, stock_id, stock_ticker) VALUES (%s, %s, %s)",
            (user_id, stock_id, symbol),
        )
        return "added", f"{symbol} added to your watchlist."
    except Exception as e:
        return "error", f"Could not add {symbol}: {e}"


def held_quantity(user_id, portfolio_id, stock_id):
    row = run_query(
        """
        SELECT COALESCE(SUM(CASE WHEN UPPER(transaction_type) IN ('BUY','PURCHASE')
                                 THEN quantity ELSE -quantity END), 0) AS held
        FROM transactions
        WHERE user_id=%s AND portfolio_id=%s AND stock_id=%s
        """,
        (user_id, portfolio_id, stock_id), fetchone=True,
    )
    return float(row["held"] or 0) if row else 0.0


def record_trade(user_id, portfolio_id, symbol, company, trade_type, quantity, native_price):
    """Save a BUY/SELL. Raises ValueError if you try to sell more than you hold."""
    stock_id = ensure_stock(symbol, company)
    if trade_type == "SELL":
        held = held_quantity(user_id, portfolio_id, stock_id)
        if quantity > held + 1e-9:
            raise ValueError(
                f"You can't sell {quantity:g}. You hold {held:g} shares of {symbol} in this portfolio."
            )
    run_query(
        """
        INSERT INTO transactions
        (user_id, portfolio_id, stock_id, transaction_type, quantity, price, transaction_date)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """,
        (user_id, portfolio_id, stock_id, trade_type, quantity, native_price),
    )