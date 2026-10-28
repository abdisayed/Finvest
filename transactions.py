import streamlit as st
import pandas as pd
from db import run_query

from theme import page_header, section, note, currency_toggle
from market_utils import (
    BUY_TYPES, SELL_TYPES, convert, cur_symbol, ensure_stock,
    get_fx_rate, get_last_price, stock_currency,
)


def _held_quantity(user_id, portfolio_id, stock_id):
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


def _type_color(value):
    if str(value).upper() in BUY_TYPES:
        return "color:#2DD4A0;font-weight:600"
    if str(value).upper() in SELL_TYPES:
        return "color:#FF5C7A;font-weight:600"
    return ""


def show_transactions():
    page_header("🧾", "Transactions", "Record your buys and sells and review your trade history.")

    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("Please log in first.")
        return

    flash = st.session_state.pop("tx_flash", None)
    if flash:
        st.success(flash)

    currency = currency_toggle("transactions_currency")
    prefix = cur_symbol(currency)

    try:
        fx_rate = get_fx_rate()
    except Exception as e:
        st.error(f"Cannot load USD/INR rate: {e}")
        return

    try:
        portfolios = run_query(
            "SELECT portfolio_id, portfolio_name FROM portfolios WHERE user_id=%s ORDER BY portfolio_id",
            (user_id,), fetchall=True,
        ) or []
        stocks = run_query(
            "SELECT stock_id, symbol, company_name FROM stocks ORDER BY symbol",
            fetchall=True,
        ) or []
    except Exception as e:
        st.error(f"Could not load portfolios/stocks: {e}")
        return

    if not portfolios:
        st.info("Create a portfolio on the Portfolio Overview page before recording transactions.")
        return

    portfolio_map = {p["portfolio_name"]: p["portfolio_id"] for p in portfolios}
    chosen = st.selectbox(
        "Portfolio", list(portfolio_map.keys()), index=None,
        placeholder="Choose a portfolio", key="tx_portfolio",
    )
    if not chosen:
        st.info("Select a portfolio to add or view transactions.")
        return
    portfolio_id = portfolio_map[chosen]

    # ---------------- add transaction ----------------
    with st.expander("➕ Add transaction", expanded=False):
        stock_map = {f'{s["symbol"]} | {s.get("company_name") or ""}': s for s in stocks}

        a, b = st.columns([3, 2])
        label = a.selectbox(
            "Stock from your list", list(stock_map.keys()), index=None,
            placeholder="Choose a stock", key="tx_stock",
        )
        new_ticker = b.text_input(
            "Or enter any new ticker", key="tx_new_ticker",
            placeholder="NVDA, TCS.NS ...",
        ).strip().upper()

        symbol = new_ticker or (str(stock_map[label]["symbol"]).upper() if label else "")

        d1, d2, d3 = st.columns(3)
        trade_type = d1.radio("Type", ["BUY", "SELL"], horizontal=True, key="tx_type")
        quantity = d2.number_input("Quantity", min_value=0.0001, value=1.0, step=1.0, key="tx_qty")

        default_price = 100.0
        if symbol:
            try:
                last = get_last_price(symbol)
                if last:
                    default_price = round(convert(last, stock_currency(symbol), currency, fx_rate), 2)
            except Exception:
                pass
        entered_price = d3.number_input(
            f"Price per share ({currency})", min_value=0.01, value=float(max(default_price, 0.01)),
            step=1.0, key=f"tx_price_{symbol}_{currency}",
        )
        if symbol:
            note(f"Prefilled with the latest market price for {symbol}. Edit it if your trade price was different.")

        if st.button("Save transaction", type="primary", use_container_width=True, key="tx_save"):
            if not symbol:
                st.warning("Choose a stock or enter a ticker.")
            else:
                try:
                    if new_ticker:
                        stock_id = ensure_stock(new_ticker)
                    else:
                        stock_id = stock_map[label]["stock_id"]

                    if trade_type == "SELL":
                        held = _held_quantity(user_id, portfolio_id, stock_id)
                        if quantity > held + 1e-9:
                            st.error(f"You can't sell {quantity:g}. You only hold {held:g} of {symbol} in this portfolio.")
                            st.stop()

                    native_price = convert(entered_price, currency, stock_currency(symbol), fx_rate)
                    run_query(
                        """
                        INSERT INTO transactions
                        (user_id, portfolio_id, stock_id, transaction_type, quantity, price, transaction_date)
                        VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (user_id, portfolio_id, stock_id, trade_type, quantity, native_price),
                    )
                    st.session_state["tx_flash"] = (
                        f"Saved {trade_type} {quantity:g} {symbol} at {prefix}{entered_price:,.2f} per share."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not save transaction: {e}")

    # ---------------- history ----------------
    try:
        rows = run_query(
            """
            SELECT t.transaction_type, t.quantity, t.price, t.transaction_date,
                   s.symbol, s.company_name
            FROM transactions t
            JOIN stocks s ON s.stock_id=t.stock_id
            WHERE t.user_id=%s AND t.portfolio_id=%s
            ORDER BY t.transaction_date DESC
            """,
            (user_id, portfolio_id), fetchall=True,
        ) or []
    except Exception as e:
        st.error(f"Could not load transaction history: {e}")
        return

    if not rows:
        st.info("No transactions recorded for this portfolio yet.")
        return

    df = pd.DataFrame(rows)
    df["Quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    native = pd.to_numeric(df["price"], errors="coerce").fillna(0)
    df["Symbol"] = df["symbol"].astype(str).str.upper()
    src = df["Symbol"].apply(stock_currency)
    df["Price"] = [convert(p, s, currency, fx_rate) for p, s in zip(native, src)]
    df["Total"] = df["Price"] * df["Quantity"]
    df["Date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df["Type"] = df["transaction_type"].astype(str).str.upper()
    df["Company"] = df["company_name"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Transactions", len(df))
    c2.metric("Buy value", f'{prefix}{df.loc[df["Type"].isin(BUY_TYPES), "Total"].sum():,.2f}')
    c3.metric("Sell value", f'{prefix}{df.loc[df["Type"].isin(SELL_TYPES), "Total"].sum():,.2f}')

    section("Trade history")
    f1, f2 = st.columns([3, 1])
    search = f1.text_input("Search ticker or company", key="tx_search")
    only = f2.selectbox("Show", ["All", "BUY", "SELL"], key="tx_filter")

    view = df
    if search.strip():
        view = view[
            view["Symbol"].str.contains(search, case=False, na=False)
            | view["Company"].astype(str).str.contains(search, case=False, na=False)
        ]
    if only != "All":
        view = view[view["Type"].isin(BUY_TYPES if only == "BUY" else SELL_TYPES)]

    view = view[["Date", "Symbol", "Company", "Type", "Quantity", "Price", "Total"]]
    styled = view.style.format({
        "Quantity": "{:,.4f}",
        "Price": lambda x: f"{prefix}{x:,.2f}",
        "Total": lambda x: f"{prefix}{x:,.2f}",
    })
    fn = getattr(styled, "map", None) or styled.applymap
    styled = fn(_type_color, subset=["Type"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    note("Prices are stored in each stock's own currency (₹ for .NS/.BO, $ otherwise) "
         "and shown here converted at the current USD/INR rate.")


def render_transactions():
    show_transactions()
