"""Swing Scanner engine: data, indicators, signals, trade plan, fundamentals.

Technique: Buy the Pullback in an Uptrend
  1) Trend   : Close > EMA50 > EMA200
  2) Pullback: lowest low of the last 3 bars came within 0.25 ATR of EMA20,
               and price still closes above EMA50
  3) RSI turn: RSI(14) dipped to 30-50 within the last 5 bars and today's RSI > yesterday's
Trade plan  : entry = last close, stop = entry - mult * ATR(14),
              target = previous swing high (resistance) or 2R when price is at highs.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)


# ----------------------------------------------------------------- settings
@dataclass
class Settings:
    portfolio: float = 500_000        # THB
    risk_pct: float = 2.0             # % of portfolio risked per trade
    atr_mult: float = 2.0             # stop distance in ATRs
    min_rr: float = 2.0               # minimum reward:risk to call it "ready"
    resistance_lookback: int = 60     # bars used to find the previous swing high
    lot: int = 100                    # board lot for Thai shares
    earnings_buffer: int = 14         # days: flag a setup if earnings fall inside this window
    hold_days: int = 15               # trading days: time stop for a swing trade

    @classmethod
    def load(cls) -> "Settings":
        p = BASE / "settings.json"
        if p.exists():
            try:
                return cls(**{**asdict(cls()), **json.loads(p.read_text(encoding="utf-8"))})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        (BASE / "settings.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def load_watchlist() -> pd.DataFrame:
    df = pd.read_csv(BASE / "watchlist.csv", dtype=str, encoding="utf-8").fillna("")
    df["symbol"] = df["symbol"].str.strip().str.upper()
    df["yahoo"] = df["yahoo"].str.strip()
    df = df[df["symbol"] != ""]
    df.loc[df["yahoo"] == "", "yahoo"] = df["symbol"]
    return df.reset_index(drop=True)


def save_watchlist(df: pd.DataFrame) -> None:
    cols = ["symbol", "yahoo", "market", "group", "note"]
    df = df.reindex(columns=cols).fillna("")
    df.to_csv(BASE / "watchlist.csv", index=False, encoding="utf-8")


# ----------------------------------------------------------------- data
def fetch_prices(tickers: list[str], period: str = "3y") -> dict[str, pd.DataFrame]:
    """Daily OHLCV per Yahoo ticker. Missing tickers are left out."""
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    if not tickers:
        return out
    raw = yf.download(tickers, period=period, interval="1d", group_by="ticker",
                      auto_adjust=True, threads=True, progress=False)
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            if len(df) >= 60:
                out[t] = df
        except Exception:
            continue
    return out


# ----------------------------------------------------------------- indicators
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI (same as TradingView / Streaming default)."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's ATR."""
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA20"] = ema(df["Close"], 20)
    df["EMA50"] = ema(df["Close"], 50)
    df["EMA200"] = ema(df["Close"], 200)
    df["RSI"] = rsi(df["Close"])
    df["ATR"] = atr(df)
    df["VolAvg20"] = df["Volume"].rolling(20).mean()
    return df


# ----------------------------------------------------------------- signals + plan
STATUS_ORDER = {"พร้อมเข้า": 0, "ระวังงบ": 1, "R:R ต่ำ": 2, "ใกล้เข้า": 3, "รอย่อ": 4, "นอกแนวโน้ม": 5, "ข้อมูลไม่พอ": 6}


def trade_levels(close: float, atr_v: float, low10: float, resistance: float, s: Settings) -> dict:
    """Entry/stop/targets from several methods. Used by the live scan and the backtest alike.

    Stop  : structure first (0.2 ATR under the lowest low of the last 10 bars), but kept
            between 1 ATR (noise floor) and atr_mult+0.5 ATR (too wide) from the entry.
    TP1/2 : candidates are the previous swing high (resistance), 2R, and the stock's
            expected range over the holding period (ATR x sqrt(hold_days)). Only targets
            at least 1R away count. TP1 = nearest, TP2 = farthest but capped at the
            expected range, so the plan stays realistic for a 2-3 week hold.
    R:R   : blended, assuming half is sold at TP1 and half at TP2."""
    struct = low10 - 0.2 * atr_v
    dist = close - struct
    lo, hi = 1.0 * atr_v, (s.atr_mult + 0.5) * atr_v
    if lo <= dist <= hi:
        stop, stop_src = struct, "ใต้จุดต่ำสุดของการย่อ 10 วัน"
    elif dist < lo:
        stop, stop_src = close - lo, "1×ATR (จุดต่ำสุดใกล้ราคาเกินไป)"
    else:
        stop, stop_src = close - s.atr_mult * atr_v, f"{s.atr_mult:g}×ATR (จุดต่ำสุดไกลเกินไป)"
    risk = close - stop
    t_rng = close + atr_v * math.sqrt(max(1, s.hold_days))
    cands = [(close + 2 * risk, "2R"), (t_rng, f"กรอบแกว่ง {s.hold_days} วัน")]
    if resistance == resistance and resistance > close:
        cands.append((resistance, "แนวต้าน"))
    cands = [c for c in cands if c[0] >= close + 1.0 * risk] or [(close + 2 * risk, "2R")]
    tp1 = min(cands, key=lambda c: c[0])
    far = max(cands, key=lambda c: c[0])
    tp2 = far if far[0] <= max(t_rng, tp1[0]) else (max(t_rng, tp1[0]), f"กรอบแกว่ง {s.hold_days} วัน")
    blend = 0.5 * tp1[0] + 0.5 * tp2[0]
    rr = (blend - close) / risk if risk > 0 else float("nan")
    m = s.min_rr
    max_entry = (blend + m * stop) / (1 + m)
    return {"stop": stop, "stop_src": stop_src, "risk": risk,
            "tp1": tp1[0], "tp1_src": tp1[1], "tp2": tp2[0], "tp2_src": tp2[1],
            "rr": rr, "max_entry": max_entry}


def signal_frame(d: pd.DataFrame) -> pd.DataFrame:
    """Vectorised version of the three entry conditions (d must already have indicators)."""
    trend = (d["Close"] > d["EMA50"]) & (d["EMA50"] > d["EMA200"])
    pull = (d["Low"].rolling(3).min() <= d["EMA20"] + 0.25 * d["ATR"]) & (d["Close"] >= d["EMA50"])
    rmin = d["RSI"].rolling(5).min()
    turn = rmin.between(30, 50) & (d["RSI"] > d["RSI"].shift())
    return pd.DataFrame({"trend": trend, "pullback": pull, "rsi_turn": turn,
                         "signal": trend & pull & turn}, index=d.index)


def backtest(df: pd.DataFrame, s: Settings, return_trades: bool = False) -> dict:
    """Replay the exact rules on history: enter next day's open after a signal, sell half at
    TP1 and move the stop to breakeven, sell the rest at TP2, or exit at the close after
    hold_days. If stop and target touch on the same day the stop is assumed first
    (conservative). One trade at a time."""
    d = add_indicators(df)
    sig = signal_frame(d)["signal"].values
    o, h, l, c = (d[k].values for k in ("Open", "High", "Low", "Close"))
    atr_v, n = d["ATR"].values, len(d)
    trades, i = [], 210
    while i < n - 1:
        if not sig[i]:
            i += 1
            continue
        lo10 = l[max(0, i - 9):i + 1].min()
        res = h[max(0, i - s.resistance_lookback):i].max()
        lv = trade_levels(c[i], atr_v[i], lo10, res, s)
        entry = o[i + 1]
        stop = lv["stop"]
        if not entry > stop:
            i += 1
            continue
        risk = entry - stop
        left, R, half = 1.0, 0.0, False
        j_end = min(i + s.hold_days, n - 1)
        j = i + 1
        while j <= j_end:
            if l[j] <= stop:
                R += left * (stop - entry) / risk
                left = 0.0
                break
            if not half and h[j] >= lv["tp1"]:
                R += 0.5 * (lv["tp1"] - entry) / risk
                left, half, stop = 0.5, True, entry
            if half and h[j] >= lv["tp2"]:
                R += left * (lv["tp2"] - entry) / risk
                left = 0.0
                break
            j += 1
        j = min(j, j_end)
        if left > 0:
            R += left * (c[j] - entry) / risk
        trades.append({"date": d.index[i + 1], "R": R, "days": j - i})
        i = j + 1
    if not trades:
        if return_trades:
            return []
        return {"bt_n": 0, "bt_win": float("nan"), "bt_avg_r": float("nan"), "bt_days": float("nan")}
    rs = pd.Series([t["R"] for t in trades])
    if return_trades:
        return trades
    return {"bt_n": len(trades), "bt_win": float((rs > 0).mean() * 100), "bt_avg_r": float(rs.mean()),
            "bt_days": float(pd.Series([t["days"] for t in trades]).mean())}



def analyze(df: pd.DataFrame, s: Settings) -> dict:
    if len(df) < 210:
        return {"status": "ข้อมูลไม่พอ"}
    d = add_indicators(df)
    last, prev = d.iloc[-1], d.iloc[-2]
    close, a = float(last["Close"]), float(last["ATR"])
    e20, e50, e200 = float(last["EMA20"]), float(last["EMA50"]), float(last["EMA200"])

    trend = close > e50 > e200
    low3 = float(d["Low"].iloc[-3:].min())
    pullback = (low3 <= e20 + 0.25 * a) and close >= e50
    rsi_min5 = float(d["RSI"].iloc[-5:].min())
    rsi_turn = (30 <= rsi_min5 <= 50) and float(last["RSI"]) > float(prev["RSI"])
    checks = int(trend) + int(pullback) + int(rsi_turn)

    # trade plan (shared with the backtest)
    low10 = float(d["Low"].iloc[-10:].min())
    window = d["High"].iloc[-(s.resistance_lookback + 1):-1]
    resistance = float(window.max()) if len(window) else float("nan")
    support = float(d["Low"].iloc[-20:].min())
    lv = trade_levels(close, a, low10, resistance, s)
    stop, risk, rr, max_entry = lv["stop"], lv["risk"], lv["rr"], lv["max_entry"]
    target, target_src = lv["tp1"], lv["tp1_src"]
    bt = backtest(df, s)

    risk_baht = s.portfolio * s.risk_pct / 100
    position_value = min(risk_baht / (risk / close), s.portfolio) if risk > 0 else 0.0

    if not trend:
        status = "นอกแนวโน้ม"
    elif checks == 3 and rr >= s.min_rr:
        status = "พร้อมเข้า"
    elif checks == 3:
        status = "R:R ต่ำ"
    elif checks == 2:
        status = "ใกล้เข้า"
    else:
        status = "รอย่อ"

    vol_ratio = float(last["Volume"] / last["VolAvg20"]) if last["VolAvg20"] else float("nan")
    c = d["Close"]
    ret21 = float(c.iloc[-1] / c.iloc[-22] - 1) * 100 if len(c) > 22 else float("nan")
    ret63 = float(c.iloc[-1] / c.iloc[-64] - 1) * 100 if len(c) > 64 else float("nan")
    tail = d.iloc[-10:]
    upv = float(tail.loc[tail["Close"] >= tail["Close"].shift().fillna(tail["Open"]), "Volume"].sum())
    dnv = float(tail["Volume"].sum()) - upv
    updown = upv / dnv if dnv > 0 else 2.0
    return {
        "status": status,
        "checks": checks,
        "trend": trend,
        "pullback": pullback,
        "rsi_turn": rsi_turn,
        "date": d.index[-1].strftime("%Y-%m-%d"),
        "close": close,
        "chg_pct": (close / float(prev["Close"]) - 1) * 100,
        "ema20": e20, "ema50": e50, "ema200": e200,
        "rsi": float(last["RSI"]),
        "atr": a,
        "atr_pct": a / close * 100,
        "dist_ema20_atr": (close - e20) / a if a else float("nan"),
        "vol_ratio": vol_ratio,
        "ret21": ret21,
        "ret63": ret63,
        "updown_vol": updown,
        "entry": close,
        "stop": stop,
        "stop_pct": -risk / close * 100,
        "support20": support,
        "resistance": resistance,
        "target": target,
        "target_src": target_src,
        "target_pct": (target / close - 1) * 100,
        "target_2r": close + 2 * risk,
        "target2": lv["tp2"],
        "target2_src": lv["tp2_src"],
        "target2_pct": (lv["tp2"] / close - 1) * 100,
        "stop_src": lv["stop_src"],
        "hold_until": (pd.Timestamp.today().normalize() + pd.offsets.BDay(s.hold_days)).strftime("%Y-%m-%d"),
        **bt,
        "rr": rr,
        "max_entry": max_entry,
        "risk_baht": risk_baht,
        "position_value": position_value,
    }


def shares_for(row: dict, s: Settings) -> float:
    """Whole-lot share count for Thai stocks; for DR the value in THB is what matters."""
    if row.get("market") == "TH" and row.get("entry"):
        lot = max(1, int(s.lot))
        return math.floor(row["position_value"] / row["entry"] / lot) * lot
    return float("nan")


INDEX_NAMES = {"^SET.BI": "SET", "^IXIC": "Nasdaq", "^HSI": "Hang Seng", "000300.SS": "CSI 300", "^N225": "Nikkei"}


def index_for(yahoo: str) -> str:
    y = str(yahoo).upper()
    if y.endswith(".BK"):
        return "^SET.BI"
    if y.endswith(".HK"):
        return "^HSI"
    if y.endswith(".SZ") or y.endswith(".SS"):
        return "000300.SS"
    if y.endswith(".T"):
        return "^N225"
    return "^IXIC"


REGIME_MULT = {"ขาขึ้น": 1.0, "ระวัง": 0.5, "ขาลง": 0.25}


def market_regime(df: pd.DataFrame | None) -> dict:
    """ขาขึ้น: close > EMA50 > EMA200 · ระวัง: still above EMA200 but not a clean uptrend · ขาลง: below EMA200."""
    if df is None or len(df) < 210:
        return {"state": "ไม่ทราบ", "mult": 1.0}
    c = df["Close"]
    e50, e200 = ema(c, 50), ema(c, 200)
    close, a50, a200 = float(c.iloc[-1]), float(e50.iloc[-1]), float(e200.iloc[-1])
    if close > a50 > a200:
        state = "ขาขึ้น"
    elif close > a200:
        state = "ระวัง"
    else:
        state = "ขาลง"
    ret63 = float(c.iloc[-1] / c.iloc[-64] - 1) * 100
    ret21 = float(c.iloc[-1] / c.iloc[-22] - 1) * 100
    return {"state": state, "mult": REGIME_MULT[state], "close": close, "ema50": a50, "ema200": a200,
            "ret21": ret21, "ret63": ret63, "chg_pct": float(c.iloc[-1] / c.iloc[-2] - 1) * 100}


def regimes(prices: dict[str, pd.DataFrame]) -> dict[str, dict]:
    return {ix: market_regime(prices.get(ix)) | {"name": nm} for ix, nm in INDEX_NAMES.items()}


def _clip01(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(x) else max(0.0, min(1.0, x))


def scan(watch: pd.DataFrame, s: Settings, prices: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    if prices is None:
        prices = fetch_prices(watch["yahoo"].tolist() + list(INDEX_NAMES))
    reg = regimes(prices)
    # fallback when Yahoo does not return an index: equal-weight average of the listed stocks in that market
    for ix, g in reg.items():
        if g["state"] != "ไม่ทราบ":
            continue
        members = [prices[y] for y in watch["yahoo"] if index_for(y) == ix and y in prices]
        if len(members) < 5:
            continue
        closes = pd.concat([m["Close"] / m["Close"].dropna().iloc[0] for m in members], axis=1).ffill()
        proxy = pd.DataFrame({"Close": closes.mean(axis=1).dropna()})
        p_ = market_regime(proxy)
        if p_["state"] != "ไม่ทราบ":
            reg[ix] = p_ | {"name": f"{INDEX_NAMES[ix]}*", "proxy": len(members)}
    rows = []
    for _, w in watch.iterrows():
        df = prices.get(w["yahoo"])
        r = analyze(df, s) if df is not None else {"status": "ข้อมูลไม่พอ"}
        r.update({"symbol": w["symbol"], "yahoo": w["yahoo"], "market": w["market"],
                  "group": w["group"], "note": w["note"]})
        ix = index_for(w["yahoo"])
        g = reg.get(ix, {"state": "ไม่ทราบ", "mult": 1.0})
        r["index"] = INDEX_NAMES.get(ix, ix)
        r["regime"] = g["state"]
        r["size_mult"] = g["mult"]
        if r["status"] != "ข้อมูลไม่พอ":
            # relative strength = stock return minus its home index over the same window
            r["rs63"] = r["ret63"] - g.get("ret63", 0.0) if "ret63" in g else r["ret63"]
            r["rs21"] = r["ret21"] - g.get("ret21", 0.0) if "ret21" in g else r["ret21"]
            r["position_value"] = r["position_value"] * g["mult"]
            r["shares"] = shares_for(r, s)
        else:
            r["shares"] = float("nan")
        rows.append(r)
    out = pd.DataFrame(rows)

    # composite score 0-100: RS rank 40% · volume 30% · reward:risk 30%
    ok = out["status"] != "ข้อมูลไม่พอ"
    rs = (0.7 * out["rs63"] + 0.3 * out["rs21"]) if "rs63" in out else pd.Series(0.0, index=out.index)
    out["rs_pct"] = rs.where(ok).rank(pct=True) * 100
    vol_s = out.get("vol_ratio", pd.Series(dtype=float)).map(lambda v: _clip01((v - 0.5) / 1.5)) * 50 \
        + out.get("updown_vol", pd.Series(dtype=float)).map(lambda v: _clip01((v - 0.5) / 1.5)) * 50
    out["vol_score"] = vol_s.where(ok)
    rr_s = out.get("rr", pd.Series(dtype=float)).map(lambda v: _clip01(v / 3.0)) * 100
    out["score"] = (0.4 * out["rs_pct"].fillna(0) + 0.3 * vol_s.fillna(0) + 0.3 * rr_s.fillna(0)).where(ok)

    out["_o"] = out["status"].map(STATUS_ORDER).fillna(9)
    out = out.sort_values(["_o", "score"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
    out = add_actions(out, s)
    out.attrs["regimes"] = reg
    return out



def _f(x):
    return f"{x:,.2f}"


def add_actions(res: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Turn each status into one plain instruction plus the price to act at."""
    acts, buys = [], []
    for _, r in res.iterrows():
        st_ = r["status"]
        if st_ == "พร้อมเข้า":
            buy = min(r["close"] * 1.01, r["max_entry"])
            acts.append(f"ซื้อได้ ราคาไม่เกิน {_f(buy)}")
        elif st_ == "ระวังงบ":
            buy = min(r["close"] * 1.01, r["max_entry"])
            acts.append(f"งบออกใน {r.get('earn_days', 0):.0f} วัน: รอหลังงบ หรือซื้อครึ่งไม้")
        elif st_ == "R:R ต่ำ":
            buy = r["max_entry"]
            acts.append(f"ตั้งซื้อรอที่ {_f(buy)}")
        elif st_ == "ใกล้เข้า":
            buy = r["ema20"]
            if not r["pullback"]:
                acts.append(f"รอย่อถึงแถว {_f(r['ema20'])} (EMA20)")
            elif not r["rsi_turn"]:
                acts.append("รอ RSI หักหัวขึ้น แล้วซื้อ")
            else:
                acts.append("เฝ้าดูพรุ่งนี้")
        elif st_ == "รอย่อ":
            buy = r["ema20"]
            acts.append(f"แนวโน้มดี รอย่อถึง {_f(r['ema20'])}")
        elif st_ == "นอกแนวโน้ม":
            buy = float("nan")
            acts.append("ข้าม")
        else:
            buy = float("nan")
            acts.append("ไม่มีข้อมูล")
        buys.append(buy)
    res = res.copy()
    res["action"] = acts
    res["buy_price"] = buys
    return res

# ----------------------------------------------------------------- earnings dates
EARN_CACHE = DATA / "earnings.json"


def set_deadline_window(today=None) -> tuple:
    """Next SET reporting window for Thai stocks when no announced date is known.
    SET rules: quarterly statements within 45 days of quarter end; annual statements
    within 2 months (companies not filing a separate Q4). Most firms report in the
    last two weeks before the deadline, so the window is [deadline-14d, deadline]."""
    import datetime as dt
    today = today or dt.date.today()
    cands = []
    for y in (today.year - 1, today.year, today.year + 1):
        for qe in (dt.date(y, 3, 31), dt.date(y, 6, 30), dt.date(y, 9, 30)):
            cands.append(qe + dt.timedelta(days=45))
        # annual: end of February of the following year
        mar1 = dt.date(y + 1, 3, 1)
        cands.append(mar1 - dt.timedelta(days=1))
    deadline = min(d for d in cands if d >= today)
    return deadline - dt.timedelta(days=14), deadline


def fetch_earnings(watch: pd.DataFrame, max_age_hours: float = 12) -> dict[str, dict]:
    """{yahoo_ticker: {"date": "YYYY-MM-DD", "source": "Yahoo" | "ประมาณ (กฎ SET)"}}"""
    import datetime as dt
    cache = {}
    if EARN_CACHE.exists():
        try:
            cache = json.loads(EARN_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    now, today = time.time(), dt.date.today()
    def lookup(t):
        found = None
        try:
            import yfinance as yf
            cal = yf.Ticker(t).calendar or {}
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            for d in (dates or []):
                d = pd.Timestamp(d).date()
                if d >= today - dt.timedelta(days=1):
                    found = {"date": d.isoformat(), "source": "Yahoo"}
                    break
        except Exception:
            pass
        if found is None and str(t).upper().endswith(".BK"):
            start, end = set_deadline_window(today)
            found = {"date": start.isoformat(), "end": end.isoformat(), "source": "ประมาณ (กฎ SET)"}
        return (found or {"date": None, "source": "ไม่พบ"}) | {"_ts": now}

    out, todo = {}, []
    for t in watch["yahoo"]:
        c = cache.get(t)
        if c and now - c.get("_ts", 0) < max_age_hours * 3600:
            out[t] = c
        else:
            todo.append(t)
    if todo:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, f in zip(todo, ex.map(lookup, todo)):
                cache[t] = f
                out[t] = f
    try:
        EARN_CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


def apply_earnings(res: pd.DataFrame, earn: dict[str, dict], s: Settings) -> pd.DataFrame:
    import datetime as dt
    today = dt.date.today()
    days, src, edate = [], [], []
    for _, r in res.iterrows():
        e = earn.get(r["yahoo"], {})
        d = e.get("date")
        if d:
            n = (dt.date.fromisoformat(d) - today).days
            end = e.get("end")
            if end and n < 0 <= (dt.date.fromisoformat(end) - today).days:
                n = 0  # inside the estimated window
            days.append(max(n, 0)); edate.append(d if not end else f"{d} – {end}")
        else:
            days.append(float("nan")); edate.append("")
        src.append(e.get("source", ""))
    res = res.copy()
    res["earn_days"] = days
    res["earn_date"] = edate
    res["earn_src"] = src
    near = res["earn_days"].le(s.earnings_buffer)
    res.loc[near & res["status"].isin(["พร้อมเข้า", "R:R ต่ำ"]), "status"] = "ระวังงบ"
    res["_o"] = res["status"].map(STATUS_ORDER).fillna(9)
    attrs = dict(res.attrs)
    res = res.sort_values(["_o", "score"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
    res = add_actions(res, s)
    res.attrs.update(attrs)
    return res


# ----------------------------------------------------------------- fundamentals (criteria 1-4 auto, 5 manual)
FUND_CACHE = DATA / "fundamentals.json"


def fetch_fundamentals(tickers: list[str], max_age_days: float = 7) -> dict[str, dict]:
    cache = {}
    if FUND_CACHE.exists():
        try:
            cache = json.loads(FUND_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    now = time.time()
    need = [t for t in tickers if now - cache.get(t, {}).get("_ts", 0) > max_age_days * 86400]
    if need:
        import yfinance as yf
        for t in need:
            try:
                info = yf.Ticker(t).info or {}
            except Exception:
                info = {}
            keys = ["forwardPE", "trailingPE", "pegRatio", "trailingPegRatio", "earningsGrowth",
                    "revenueGrowth", "operatingMargins", "freeCashflow", "totalRevenue",
                    "totalCash", "totalDebt", "currency", "financialCurrency"]
            cache[t] = {k: info.get(k) for k in keys} | {"_ts": now}
        FUND_CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return {t: cache.get(t, {}) for t in tickers}


def _num(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def score_fundamentals(f: dict, gap_pts: float | None = None) -> dict:
    """Five criteria. Returns values and pass/fail (None = no data)."""
    peg = _num(f.get("pegRatio")) or _num(f.get("trailingPegRatio"))
    fpe = _num(f.get("forwardPE"))
    rev_g = _num(f.get("revenueGrowth"))
    op_m = _num(f.get("operatingMargins"))
    fcf, rev = _num(f.get("freeCashflow")), _num(f.get("totalRevenue"))
    cash, debt = _num(f.get("totalCash")), _num(f.get("totalDebt"))

    r40 = (rev_g + op_m) * 100 if rev_g is not None and op_m is not None else None
    fcf_m = fcf / rev * 100 if fcf is not None and rev else None
    net_cash = (cash - (debt or 0)) if cash is not None else None
    implied_g = fpe / peg if peg and fpe else None

    res = {
        "peg": peg, "implied_growth": implied_g,
        "rule40": r40, "fcf_margin": fcf_m, "net_cash": net_cash,
        "gap_pts": gap_pts,
        "c1": None if peg is None else peg < 2,
        "c2": None if r40 is None else r40 >= 40,
        "c3": None if fcf_m is None else fcf_m >= 5,
        "c4": None if net_cash is None else net_cash >= 0,
        "c5": None if gap_pts is None else gap_pts <= 10,
    }
    known = [res[k] for k in ("c1", "c2", "c3", "c4", "c5") if res[k] is not None]
    res["passed"] = sum(known)
    res["known"] = len(known)
    return res


def load_manual_gap() -> dict[str, float]:
    p = BASE / "fundamentals_manual.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p, dtype={"symbol": str}).dropna(subset=["gap_pts"])
    return dict(zip(df["symbol"].str.upper(), df["gap_pts"].astype(float)))


# ----------------------------------------------------------------- company profile + news
def company_profile(yahoo: str) -> dict:
    import yfinance as yf
    try:
        info = yf.Ticker(yahoo).info or {}
    except Exception:
        info = {}
    keys = ["longName", "shortName", "sector", "industry", "country", "website", "fullTimeEmployees",
            "marketCap", "currency", "longBusinessSummary", "trailingPE", "forwardPE", "dividendYield",
            "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "recommendationKey", "targetMeanPrice", "numberOfAnalystOpinions"]
    return {k: info.get(k) for k in keys}


def company_news(yahoo: str, limit: int = 10) -> list[dict]:
    """Latest headlines from Yahoo Finance. Handles both the old flat and the newer nested news format."""
    import yfinance as yf
    try:
        raw = yf.Ticker(yahoo).news or []
    except Exception:
        raw = []
    out = []
    for n in raw:
        c = n.get("content", n) if isinstance(n, dict) else {}
        title = c.get("title")
        if not title:
            continue
        url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
        pub = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
        when = c.get("pubDate") or c.get("displayTime")
        if not when and c.get("providerPublishTime"):
            when = pd.Timestamp(c["providerPublishTime"], unit="s").isoformat()
        out.append({"title": title, "url": url, "publisher": pub,
                    "date": str(when)[:10] if when else "", "summary": c.get("summary") or ""})
        if len(out) >= limit:
            break
    return out
