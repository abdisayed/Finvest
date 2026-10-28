import re
import threading
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
import yfinance as yf

try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except Exception:  # older/newer Streamlit layouts
    add_script_run_ctx = get_script_run_ctx = None
from db import run_query

from theme import page_header, note
from ai_insight import gemini_text, get_stock_snapshot, rule_based_signal
from market_utils import search_symbols

STOP_WORDS = {
    "AI", "ETF", "SIP", "IPO", "USD", "INR", "PE", "EPS", "BUY", "SELL", "HOLD", "RSI",
    "SMA", "FD", "MF", "GDP", "RBI", "US", "IT", "NSE", "BSE", "FII", "DII", "ROE",
    "ROI", "CEO", "FAQ", "OK", "I", "A", "KYA", "HAI", "HO", "AUR", "MEIN", "MAI",
}
RECO_WORDS = (
    "buy", "sell", "kharid", "bech", "invest", "recommend", "suggest", "konsa", "kaun",
    "which", "best", "predict", "hold", "avoid", "should", "lena", "lu", "portfolio",
    "future", "target", "outlook", "safe", "risk",
)
PICK_WORDS = ("buy", "sell", "kharid", "bech", "recommend", "suggest", "konsa", "kaun", "which", "best",
              "predict", "should", "lena", "idea", "top ", "invest in")
STRICT_PICK = ("which", "konsa", "kaun", "best", "suggest", "recommend", "buy", "kharid", "stocks to", "invest in")
EDU_WORDS = ("explain", "what is", "what are", "meaning", "define", "kya hota", "kya hai", "samjhao",
             "samjha", "difference between", "how does", "how do")

SUGGESTIONS = [
    "Which stocks in my portfolio should I keep or sell?",
    "Mere watchlist mein se konsa stock abhi kharidna chahiye?",
    "Reliance ka future outlook kya hai? Risk bhi batao.",
    "Explain diversification in simple words.",
]


def _set_pending(text):
    st.session_state["chat_pending"] = text


def _user_context(user_id):
    """Holdings + watchlist for this user."""
    holdings, watch = [], []
    try:
        holdings = run_query(
            """
            SELECT s.symbol, s.company_name,
              SUM(CASE WHEN UPPER(t.transaction_type) IN ('BUY','PURCHASE') THEN t.quantity ELSE -t.quantity END) AS net_qty,
              SUM(CASE WHEN UPPER(t.transaction_type) IN ('BUY','PURCHASE') THEN t.quantity*t.price ELSE 0 END)
                / NULLIF(SUM(CASE WHEN UPPER(t.transaction_type) IN ('BUY','PURCHASE') THEN t.quantity ELSE 0 END), 0) AS avg_buy
            FROM transactions t JOIN stocks s ON s.stock_id = t.stock_id
            WHERE t.user_id = %s
            GROUP BY s.symbol, s.company_name
            HAVING net_qty > 0
            """,
            (user_id,), fetchall=True,
        ) or []
    except Exception:
        pass
    try:
        watch = run_query(
            """
            SELECT COALESCE(w.stock_ticker, s.symbol) AS symbol, s.company_name
            FROM watchlist w JOIN stocks s ON s.stock_id = w.stock_id
            WHERE w.user_id = %s
            """,
            (user_id,), fetchall=True,
        ) or []
    except Exception:
        pass
    return holdings, watch


def _detect_symbols(prompt, known):
    found, low = [], prompt.lower()
    for r in known:
        sym = str(r["symbol"]).upper()
        base = sym.split(".")[0].lower()
        name = re.sub(r"\b(limited|ltd|inc|corporation|corp|co|plc)\b\.?", "", (r.get("company_name") or "").lower()).strip()
        if re.search(rf"\b{re.escape(base)}\b", low) or (len(name) >= 4 and name in low):
            if sym not in found:
                found.append(sym)
    for tok in re.findall(r"\b[A-Z][A-Z0-9&\-]{1,14}(?:\.(?:NS|BO|[A-Z]))?\b", prompt):
        if tok in STOP_WORDS:
            continue
        if "." not in tok and len(tok) > 6:
            continue
        # Yahoo writes class shares with a hyphen: BRK.B -> BRK-B
        if re.fullmatch(r"[A-Z]{1,5}\.[A-Z]", tok):
            tok = tok.replace(".", "-")
        if tok not in found:
            found.append(tok)
    return found[:6]


def _snapshot_block(symbols, limit=3):
    blocks, used = [], []
    for sym, d in _fetch_many(symbols[:limit], True):
        if not d:
            continue
        sig = rule_based_signal(d)
        used.append(sym)
        blocks.append(
            f"{sym} ({d['name']}) | sector {d['sector']} | price {d['currency']} {d['price']:.2f} | "
            f"1D {d['day_change_pct']:+.2f}% | 1M {d['return_1m_pct']:+.1f}% | 6M {d['return_6m_pct']:+.1f}% | "
            f"1Y {d['return_1y_pct']:+.1f}% | volatility {d['volatility_pct'] or 0:.0f}% | "
            f"3-month typical move ±{(d['volatility_pct'] or 0) * 0.5:.0f}% | RSI {d['rsi14'] or 0:.0f} | "
            f"SMA20 {d['sma20']:.2f} | SMA50 {d['sma50'] or 0:.2f} | PE {d['pe_ratio']} | fwdPE {d['forward_pe']} | "
            f"P/B {d['price_to_book']} | div yield {d['dividend_yield']} | mcap {d['market_cap']} | "
            f"worst fall in past year {d['max_drawdown_1y_pct']:.0f}% | now {d['below_52w_high_pct']:.0f}% from 52w high | "
            f"rule-signal {sig['verdict']} "
            f"(+: {'; '.join(sig['positives'])} | -: {'; '.join(sig['concerns'])})"
        )
    return "\n".join(blocks), used


UNIVERSE_US = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "JPM", "JNJ", "XOM", "KO", "WMT"]
UNIVERSE_IN = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "ITC.NS",
               "LT.NS", "SUNPHARMA.NS", "BHARTIARTL.NS", "HINDUNILVR.NS"]

EXCLUDE_PHRASES = (
    "excluding", "exclude", "except my", "without my", "bina my", "without watchlist", "without taking",
    "not in my watchlist", "other than my", "outside my",
    "not bought", "haven't bought", "have not bought", "not buyed", "other stocks", "new stocks",
    "naye stock", "dusre stock", "watchlist ke bina", "watchlist ke bahar", "kharide nahi", "nahi kharide",
)
DISCOVERY_WORDS = (
    "which", "konsa", "kaun", "best", "suggest", "recommend", "ideas", "top ", "stocks", "shares",
    "new ", "other", "naye", "dusre", "predict", "diversif", "sector", "alternative", "idea",
)
# Only these mean "review what I already own". A plain "my portfolio" does not.
OWN_REVIEW = (
    "should i sell", "should i hold", "sell my", "review my", "analyze my", "analyse my",
    "my holdings", "mere holdings", "mere stocks mein se", "meri portfolio ka", "kya bechu", "kya sell karu",
)
STOCK_INTENT = ("buy", "sell", "about", "analy", "outlook", "kaisa", "stock", "share", "price",
                "invest", "hold", "batao", "detail", "future", "good", "risk", "kharid")


SECTOR_UNIVERSE = {
    "tech": {"US": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ORCL", "AMD"],
             "IN": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"]},
    "banks & finance": {"US": ["JPM", "BAC", "WFC", "GS", "V", "MA"],
                        "IN": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS", "BAJFINANCE.NS"]},
    "pharma & health": {"US": ["JNJ", "LLY", "PFE", "MRK", "ABBV"],
                        "IN": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS"]},
    "energy & power": {"US": ["XOM", "CVX", "COP"],
                       "IN": ["RELIANCE.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "COALINDIA.NS"]},
    "consumer": {"US": ["KO", "PEP", "WMT", "COST", "PG", "MCD", "AMZN"],
                 "IN": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "TITAN.NS", "ASIANPAINT.NS"]},
    "auto": {"US": ["TSLA", "F", "GM"],
             "IN": ["MARUTI.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS"]},
    "industrial & infra": {"US": ["CAT", "GE", "HON", "UPS"],
                           "IN": ["LT.NS", "ADANIPORTS.NS", "ULTRACEMCO.NS", "TATASTEEL.NS", "JSWSTEEL.NS"]},
    "telecom": {"US": ["T", "VZ", "TMUS"], "IN": ["BHARTIARTL.NS"]},
}
SECTOR_KEYWORDS = {
    "tech": ("tech", " it ", "software", "semiconductor", "chip", " ai "),
    "banks & finance": ("bank", "financ", "nbfc", "insurance"),
    "pharma & health": ("pharma", "health", "medicine", "drug", "biotech"),
    "energy & power": ("energy", " oil", "gas", "power", "coal", "renewable"),
    "consumer": ("fmcg", "consumer", "retail", "food", "beverage"),
    "auto": ("auto", " car", " ev ", "electric vehicle"),
    "industrial & infra": ("industrial", "infra", "steel", "cement", "metal", "defence"),
    "telecom": ("telecom", "5g"),
}
YAHOO_SCREENS = {
    "gainers": "day_gainers",
    "losers": "day_losers",
    "most active": "most_actives",
    "undervalued": "undervalued_large_caps",
    "small cap": "small_cap_gainers",
    "growth": "growth_technology_stocks",
}
MORE_WORDS = (
    "more", "next batch", "aur stocks", "aur dikhao", "different stocks", "something else", "kuch aur",
    "other than these", "something different", "different one", "dusre wale", "naye wale",
)


def _yahoo_screen(name):
    """Yahoo Finance ready-made screens (mostly US stocks). Returns [] if unavailable."""
    try:
        res = yf.screen(name)
        return [q["symbol"] for q in (res.get("quotes") or []) if q.get("symbol")]
    except Exception:
        return []


SECTOR_YAHOO = {
    "tech": ["Technology"],
    "banks & finance": ["Financial Services"],
    "pharma & health": ["Healthcare"],
    "energy & power": ["Energy", "Utilities"],
    "consumer": ["Consumer Defensive", "Consumer Cyclical"],
    "auto": ["Consumer Cyclical"],
    "industrial & infra": ["Industrials", "Basic Materials"],
    "telecom": ["Communication Services"],
}


@st.cache_data(ttl=900, show_spinner=False)
def _screen_market(region, sector_names):
    """One Yahoo screener call over a whole market (filtered on Yahoo's side). Raises on failure."""
    from yfinance import EquityQuery

    clauses = [EquityQuery("eq", ["region", region])]
    if region == "us":
        clauses.append(EquityQuery("is-in", ["exchange", "NMS", "NYQ"]))
        floor = 10e9          # US large caps (> $10B)
    else:
        clauses.append(EquityQuery("eq", ["exchange", "NSI"]))
        floor = 2e11          # India large/mid caps (> ₹200B)
    clauses.append(EquityQuery("gt", ["intradaymarketcap", floor]))
    if sector_names:
        clauses.append(EquityQuery("is-in", ["sector", *sector_names]))

    res = yf.screen(EquityQuery("and", clauses), sortField="intradaymarketcap", sortAsc=False, size=250)
    quotes = (res or {}).get("quotes") or []
    if not quotes:
        raise ValueError("empty screen")
    return quotes


def _prescore(q):
    """Cheap ranking from fields Yahoo already returns (no extra calls)."""
    score = 0
    price = q.get("regularMarketPrice")
    if price:
        if q.get("fiftyDayAverage") and price > q["fiftyDayAverage"]:
            score += 1
        if q.get("twoHundredDayAverage") and price > q["twoHundredDayAverage"]:
            score += 1
        if q.get("fiftyTwoWeekHigh") and price / q["fiftyTwoWeekHigh"] - 1 > -0.25:
            score += 1
    chg = q.get("fiftyTwoWeekChangePercent")
    if chg is not None and chg > 0:
        score += 1
    pe = q.get("trailingPE")
    if pe and 0 < pe < 35:
        score += 1
    eps = q.get("epsTrailingTwelveMonths")
    if eps and eps > 0:
        score += 1
    return score


def _market_wide(exclude, markets, sectors, offset):
    """Pull hundreds of large companies from Yahoo, rank them, return a few strong + a few weak ones."""
    regions = ["us" if m == "US" else "in" for m in markets]
    names = tuple(dict.fromkeys(n for s in sectors for n in SECTOR_YAHOO.get(s, [])))
    n_top, n_weak = (9, 3) if len(regions) == 1 else (5, 1)
    page = offset // 12

    picks, total = [], 0
    for r in regions:
        try:
            quotes = _screen_market(r, names)
        except Exception:
            continue
        quotes = [q for q in quotes if q.get("symbol") and q["symbol"] not in exclude]
        if len(quotes) < n_top + n_weak:
            continue
        total += len(quotes)
        ranked = sorted(quotes, key=lambda q: (-_prescore(q), -(q.get("marketCap") or 0)))
        p = page % max(1, len(ranked) // n_top)
        top = ranked[p * n_top:(p + 1) * n_top]
        weak = ranked[::-1][p * n_weak:(p + 1) * n_weak]
        picks += [q["symbol"] for q in top + weak]

    picks = list(dict.fromkeys(picks))
    if not picks:
        return [], ""
    where = " + ".join("US" if r == "us" else "India" for r in regions)
    what = ", ".join(sectors) if sectors else "all sectors"
    return picks, (
        f"Yahoo Finance's screener: {total} large companies ({where}; {what}), ranked by trend and "
        f"valuation, then the strongest and weakest analysed live"
    )


def _choose_candidates(low, exclude):
    """Pick which stocks to screen. Returns (symbols, human description)."""
    india = any(w in low for w in ("india", "indian", "nse", "bse", "nifty", "sensex", "₹", "rupee"))
    us = any(w in low for w in (" us ", "usa", "american", "nasdaq", "nyse", "global", "dollar", "s&p"))

    # 1) Yahoo's own live lists (gainers, most active, undervalued...) for US stocks
    if not (india and not us):
        for key, name in YAHOO_SCREENS.items():
            if key in low:
                syms = [s for s in _yahoo_screen(name) if s not in exclude][:12]
                if syms:
                    return syms, f"Yahoo Finance's '{key}' list (mostly US stocks)"

    # 2) Whole-market screen through Yahoo's screener, paged with "show me more"
    markets = ["IN"] if (india and not us) else (["US"] if (us and not india) else ["US", "IN"])
    sectors = [s for s, kws in SECTOR_KEYWORDS.items() if any(k in f" {low} " for k in kws)]
    named = bool(sectors)
    more = any(w in low for w in MORE_WORDS)
    offset = (st.session_state.get("screen_offset", 0) + 12) if more else 0
    st.session_state["screen_offset"] = offset

    wide, wide_source = _market_wide(exclude, markets, sectors if named else [], offset)
    if wide:
        return wide, wide_source

    # 3) Fallback if the screener is unavailable: curated sector lists
    sectors = sectors or list(SECTOR_UNIVERSE)

    lists = [SECTOR_UNIVERSE[s][m] for s in sectors for m in markets]
    pool, seen = [], set()
    for i in range(max(len(x) for x in lists)):
        for x in lists:
            if i < len(x) and x[i] not in seen and x[i] not in exclude:
                seen.add(x[i])
                pool.append(x[i])
    if not pool:
        return [], "no stocks"

    start = offset % len(pool)
    batch = (pool[start:] + pool[:start])[:12]

    label = ", ".join(sectors) if named else "all major sectors"
    return batch, f"a screen of {len(batch)} stocks ({label}; {'/'.join(markets)} markets)"


def _fetch_many(symbols, with_info):
    """Fetch several snapshots at the same time instead of one by one."""
    ctx = get_script_run_ctx() if get_script_run_ctx else None

    def one(sym):
        if ctx is not None and add_script_run_ctx:
            try:
                add_script_run_ctx(threading.current_thread(), ctx)
            except Exception:
                pass
        try:
            return sym, get_stock_snapshot(sym, with_info)
        except Exception:
            return sym, None

    if not symbols:
        return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, symbols))


def _screen_block(symbols):
    """Quick scan of all candidates, then full details (PE etc.) for only the top 6."""
    quick = [(s, d) for s, d in _fetch_many(symbols, False) if d]
    rows = [(s, d, rule_based_signal(d)) for s, d in quick]

    order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    # Best signal first, and within the same signal the best 6-month performer first
    rows.sort(key=lambda r: (order[r[2]["verdict"]], -r[1]["return_6m_pct"]))

    rich = {s: d for s, d in _fetch_many([r[0] for r in rows[:8]], True) if d}

    lines = [
        f"{sym} ({d['name']}) | {d['sector']} | {d['currency']} {d['price']:.2f} | "
        f"1M {d['return_1m_pct']:+.1f}% | 6M {d['return_6m_pct']:+.1f}% | 1Y {d['return_1y_pct']:+.1f}% | "
        f"vol {d['volatility_pct'] or 0:.0f}% | 3-month typical move ±{(d['volatility_pct'] or 0) * 0.5:.0f}% | "
        f"RSI {d['rsi14'] or 0:.0f} | PE {d['pe_ratio']} | mcap {d['market_cap']} | "
        f"worst fall in past year {d['max_drawdown_1y_pct']:.0f}% | "
        f"rule-signal {s['verdict']} ({s['risk_level']} risk)"
        for sym, d, s in [(r[0], rich.get(r[0], r[1]), r[2]) for r in rows]
    ]
    return "\n".join(lines), [r[0] for r in rows]


def _lookup_by_name(prompt):
    """Find a stock named in plain words (e.g. 'Tata Motors') even if it's not in the DB."""
    low = prompt.lower()
    if len(prompt) > 90 or not any(w in low for w in STOCK_INTENT):
        return None
    try:
        hits = search_symbols(prompt)
    except Exception:
        return None
    for hit in hits[:3]:
        words = [w for w in re.findall(r"[a-z]{4,}", hit["name"].lower())
                 if w not in ("limited", "corporation", "company", "holdings", "group")]
        if any(w in low for w in words) or hit["symbol"].split(".")[0].lower() in low:
            return hit["symbol"]
    return None


def get_ai_response(prompt, user_id, history=None):
    holdings, watch = _user_context(user_id)

    try:
        known = run_query("SELECT symbol, company_name FROM stocks", fetchall=True) or []
    except Exception:
        known = []

    low = prompt.lower()
    explicit = _detect_symbols(prompt, known)
    wants_reco = any(w in low for w in RECO_WORDS)
    own = list(dict.fromkeys(
        [str(h["symbol"]).upper() for h in holdings] + [str(w["symbol"]).upper() for w in watch]
    ))
    exclude_own = any(p in low for p in EXCLUDE_PHRASES)
    own_review = any(p in low for p in OWN_REVIEW) and not exclude_own
    broad = exclude_own or any(w in low for w in DISCOVERY_WORDS)

    symbols = list(explicit)

    # A company named in words (e.g. "Tata Motors") that isn't saved anywhere yet
    if not symbols and not broad and not own_review:
        found = _lookup_by_name(prompt)
        if found:
            symbols = [found]

    # Idea / recommendation questions with no stock named -> screen the wider market
    pick_intent = any(w in low for w in PICK_WORDS)
    educational = any(w in low for w in EDU_WORDS) and not any(w in low for w in STRICT_PICK)
    discovery_mode = (not symbols and not own_review and not educational
                      and (broad or pick_intent))

    candidate_block, used = "", []
    screen_source = "a limited screen of popular stocks"
    missing = []
    if discovery_mode:
        # Idea questions: screen popular stocks across sectors, not just the user's lists
        exclude = set(own) if exclude_own else set()
        candidates, screen_source = _choose_candidates(low, exclude)
        candidate_block, screened = _screen_block(candidates)
        used = screened[:5]
        market_block = ""
    else:
        if not symbols and own_review:
            symbols = own[:5]
        market_block, used = _snapshot_block(symbols, limit=6)
        missing = [s for s in symbols if s not in used]

    hold_txt = "\n".join(
        f'- {h["symbol"]} ({h.get("company_name") or ""}): qty {float(h["net_qty"]):g}, avg buy {float(h["avg_buy"] or 0):.2f} (native currency)'
        for h in holdings
    ) or "No open holdings."
    watch_txt = ", ".join(str(w["symbol"]) for w in watch) or "Watchlist is empty."

    convo = ""
    for m in (history or [])[-6:]:
        convo += f'{m["role"].upper()}: {m["content"][:600]}\n'

    full_prompt = f"""
You are FinVest AI, an investing research assistant for Indian and global stocks.

LANGUAGE: Reply in the same language/style as the user's latest message. If they write
English, reply in English. If they write Hindi/Hinglish, reply in natural Roman-script Hinglish.

HOW TO ANSWER
- If asked what to buy/avoid/sell: give a clear call per stock: 🟢 BUY / 🟡 HOLD / 🔴 AVOID (or SELL if owned),
  with confidence (Low/Medium/High), 2-3 simple reasons, the main risk, and what would change your view.
- Give a price outlook as scenarios (bullish / base / bearish) for the NEXT ~3 MONTHS and say that horizon.
  Anchor the ranges on the supplied "3-month typical move" (about 1 standard deviation): bearish is roughly
  -0.5 to -1x that move, bullish roughly +0.5 to +1x, adjusted a little for trend. Label them as rough estimates,
  never as guarantees or exact targets.
- Use exactly these emojis: BUY 🟢, HOLD 🟡, AVOID/SELL 🔴.
- If asked about a stock's details: business, sector, trend, valuation (only supplied metrics), growth drivers, risks.
- If the user asks for stock ideas, recommendations or "which stocks to buy/avoid" without naming stocks, use the
  CANDIDATE SCREEN below (live data for popular stocks across sectors). Rank them, give BUY / HOLD / AVOID calls
  for the best and the weakest few, and explain why. Do NOT limit yourself to the user's holdings or watchlist.
  Use their holdings only for diversification context. If they asked to exclude their holdings/watchlist,
  never recommend those.
- For "which stocks should I buy / purchase" style questions, answer with the TOP 5 best-performing candidates from
  the CANDIDATE SCREEN, as a numbered list 1 to 5 (best first, favour BUY signals, then highest 6-month return).
  For each one give: ticker + company name, current price, performance (1M / 6M / 1Y), sector, market cap and P/E
  when supplied, a clear RISK LEVEL (Low / Medium / High) with the reason (use volatility: under 25% Low, 25 to 40%
  Medium, above 40% High; also mention the worst fall in the past year), the Call (BUY or HOLD), 2 short reasons,
  the main risk, and a rough 3-month outlook range. If fewer than 5 have live data, list only those.
  After the list add one line "Stocks to be careful with" naming 1 or 2 weak candidates from the screen and why.
- In one short line, say the picks come from {screen_source}, and be honest that it does not cover every small or
  micro-cap stock. Also say that the user can ask for
  "more stocks", name a sector (banks, pharma, auto, IT...), ask for lists like "top gainers" or "undervalued",
  or name any specific company or ticker to get live analysis.
- Say "Confidence: High" only when several independent signals agree (trend, valuation, momentum). Otherwise Medium
  or Low. Do not base an AVOID call on a downtrend alone when valuation data is available; mention both.
- If the user asks about any stock, even one not in their lists, answer fully when live data is supplied. If a stock
  is listed under MISSING LIVE DATA, do NOT give it a BUY / HOLD / AVOID call, a confidence level or a price outlook.
  Write "No live data right now, so I can't rate it", add 2-3 lines of general business context clearly labelled
  as not live, and suggest retrying in a minute or checking the ticker on Yahoo Finance.
- Use ONLY the supplied data for numbers. Never invent prices, news or analyst targets. Say when data is missing.
- Keep it short and easy: small markdown, bullets, max ~250 words unless the user asks for detail.
- End with one short line: educational information, not personalised financial advice.

USER HOLDINGS:
{hold_txt}

USER WATCHLIST: {watch_txt}

LIVE MARKET DATA (Yahoo Finance, may be delayed):
{market_block or "No specific stock data fetched for this question."}

MISSING LIVE DATA (could not be loaded): {', '.join(missing) or 'none'}

CANDIDATE SCREEN (live data, best signals first; the user wants ideas beyond their own lists):
{candidate_block or ("LIVE SCREEN FAILED: Yahoo Finance returned no data for the screened stocks just now. "
"Start your answer by telling the user in one short line that live data could not be loaded and that they should "
"retry in a minute. Do not present any picks as live-data-based." if discovery_mode else "Not requested.")}

RECENT CONVERSATION:
{convo or "(start of chat)"}

USER QUESTION: {prompt}
"""

    text, error = gemini_text(full_prompt)
    if text:
        return text

    # ---- fallback without AI ----
    lines = ["### FinVest (basic mode)", f"_AI is unavailable: {error}_", ""]
    if used:
        for sym in used:
            try:
                d = get_stock_snapshot(sym)
                s = rule_based_signal(d)
                icon = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}[s["verdict"]]
                lines.append(f"**{sym}**: {icon} {s['verdict']} ({s['risk_level']} risk)")
                lines += [f"- ✅ {p}" for p in s["positives"][:2]] + [f"- ⚠️ {c}" for c in s["concerns"][:2]]
                lines.append("")
            except Exception:
                continue
    else:
        lines.append("Add `GOOGLE_API_KEY` to your `.env` and install `google-genai` for full AI answers.")
    lines.append("_Educational information, not financial advice._")
    return "\n".join(lines)


def _safe(text):
    """Streamlit treats $...$ as math; escape dollar signs so prices render normally."""
    return str(text).replace("\\$", "$").replace("$", "\\$")


def show_ai_chat():
    page_header("🤖", "FinVest AI Chat",
                "Ask about stocks, what to buy or avoid, risks and investing basics, in English or Hinglish.")

    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("Please log in first.")
        return

    history = st.session_state.setdefault("finvest_chat_history", [])

    if not history:
        st.markdown("**Try asking**")
        cols = st.columns(2)
        for i, text in enumerate(SUGGESTIONS):
            cols[i % 2].button(text, key=f"sugg_{i}", on_click=_set_pending,
                               args=(text,), use_container_width=True)
        note("Tip: write a ticker like TCS.NS or AAPL to get live data for that stock.")

    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(_safe(message["content"]))

    prompt = st.chat_input("Ask about a stock, risk, or your portfolio...")
    prompt = prompt or st.session_state.pop("chat_pending", None)

    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Analysing..."):
                try:
                    answer = get_ai_response(prompt, user_id, history)
                except Exception as e:
                    answer = f"Could not generate a response: {e}"
            st.markdown(_safe(answer))

        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": answer})

    if history and st.button("🗑️ Clear conversation", key="chat_clear"):
        st.session_state["finvest_chat_history"] = []
        st.rerun()

    note("AI answers are educational and based on delayed market data. They are not financial advice.")


def render_ai_chat():
    return show_ai_chat()