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
    portfolio: float = 2_000_000      # THB
    risk_pct: float = 1.0             # % of portfolio risked per trade
    atr_mult: float = 2.0             # stop distance in ATRs
    min_rr: float = 2.0               # minimum reward:risk to call it "ready"
    resistance_lookback: int = 60     # bars used to find the previous swing high
    lot: int = 100                    # board lot for Thai shares

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
def fetch_prices(tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
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
STATUS_ORDER = {"พร้อมเข้า": 0, "R:R ต่ำ": 1, "ใกล้เข้า": 2, "รอย่อ": 3, "นอกแนวโน้ม": 4, "ข้อมูลไม่พอ": 5}


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

    # trade plan
    stop = close - s.atr_mult * a
    risk = close - stop
    window = d["High"].iloc[-(s.resistance_lookback + 1):-1]
    resistance = float(window.max()) if len(window) else float("nan")
    support = float(d["Low"].iloc[-20:].min())
    if resistance > close + 0.5 * risk:
        target, target_src = resistance, "แนวต้าน"
    else:
        target, target_src = close + 2 * risk, "2R (ราคาอยู่ใกล้จุดสูงสุด)"
    rr = (target - close) / risk if risk > 0 else float("nan")
    max_entry = target - s.min_rr * risk if target_src == "แนวต้าน" else float("nan")

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
        "entry": close,
        "stop": stop,
        "stop_pct": -risk / close * 100,
        "support20": support,
        "resistance": resistance,
        "target": target,
        "target_src": target_src,
        "target_pct": (target / close - 1) * 100,
        "target_2r": close + 2 * risk,
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


def scan(watch: pd.DataFrame, s: Settings, prices: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    if prices is None:
        prices = fetch_prices(watch["yahoo"].tolist())
    rows = []
    for _, w in watch.iterrows():
        df = prices.get(w["yahoo"])
        r = analyze(df, s) if df is not None else {"status": "ข้อมูลไม่พอ"}
        r.update({"symbol": w["symbol"], "yahoo": w["yahoo"], "market": w["market"],
                  "group": w["group"], "note": w["note"]})
        r["shares"] = shares_for(r, s) if r["status"] != "ข้อมูลไม่พอ" else float("nan")
        rows.append(r)
    out = pd.DataFrame(rows)
    out["_o"] = out["status"].map(STATUS_ORDER).fillna(9)
    out = out.sort_values(["_o", "rr"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
    return out


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
