import os
import re
import json
import html
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------- Gemini ----

_WORKING_MODEL = {}


def _discover_models(client):
    """List Gemini flash models available to this API key, newest first."""
    names = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            actions = getattr(m, "supported_actions", None) or []
            skip = ("image", "tts", "live", "audio", "embedding", "thinking", "lite", "robotics")
            if "flash" in name and "generateContent" in actions and not any(x in name for x in skip):
                names.append(name.replace("models/", ""))
    except Exception:
        pass

    def version(n):
        nums = re.findall(r"\d+(?:\.\d+)?", n)
        return float(nums[0]) if nums else 0.0

    return sorted(set(names), key=version, reverse=True)


def gemini_text(prompt, json_mode=False):
    """Returns (text, error). Tries the new SDK, then the legacy one."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "GOOGLE_API_KEY is missing in your .env file."

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    last_error = None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = (
            types.GenerateContentConfig(response_mime_type="application/json")
            if json_mode else None
        )
        def attempt(name):
            resp = client.models.generate_content(model=name, contents=prompt, config=config)
            return resp.text

        first = _WORKING_MODEL.get("name") or model
        try:
            text = attempt(first)
            if text:
                _WORKING_MODEL["name"] = first
                return text, None
        except Exception as exc:
            last_error = str(exc)
            not_found = "404" in last_error or "NOT_FOUND" in last_error
            if not_found:
                # Configured model was retired: find a model this key can use.
                for candidate in _discover_models(client)[:4]:
                    if candidate == first:
                        continue
                    try:
                        text = attempt(candidate)
                        if text:
                            _WORKING_MODEL["name"] = candidate
                            return text, None
                    except Exception as exc2:
                        last_error = str(exc2)
    except ImportError:
        pass
    except Exception as exc:
        last_error = str(exc)

    try:
        import google.generativeai as legacy

        legacy.configure(api_key=api_key)
        gen = legacy.GenerativeModel(model if "gemini-2" in model else "gemini-1.5-flash")
        kwargs = {"generation_config": {"response_mime_type": "application/json"}} if json_mode else {}
        response = gen.generate_content(prompt, **kwargs)
        if response.text:
            return response.text, None
    except Exception as exc:
        last_error = last_error or str(exc)

    return None, last_error or "AI service unavailable. Install `google-genai` and check your API key."


# -------------------------------------------------------------- Market data --

def _rsi(close, n=14):
    if len(close) <= n:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(n).mean().iloc[-1]
    if pd.isna(gain) or pd.isna(loss):
        return None
    # Standard RSI uses Wilder's smoothing rather than a simple rolling mean.
    # This reduces abrupt spikes while preserving the valid 0-100 RSI range.
    gains = delta.clip(lower=0)
    losses = (-delta.clip(upper=0))
    avg_gain = gains.ewm(alpha=1 / n, min_periods=n, adjust=False).mean().iloc[-1]
    avg_loss = losses.ewm(alpha=1 / n, min_periods=n, adjust=False).mean().iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return None
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    value = 100 - 100 / (1 + avg_gain / avg_loss)
    return float(max(0.0, min(100.0, value)))


@st.cache_data(ttl=300, show_spinner=False)
def get_stock_snapshot(ticker, with_info=True):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y", auto_adjust=True)
    if hist.empty or "Close" not in hist.columns:
        raise ValueError("No usable market data found.")

    close = hist["Close"].dropna()
    if len(close) < 2:
        raise ValueError("Not enough price history.")

    info = {}
    if with_info:
        try:
            info = stock.info or {}
        except Exception:
            info = {}

    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])

    def ret(days):
        n = min(days, len(close) - 1)
        base = float(close.iloc[-1 - n])
        return (price / base - 1) * 100 if base else 0.0

    daily = close.pct_change().dropna()
    vol = float(daily.std() * (252 ** 0.5) * 100) if len(daily) > 2 else None
    drawdown = float(((close / close.cummax()) - 1).min() * 100)

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency") or ("INR" if ticker.endswith((".NS", ".BO")) else "USD"),
        "exchange": info.get("exchange", "Unknown"),
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "price": price,
        "day_change_pct": (price / prev - 1) * 100 if prev else 0.0,
        "return_1m_pct": ret(21),
        "return_6m_pct": ret(126),
        "return_1y_pct": ret(252),
        "volatility_pct": vol,
        "max_drawdown_1y_pct": drawdown,
        "below_52w_high_pct": (price / float(close.max()) - 1) * 100,
        "rsi14": _rsi(close),
        "sma20": float(close.tail(20).mean()),
        "sma50": float(close.tail(50).mean()) if len(close) >= 50 else None,
        "sma200": float(close.tail(200).mean()) if len(close) >= 200 else None,
        "high_52w": float(close.max()),
        "low_52w": float(close.min()),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "revenue_growth": info.get("revenueGrowth"),
        "profit_margin": info.get("profitMargins"),
    }


def rule_based_signal(d):
    """Simple transparent signal. Used as a hint for the AI and as a fallback."""
    score, pos, neg = 0, [], []
    p = d["price"]

    if d["sma50"]:
        if p > d["sma50"]:
            score += 1
            pos.append("Price is above its 50-day average, so the trend is upward.")
        else:
            score -= 1
            neg.append("Price is below its 50-day average, so the trend is weak.")
    if p > d["sma20"]:
        score += 1
        pos.append("Short-term momentum is positive (above the 20-day average).")
    else:
        score -= 1
        neg.append("Short-term momentum is negative (below the 20-day average).")

    r6 = d["return_6m_pct"]
    if r6 > 10:
        score += 1
        pos.append(f"The stock gained {r6:.1f}% in the last 6 months.")
    elif r6 < -10:
        score -= 1
        neg.append(f"The stock fell {abs(r6):.1f}% in the last 6 months.")

    rsi = d["rsi14"]
    if rsi is not None:
        if rsi > 70:
            score -= 1
            neg.append(f"RSI is {rsi:.0f}, so the stock may be overbought and could cool off.")
        elif rsi < 30:
            score += 1
            pos.append(f"RSI is {rsi:.0f}, so the stock may be oversold and could bounce.")

    vol = d["volatility_pct"]
    if vol is None:
        risk = "Medium"
    elif vol < 25:
        risk = "Low"
    elif vol < 40:
        risk = "Medium"
    else:
        risk = "High"
        neg.append(f"Price swings are large (about {vol:.0f}% yearly volatility).")

    verdict = "BUY" if score >= 2 else ("SELL" if score <= -2 else "HOLD")
    if not pos:
        pos.append("No strong positive signal in the price data right now.")
    if not neg:
        neg.append("No major warning sign in the price data, but markets can change quickly.")

    headline = {
        "BUY": "Trend and momentum look supportive.",
        "HOLD": "Signals are mixed. Waiting for a clearer picture is reasonable.",
        "SELL": "Trend and momentum look weak.",
    }[verdict]

    return {
        "verdict": verdict,
        "confidence": min(80, 50 + abs(score) * 10),
        "risk_level": risk,
        "headline": headline,
        "summary": " ".join(pos[:1] + neg[:1]),
        "positives": pos[:3],
        "concerns": neg[:3],
        "action": {
            "BUY": "If you buy, consider entering in parts and set a stop-loss you are comfortable with.",
            "HOLD": "If you already own it, keep watching. If not, wait for a clearer trend.",
            "SELL": "If you own it, review your reasons for holding or consider reducing the position.",
        }[verdict],
    }


# ---------------------------------------------------------------- Insight ----

def _clean_list(value):
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()][:3]


def generate_stock_ai_insight(company_name, ticker, curr_price=None,
                              percent_change=None, language="English", **_):
    """Returns a dict with verdict, summary, positives, concerns... or None."""
    try:
        data = get_stock_snapshot(ticker)
    except Exception:
        return None

    base = rule_based_signal(data)
    prompt = f"""
You are FinVest's stock analyst. Write a SHORT, simple report in {language} for a
beginner investor. Use plain words, no jargon (if you use a term, explain it in a few words).

Company: {company_name or data['name']}  |  Ticker: {ticker}

Market data (Yahoo Finance, may be delayed):
{json.dumps(data, default=str)}

Rule-based technical signal (use as a hint, you may disagree with reasons):
{json.dumps({k: base[k] for k in ('verdict', 'positives', 'concerns')})}

Return ONLY valid JSON with exactly these keys:
{{
  "verdict": "BUY" | "HOLD" | "SELL",
  "confidence": integer 40-90,
  "risk_level": "Low" | "Medium" | "High",
  "headline": "one simple sentence with your overall view",
  "summary": "2-3 simple sentences: what the company does, how the price behaved, what matters now",
  "positives": ["max 3 short bullet points"],
  "concerns": ["max 3 short bullet points"],
  "action": "one practical sentence on what an investor could do (e.g. buy in parts, hold, reduce)"
}}

Field meanings: max_drawdown_1y_pct is the WORST fall seen at any point in the past year, not the current
gap from the high. Use below_52w_high_pct for how far the price is from its 52-week high right now.
dividend_yield is a yield (percent of price), not a payout ratio. Do not call a past drawdown "current".

Rules: use only the supplied data, never invent news or targets, never promise returns,
say when a metric is unavailable. This is educational, not personal financial advice.
"""

    result = dict(base)
    result["source"] = "Rule-based signals"
    text, ai_error = gemini_text(prompt, json_mode=True)

    if text:
        try:
            match = re.search(r"\{.*\}", text, re.S)
            parsed = json.loads(match.group(0)) if match else {}
            verdict = str(parsed.get("verdict", "")).upper()
            if verdict in ("BUY", "HOLD", "SELL"):
                result.update({
                    "verdict": verdict,
                    "confidence": max(30, min(95, int(parsed.get("confidence", base["confidence"])))),
                    "risk_level": parsed.get("risk_level") if parsed.get("risk_level") in ("Low", "Medium", "High") else base["risk_level"],
                    "headline": str(parsed.get("headline") or base["headline"]),
                    "summary": str(parsed.get("summary") or base["summary"]),
                    "positives": _clean_list(parsed.get("positives")) or base["positives"],
                    "concerns": _clean_list(parsed.get("concerns")) or base["concerns"],
                    "action": str(parsed.get("action") or base["action"]),
                    "source": "Gemini AI + market data",
                })
        except Exception:
            pass

    result["stats"] = {
        "return_1m_pct": data["return_1m_pct"],
        "return_6m_pct": data["return_6m_pct"],
        "volatility_pct": data["volatility_pct"],
        "rsi14": data["rsi14"],
    }
    result["ticker"] = ticker
    if result["source"] == "Rule-based signals":
        result["ai_error"] = ai_error or "The AI reply could not be read."
    return result


def render_insight(ins):
    """Draws the verdict card + short report."""
    esc = lambda s: html.escape(str(s)).replace("$", "&#36;")
    verdict = ins["verdict"]
    stats = ins.get("stats", {})

    if ins.get("ai_error"):
        st.warning(
            "AI model is unavailable right now, so this verdict uses price-based signals only. "
            f"Reason: {str(ins['ai_error'])[:180]}"
        )

    st.markdown(
        f'<div class="fv-verdict {verdict.lower()}">'
        f'<div class="tag">{verdict}</div>'
        f'<div><div class="headline">{esc(ins["headline"])}</div>'
        f'<div class="sub">{esc(ins["summary"])}</div></div></div>',
        unsafe_allow_html=True,
    )

    chips = [f'<span class="fv-chip">Confidence <b>{ins["confidence"]}%</b></span>',
             f'<span class="fv-chip">Risk <b>{esc(ins["risk_level"])}</b></span>']
    if stats.get("return_1m_pct") is not None:
        chips.append(f'<span class="fv-chip">1M <b>{stats["return_1m_pct"]:+.1f}%</b></span>')
    if stats.get("return_6m_pct") is not None:
        chips.append(f'<span class="fv-chip">6M <b>{stats["return_6m_pct"]:+.1f}%</b></span>')
    if stats.get("volatility_pct") is not None:
        chips.append(f'<span class="fv-chip">Volatility <b>{stats["volatility_pct"]:.0f}%</b></span>')
    if stats.get("rsi14") is not None:
        chips.append(f'<span class="fv-chip">RSI <b>{stats["rsi14"]:.0f}</b></span>')
    st.markdown(f'<div class="fv-chips">{"".join(chips)}</div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    for col, title, items in ((left, "✅ What looks good", ins["positives"]),
                              (right, "⚠️ What to watch", ins["concerns"])):
        li = "".join(f"<li>{esc(i)}</li>" for i in items)
        col.markdown(f'<div class="fv-card"><h4>{title}</h4><ul>{li}</ul></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="fv-action"><b>What you could do:</b> {esc(ins["action"])}</div>'
        f'<div class="fv-note">Source: {esc(ins["source"])} · Yahoo Finance data may be delayed. '
        f'Educational information only, not financial advice.</div>',
        unsafe_allow_html=True,
    )