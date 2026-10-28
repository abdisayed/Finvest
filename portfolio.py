import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from db import run_query

from theme import page_header, section, note, currency_toggle, pnl_color, style_map
from market_utils import (
    BUY_TYPES, SELL_TYPES, convert, cur_symbol, get_fx_rate,
    get_last_price, stock_currency,
)


def _create_portfolio(user_id):
    with st.expander("➕ Create new portfolio", expanded=False):
        name = st.text_input("Portfolio name", key="new_portfolio_name",
                             placeholder="e.g. Long-term, Growth, Dividend")
        if st.button("Create portfolio", key="create_portfolio_btn"):
            if not name.strip():
                st.warning("Enter a portfolio name.")
                return
            try:
                run_query(
                    "INSERT INTO portfolios (user_id, portfolio_name) VALUES (%s, %s)",
                    (user_id, name.strip()),
                )
                st.success(f"Portfolio '{name.strip()}' created.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not create portfolio: {e}")


def _build_holdings(rows, currency, fx_rate):
    """Average-cost method. Returns (holdings dict, realized P&L in display currency)."""
    holdings, realized = {}, 0.0

    for t in rows:
        symbol = str(t["symbol"]).upper()
        kind = str(t["transaction_type"]).upper()
        qty = float(t["quantity"] or 0)
        price = float(t["price"] or 0)

        item = holdings.setdefault(symbol, {
            "company": t.get("company_name") or symbol,
            "sector": t.get("sector") or "Unknown",
            "quantity": 0.0, "cost": 0.0,
        })

        if kind in BUY_TYPES:
            item["quantity"] += qty
            item["cost"] += qty * price
        elif kind in SELL_TYPES and item["quantity"] > 0:
            avg = item["cost"] / item["quantity"]
            sold = min(qty, item["quantity"])
            item["cost"] -= avg * sold
            item["quantity"] -= sold
            realized += convert((price - avg) * sold, stock_currency(symbol), currency, fx_rate)

    return holdings, realized


def show_portfolio():
    page_header("💼", "Portfolio Overview",
                "Your holdings, cost basis, profit or loss and concentration risk.")

    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("Please log in first.")
        return

    currency = currency_toggle("portfolio_currency")
    prefix = cur_symbol(currency)

    try:
        fx_rate = get_fx_rate()
    except Exception as e:
        st.error(f"Cannot load USD/INR exchange rate: {e}")
        return

    try:
        portfolios = run_query(
            "SELECT portfolio_id, portfolio_name FROM portfolios WHERE user_id=%s ORDER BY portfolio_id",
            (user_id,), fetchall=True,
        ) or []
    except Exception as e:
        st.error(f"Could not load portfolios: {e}")
        return

    if not portfolios:
        st.info("You have no portfolio yet. Create one to start tracking.")
        _create_portfolio(user_id)
        return

    portfolio_map = {p["portfolio_name"]: p["portfolio_id"] for p in portfolios}
    chosen = st.selectbox(
        "Portfolio", list(portfolio_map.keys()), index=None,
        placeholder="Choose a portfolio to view",
        key="portfolio_choice",
    )
    _create_portfolio(user_id)

    if not chosen:
        st.info("Select a portfolio above to see your holdings.")
        return

    portfolio_id = portfolio_map[chosen]

    try:
        rows = run_query(
            """
            SELECT s.symbol, s.company_name, s.sector,
                   t.transaction_type, t.quantity, t.price, t.transaction_date
            FROM transactions t
            JOIN stocks s ON s.stock_id=t.stock_id
            WHERE t.user_id=%s AND t.portfolio_id=%s
            ORDER BY t.transaction_date ASC
            """,
            (user_id, portfolio_id), fetchall=True,
        ) or []
    except Exception as e:
        st.error(f"Could not load portfolio: {e}")
        return

    if not rows:
        st.info("No transactions in this portfolio yet. Add a buy on the Transactions page.")
        return

    holdings, realized = _build_holdings(rows, currency, fx_rate)

    output = []
    with st.spinner("Fetching latest prices..."):
        for symbol, item in holdings.items():
            qty = item["quantity"]
            if qty <= 1e-9:
                continue

            source = stock_currency(symbol)
            avg_native = item["cost"] / qty
            purchase = convert(avg_native, source, currency, fx_rate)

            try:
                current_native = get_last_price(symbol)
            except Exception:
                current_native = None

            if current_native is None:
                current = value = pnl = pnl_pct = None
            else:
                current = convert(current_native, source, currency, fx_rate)
                value = qty * current
                pnl = value - qty * purchase
                pnl_pct = (current_native / avg_native - 1) * 100 if avg_native else 0.0

            output.append({
                "Stock": symbol, "Company": item["company"], "Sector": item["sector"],
                "Quantity": qty, "Purchase Price": purchase, "Current Price": current,
                "Invested": qty * purchase, "Market Value": value, "P&L": pnl, "P&L %": pnl_pct,
            })

    if not output:
        st.info("No open positions in this portfolio (everything has been sold).")
        st.metric("Realized P&L", f"{prefix}{realized:,.2f}")
        return

    df = pd.DataFrame(output)
    priced = df.dropna(subset=["Market Value"])
    total_value = priced["Market Value"].sum()
    total_invested = priced["Invested"].sum()
    total_pnl = priced["P&L"].sum()
    pnl_pct_total = (total_pnl / total_invested * 100) if total_invested else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Market value", f"{prefix}{total_value:,.2f}")
    c2.metric("Invested", f"{prefix}{total_invested:,.2f}")
    c3.metric("Unrealized P&L", f"{prefix}{total_pnl:,.2f}", f"{pnl_pct_total:+.2f}%")
    c4.metric("Realized P&L", f"{prefix}{realized:,.2f}")

    # ---------------- risk panel ----------------
    section("🛡️ Risk check")
    if total_value > 0:
        weights = (priced["Market Value"] / total_value).values
        top_idx = int(weights.argmax())
        top_weight = float(weights[top_idx]) * 100
        effective = 1 / float((weights ** 2).sum())
        sectors = priced["Sector"].nunique()

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Open holdings", len(df))
        r2.metric("Biggest position", f"{priced.iloc[top_idx]['Stock']}", f"{top_weight:.1f}% of portfolio", delta_color="off")
        r3.metric("Effective diversification", f"{effective:.1f} stocks")
        r4.metric("Sectors", sectors)

        if top_weight > 40:
            st.warning(f"High concentration: {priced.iloc[top_idx]['Stock']} is {top_weight:.0f}% of your portfolio. "
                       "A fall in this one stock would hit your portfolio hard.")
        elif top_weight > 25:
            st.info("Moderate concentration. Consider whether you are comfortable with your largest position.")
        else:
            st.success("Your money is reasonably spread across holdings.")
        if len(df) < 5:
            note("Holding fewer than 5 stocks usually means higher risk from a single company.")

    # ---------------- holdings table ----------------
    section("📊 Your holdings")
    display = df.drop(columns=["Invested"])
    styled = display.style.format({
        "Quantity": "{:,.4f}",
        "Current Price": lambda x: "N/A" if pd.isna(x) else f"{prefix}{x:,.2f}",
        "Purchase Price": lambda x: f"{prefix}{x:,.2f}",
        "Market Value": lambda x: "N/A" if pd.isna(x) else f"{prefix}{x:,.2f}",
        "P&L": lambda x: "N/A" if pd.isna(x) else f"{prefix}{x:,.2f}",
        "P&L %": lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}%",
    })
    styled = style_map(styled, pnl_color, ["P&L", "P&L %"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ---------------- charts ----------------
    if not priced.empty and total_value > 0:
        left, right = st.columns(2)
        with left:
            section("🧩 Allocation")
            fig = px.pie(priced, values="Market Value", names="Stock", hole=0.6)
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                              height=360, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with right:
            section("📈 Profit / loss by stock")
            fig = go.Figure(go.Bar(
                x=priced["Stock"], y=priced["P&L"],
                marker_color=["#2DD4A0" if v >= 0 else "#FF5C7A" for v in priced["P&L"]],
            ))
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)", height=360,
                              yaxis_title=f"P&L ({currency})", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    note(f"Values shown in {currency}. Exchange rate: 1 USD = ₹{fx_rate:,.2f}. "
         "Cost basis uses the average-cost method. Market prices may be delayed.")


def render_portfolio():
    show_portfolio()
