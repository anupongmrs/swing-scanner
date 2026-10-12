"""Swing Scanner — Streamlit app. Run:  streamlit run app.py"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import importlib

import engine as E

E = importlib.reload(E)  # pick up engine.py changes after a git update without a reboot

st.set_page_config(page_title="Swing Scanner", page_icon="📈", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&family=Prompt:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select, label,
[data-testid="stMetricValue"], [data-testid="stMetricLabel"], [data-testid="stSidebar"] * {
  font-family: 'Poppins', 'Prompt', sans-serif !important;
}
:root { --ink:#111111; --paper:#F3F1EA; --lime:#D8E64B; --up:#4F7F52; --down:#C2362B; }
h1 { font-weight: 600 !important; letter-spacing: -0.03em; font-size: 2.6rem !important; }
h2, h3 { font-weight: 600 !important; letter-spacing: -0.02em; }
[data-testid="stSidebar"] { background: var(--paper); }
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {
  background: var(--paper); border-radius: 24px; padding: 10px; overflow: hidden;
}
.stButton > button { border-radius: 999px !important; border: 1.5px solid var(--ink) !important;
  background: var(--ink) !important; color: var(--paper) !important; font-weight: 500; }
.stButton > button:hover { background: var(--paper) !important; color: var(--ink) !important; }
.bento { display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 6px 0 16px; }
.card { border-radius: 24px; padding: 16px 18px; background: var(--paper); color: var(--ink); min-width: 0; }
.card.dark { background: var(--ink); color: var(--paper); }
.card.wide { grid-column: span 2; }
@media (max-width: 640px) { .card.wide { grid-column: span 1; } }
.pill { display:inline-block; border:1.5px solid currentColor; border-radius:999px; padding:2px 12px;
  font-size:.78rem; font-weight:500; margin: 0 6px 8px 0; white-space: nowrap; }
.pill.solid { background: var(--lime); color: var(--ink); border-color: var(--lime); }
.big { font-size: 2.6rem; font-weight: 500; letter-spacing: -0.04em; line-height: 1.05; font-variant-numeric: tabular-nums; }
.mid { font-size: 1.5rem; font-weight: 500; letter-spacing: -0.02em; line-height: 1.15; font-variant-numeric: tabular-nums; }
.lab { font-size: .8rem; opacity: .7; margin-top: 4px; }
.act { font-size: 1.15rem; font-weight: 500; margin-top: 4px; }
.neg { color: var(--down); } .pos { color: var(--up); }
.card.dark .pos { color: var(--lime); } .card.dark .neg { color: #FF8A7A; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- helpers
def fmt(x, d=2):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return "–"
        return f"{x:,.{d}f}"
    except Exception:
        return "–"


@st.cache_data(ttl=3600, show_spinner=False)
def get_prices(tickers: tuple[str, ...]):
    return E.fetch_prices(list(tickers))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_earnings(tickers: tuple[str, ...]):
    w = pd.DataFrame({"yahoo": list(tickers)})
    return E.fetch_earnings(w)


STATUS_COLOR = {
    "พร้อมเข้า": "#86efac",   # strong green
    "ใกล้เข้า": "#d1fae5",    # light green
    "R:R ต่ำ": "#fef3c7",     # amber: valid setup, entry price too high
    "รอย่อ": "#e5e7eb",       # neutral grey
    "นอกแนวโน้ม": "#f3f4f6",  # light grey: simply not a candidate
    "ระวังงบ": "#fca5a5",     # red: genuine risk
    "ข้อมูลไม่พอ": "#f3f4f6",
}

# ---------------------------------------------------------------- sidebar
s = E.Settings.load()
with st.sidebar:
    st.header("ตั้งค่า")
    s.portfolio = st.number_input("ขนาดพอร์ต (บาท)", min_value=10_000.0, value=float(s.portfolio), step=50_000.0, format="%.0f",
        help="เงินทั้งหมดที่ใช้เทรด ระบบใช้คำนวณว่าแต่ละไม้ควรซื้อกี่บาท")
    s.risk_pct = st.number_input("เสี่ยงต่อไม้ (%)", min_value=0.1, max_value=5.0, value=float(s.risk_pct), step=0.1,
        help="ถ้าโดนคัดลอส ยอมขาดทุนกี่ % ของพอร์ต มือใหม่ 0.5–1% · ไม่ควรเกิน 2%")
    st.caption(f"→ ถ้าโดนคัดลอส จะเสียไม่เกิน **{fmt(s.portfolio * s.risk_pct / 100, 0)} บาท** ต่อไม้")
    s.atr_mult = st.number_input("ระยะคัดลอสสำรอง (× ATR)", min_value=0.5, max_value=4.0, value=float(s.atr_mult), step=0.25,
        help="ATR = ระยะที่หุ้นแกว่งเฉลี่ยต่อวัน ปกติระบบวางคัดลอสใต้จุดต่ำสุดของการย่อ "
             "แต่ถ้าจุดนั้นไกลเกินไป จะใช้ระยะนี้แทน และจะไม่ให้คัดลอสห่างเกิน (ค่านี้ + 0.5) × ATR")
    s.min_rr = st.number_input("R:R ขั้นต่ำ", min_value=1.0, max_value=5.0, value=float(s.min_rr), step=0.5,
        help="กำไรที่คาดหวังต้องมากกว่าความเสี่ยงกี่เท่า 2 = ยอมเสีย 1 บาทเพื่อลุ้นกำไร 2 บาท "
             "ตัวที่ต่ำกว่านี้จะขึ้น 'R:R ต่ำ' และบอกราคาที่ควรตั้งซื้อรอ")
    s.hold_days = st.number_input("ถือไม่เกิน (วันทำการ)", min_value=5, max_value=40, value=int(s.hold_days), step=1,
        help="ครบกำหนดแล้วยังไม่ถึงเป้า ให้ขายออกแล้วหาไม้ใหม่ · 15 วันทำการ ≈ 3 สัปดาห์ "
             "ค่านี้ใช้กำหนดเป้าขายที่ 2 ด้วย (หุ้นแกว่งได้ประมาณ ATR × √วัน)")
    s.resistance_lookback = st.number_input("หาแนวต้านย้อนหลัง (วัน)", min_value=20, max_value=250, value=int(s.resistance_lookback), step=10,
        help="ใช้จุดสูงสุดในช่วงนี้เป็นแนวต้าน 60 วัน ≈ 3 เดือน")
    s.earnings_buffer = st.number_input("เตือนเมื่องบออกภายใน (วัน)", min_value=0, max_value=45, value=int(s.earnings_buffer), step=1,
        help="ถ้างบจะออกภายในจำนวนวันนี้ สถานะจะเปลี่ยนเป็น 'ระวังงบ' เพราะราคาอาจกระโดดข้ามคัดลอส "
             "แนะนำให้ตั้งเท่ากับระยะที่ถือจริง (ประมาณ 21 วัน)")
    if st.button("บันทึกค่า", width="stretch"):
        s.save()
        st.success("บันทึกแล้ว")
    st.divider()
    if st.button("ดึงราคาใหม่", width="stretch"):
        get_prices.clear()
    st.caption("ราคามาจาก Yahoo Finance เก็บไว้ 1 ชั่วโมง")

watch = E.load_watchlist()
with st.spinner(f"กำลังดึงราคา {len(watch)} ตัว จาก Yahoo Finance..."):
    prices = get_prices(tuple(watch["yahoo"]) + tuple(E.INDEX_NAMES))
res = E.scan(watch, s, prices)
with st.spinner("กำลังหาวันประกาศงบ..."):
    try:
        earn = get_earnings(tuple(watch["yahoo"]))
    except Exception:
        earn = {}
res = E.apply_earnings(res, earn, s)

# ---------------------------------------------------------------- header
st.title("Swing Scanner")
dates = res["date"].dropna() if "date" in res else pd.Series(dtype=str)
st.caption(
    f"เทคนิค: Buy the Pullback in an Uptrend · ข้อมูลล่าสุด {dates.max() if len(dates) else '–'} · "
    f"ดึงข้อมูลเมื่อ {datetime.now():%d/%m/%Y %H:%M}"
)
missing = res[res["status"] == "ข้อมูลไม่พอ"]["symbol"].tolist()
if len(missing) == len(res):
    st.error("ดึงราคาไม่ได้เลย ตรวจสอบอินเทอร์เน็ต แล้วกด \"ดึงราคาใหม่\" ที่แถบซ้าย")
elif missing:
    st.warning("ดึงข้อมูลไม่ได้หรือข้อมูลสั้นเกินไป: " + ", ".join(missing) + " — ตรวจรหัส Yahoo ในแท็บรายชื่อหุ้น")

def render_detail(r, key: str) -> None:
    risk_b = r["position_value"] * (r["entry"] - r["stop"]) / r["entry"] if r["entry"] else float("nan")
    gain = r["position_value"] * 0.5 * (r["target"] / r["entry"] - 1) + r["position_value"] * 0.5 * (r["target2"] / r["entry"] - 1)
    has_bt = bool(r.get("bt_n", 0))
    shares = "" if r.get("shares") != r.get("shares") else f"{r['shares']:,.0f} หุ้น · "
    bt_main = ("ชนะ " + format(r["bt_win"], ".0f") + "%") if has_bt else "–"
    bt_sub = (format(r["bt_n"], ".0f") + " ไม้ · เฉลี่ย " + format(r["bt_avg_r"], "+.2f") + "R · ถือ "
              + format(r["bt_days"], ".0f") + " วัน") if has_bt else "ยังไม่เคยเกิดสัญญาณ"
    cards = f"""
<div class="bento">
  <div class="card dark wide">
    <span class="pill">แผนเทรด · {r['symbol']}</span><span class="pill solid">{r['status']}</span>
    <div class="act">{r['action']}</div>
    <div class="big"><span class="pos">+{fmt(r['target2_pct'],1)}%</span> <span style="opacity:.45">/</span> <span class="neg">{fmt(r['stop_pct'],1)}%</span></div>
    <div class="lab">เป้าขายที่เหลือ / คัดลอส · R:R {fmt(r['rr'])} (ขายครึ่ง/ครึ่ง)</div>
  </div>
  <div class="card"><span class="pill">ซื้อที่</span><div class="mid">{fmt(r['buy_price'])}</div><div class="lab">ราคาล่าสุด {fmt(r['close'])}</div></div>
  <div class="card"><span class="pill">คัดลอส</span><div class="mid neg">{fmt(r['stop'])}</div><div class="lab">{fmt(r['stop_pct'],1)}% · {r['stop_src']}</div></div>
  <div class="card"><span class="pill">ขายครึ่งแรก</span><div class="mid pos">{fmt(r['target'])}</div><div class="lab">+{fmt(r['target_pct'],1)}% · {r['target_src']} · แล้วเลื่อนคัดลอสมาที่ทุน</div></div>
  <div class="card"><span class="pill">ขายที่เหลือ</span><div class="mid pos">{fmt(r['target2'])}</div><div class="lab">+{fmt(r['target2_pct'],1)}% · {r['target2_src']}</div></div>
  <div class="card"><span class="pill">ถือไม่เกิน</span><div class="mid">{r['hold_until']}</div><div class="lab">ไม่ถึงเป้า ขายที่ราคาปิดวันนั้น</div></div>
  <div class="card"><span class="pill">ขนาดไม้</span><div class="mid">{fmt(r['position_value'],0)}</div><div class="lab">{shares}ผิดทาง −{fmt(risk_b,0)} · ถูกทาง +{fmt(gain,0)} บาท</div></div>
  <div class="card dark"><span class="pill">ย้อนหลัง 3 ปี</span><div class="mid">{bt_main}</div><div class="lab">{bt_sub}</div></div>
  <div class="card"><span class="pill">คะแนน</span><div class="mid">{fmt(r.get('score'),0)}<span style="font-size:.9rem;opacity:.6">/100</span></div>
    <div class="lab">RS 3 เดือน {fmt(r.get('rs63'),1)}% · Vol {fmt(r['vol_ratio'],1)}x · ตลาด{r.get('regime','')}</div></div>
</div>"""
    st.markdown(cards, unsafe_allow_html=True)

    mode = st.radio("รูปแบบกราฟ", ["เส้น", "แท่งเทียน"], horizontal=True, key=f"mode_{key}", label_visibility="collapsed")
    df = E.add_indicators(prices[r["yahoo"]]).iloc[-120:]
    PAPER, INK, UP, DOWN, GRID = "#F3F1EA", "#111111", "#4F7F52", "#C2362B", "#E2DFD5"
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    if mode == "เส้น":
        fig.add_scatter(x=df.index, y=df["Close"], name="ราคา", line=dict(color=INK, width=2.6, shape="spline", smoothing=0.6), row=1, col=1)
    else:
        fig.add_candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="ราคา",
                            increasing_line_color=UP, decreasing_line_color=DOWN,
                            increasing_fillcolor=UP, decreasing_fillcolor=DOWN, row=1, col=1)
    for n, col, dash in [("EMA20", "#7A7A7A", "solid"), ("EMA50", "#B0AD9F", "dash")]:
        fig.add_scatter(x=df.index, y=df[n], name=n, line=dict(color=col, width=1.3, dash=dash), row=1, col=1)
    fig.add_vline(x=df.index[-1], line_color=INK, line_width=1)
    fig.add_scatter(x=[df.index[-1]], y=[df["Close"].iloc[-1]], mode="markers", showlegend=False,
                    marker=dict(size=11, color=INK, line=dict(color=PAPER, width=2)), row=1, col=1)
    for y, label, col in [(r["stop"], "คัดลอส", DOWN), (r["buy_price"], "ซื้อ", INK),
                          (r["target"], "ขายครึ่งแรก", UP), (r["target2"], "ขายที่เหลือ", UP)]:
        if y == y:
            fig.add_hline(y=y, line_dash="dot", line_color=col, line_width=1.2, row=1, col=1,
                          annotation_text=f" {label} {fmt(y)} ", annotation_position="top left",
                          annotation_font=dict(color=PAPER, size=11), annotation_bgcolor=col)
    vcol = [UP if c_ >= o_ else INK for c_, o_ in zip(df["Close"], df["Open"])]
    fig.add_bar(x=df.index, y=df["Volume"], marker_color=vcol, marker_line_width=0, name="Volume", row=2, col=1)
    fig.update_layout(height=560, showlegend=False, margin=dict(l=8, r=8, t=8, b=8), bargap=0.35,
                      paper_bgcolor=PAPER, plot_bgcolor=PAPER, xaxis_rangeslider_visible=False,
                      font=dict(family="Poppins, Prompt, sans-serif", color=INK, size=12), hovermode="x unified")
    fig.update_xaxes(showgrid=False, rangebreaks=[dict(bounds=["sat", "mon"])], showline=False, ticks="")
    fig.update_yaxes(gridcolor=GRID, zeroline=False, side="right")
    fig.update_yaxes(showgrid=False, showticklabels=False, row=2, col=1)
    st.plotly_chart(fig, width="stretch", key=f"px_{key}", config={"displayModeBar": False})

    rsi_fig = go.Figure()
    rsi_fig.add_hrect(y0=30, y1=50, fillcolor="#D8E64B", opacity=0.35, line_width=0)
    rsi_fig.add_scatter(x=df.index, y=df["RSI"], line=dict(color=INK, width=2, shape="spline", smoothing=0.6))
    rsi_fig.add_scatter(x=[df.index[-1]], y=[df["RSI"].iloc[-1]], mode="markers", marker=dict(size=9, color=INK))
    rsi_fig.update_layout(height=150, showlegend=False, margin=dict(l=8, r=8, t=26, b=8), yaxis_range=[0, 100],
                          paper_bgcolor=PAPER, plot_bgcolor=PAPER, font=dict(family="Poppins, Prompt, sans-serif", color=INK),
                          title=dict(text=f"RSI {fmt(r['rsi'],0)} · โซนย่อ 30–50", font=dict(size=12), x=0.01, y=0.95))
    rsi_fig.update_xaxes(showgrid=False, rangebreaks=[dict(bounds=["sat", "mon"])])
    rsi_fig.update_yaxes(gridcolor=GRID, side="right", tickvals=[30, 50, 70])
    st.plotly_chart(rsi_fig, width="stretch", key=f"rsi_{key}", config={"displayModeBar": False})

    st.caption(
        f"เงื่อนไข {r['checks']}/3: แนวโน้ม {'✓' if r['trend'] else '–'} · ย่อถึง EMA20 {'✓' if r['pullback'] else '–'} · "
        f"RSI หักหัวขึ้น {'✓' if r['rsi_turn'] else '–'} · ATR {fmt(r['atr'])} ({fmt(r['atr_pct'], 1)}%/วัน) · "
        f"แนวต้าน {fmt(r['resistance'])} · ราคาเข้าสูงสุดที่ยังได้ R:R {s.min_rr:g}: {fmt(r['max_entry'])} · "
        f"งบ: {r.get('earn_date') or '–'} ({r.get('earn_src') or 'ไม่พบ'})")


c = res["status"].value_counts()
_ready = int(c.get("พร้อมเข้า", 0))
_cards = [f'<div class="card dark wide"><span class="pill">วันนี้</span><div class="big">{_ready} ตัวพร้อมเข้า</div>'
          f'<div class="lab">ระวังงบ {int(c.get("ระวังงบ", 0))} · R:R ต่ำ {int(c.get("R:R ต่ำ", 0))} · ใกล้เข้า {int(c.get("ใกล้เข้า", 0))}</div></div>']
for _k in ["ใกล้เข้า", "รอย่อ", "นอกแนวโน้ม"]:
    _cards.append(f'<div class="card"><span class="pill">{_k}</span><div class="big">{int(c.get(_k, 0))}</div></div>')
st.markdown('<div class="bento">' + "".join(_cards) + "</div>", unsafe_allow_html=True)

REGIME_ICON = {"ขาขึ้น": "🟢", "ระวัง": "🟡", "ขาลง": "🔴", "ไม่ทราบ": "⚪"}
reg = res.attrs.get("regimes", {})
used = {E.index_for(y) for y in watch["yahoo"]}
parts = []
for ix in [i for i in E.INDEX_NAMES if i in used]:
    g = reg.get(ix, {})
    if g.get("state") == "ไม่ทราบ":
        parts.append(f"{REGIME_ICON['ไม่ทราบ']} **{g.get('name', ix)}** ไม่มีข้อมูล")
    else:
        parts.append(f"{REGIME_ICON[g['state']]} **{g['name']}** {g['state']} "
                     f"(3 เดือน {g['ret63']:+.1f}% · ขนาดไม้ ×{g['mult']:g})")
st.markdown('<div class="card"><span class="pill solid">ภาวะตลาด</span> ' + " ".join(f'<span class="pill">{p_}</span>' for p_ in parts).replace("**", "") + "</div><br>", unsafe_allow_html=True)
if any(reg.get(ix, {}).get("state") == "ขาลง" for ix in used):
    st.caption("ตลาดขาลงอยู่ใต้ EMA200: สัญญาณซื้อล้มเหลวบ่อยขึ้น ระบบลดขนาดไม้ที่แนะนำเหลือ 25% ของปกติ")

tab_scan, tab_chart, tab_fund, tab_list, tab_help = st.tabs(
    ["สแกน", "กราฟรายตัว", "พื้นฐาน 5 เกณฑ์", "รายชื่อหุ้น", "วิธีอ่าน"])

# ---------------------------------------------------------------- scan table
with tab_scan:
    f1, f2 = st.columns([2, 3])
    mk = f1.radio("ตลาด", ["ทั้งหมด", "TH", "DR"], horizontal=True)
    only = f2.multiselect("สถานะ", list(E.STATUS_ORDER), default=[k for k in E.STATUS_ORDER if k != "ข้อมูลไม่พอ"])
    view = res[res["status"].isin(only)]
    if mk != "ทั้งหมด":
        view = view[view["market"] == mk]

    show_tech = st.toggle("แสดงคอลัมน์เทคนิค (EMA, RSI, RS, Volume, ภาวะตลาด)", value=False)
    ok = lambda b: "✓" if b is True else ("–" if b is False else "")
    cols = {
        "สถานะ": view["status"],
        "หุ้น": view["symbol"],
        "ต้องทำอะไร": view.get("action"),
        "ราคา": view.get("close"),
        "ซื้อที่": view.get("buy_price"),
        "คัดลอส": view.get("stop"),
        "คัดลอส %": view.get("stop_pct"),
        "ขายครึ่งแรก": view.get("target"),
        "ขายครึ่งแรก %": view.get("target_pct"),
        "ขายที่เหลือ": view.get("target2"),
        "ขายที่เหลือ %": view.get("target2_pct"),
        "R:R": view.get("rr"),
        "ถือไม่เกิน": view.get("hold_until"),
        "ลงทุน (บาท)": view.get("position_value"),
        "จำนวนหุ้น": view.get("shares"),
        "ย้อนหลัง ชนะ %": view.get("bt_win"),
        "ย้อนหลัง เฉลี่ย R": view.get("bt_avg_r"),
        "ย้อนหลัง ไม้": view.get("bt_n"),
        "คะแนน": view.get("score"),
        "งบอีก (วัน)": view.get("earn_days"),
    }
    if show_tech:
        cols.update({
            "ตลาด": view["market"],
            "ภาวะตลาด": view.get("regime"),
            "% วันนี้": view.get("chg_pct"),
            "แนวโน้ม": view.get("trend", pd.Series(dtype=object)).map(ok),
            "ย่อ EMA20": view.get("pullback", pd.Series(dtype=object)).map(ok),
            "RSI หักขึ้น": view.get("rsi_turn", pd.Series(dtype=object)).map(ok),
            "RSI": view.get("rsi"),
            "RS 3 เดือน": view.get("rs63"),
            "Vol เทียบเฉลี่ย": view.get("vol_ratio"),
            "วันงบ": view.get("earn_date"),
            "ที่มาวันงบ": view.get("earn_src"),
            "หมายเหตุ": view["note"],
        })
    table = pd.DataFrame(cols)

    def paint(row):
        return [f"background-color: {STATUS_COLOR.get(row['สถานะ'], '')}; color: #14201c" if col == "สถานะ" else "" for col in row.index]

    event = st.dataframe(
        table.style.apply(paint, axis=1).format({
            "ราคา": "{:,.2f}", "ซื้อที่": "{:,.2f}", "คัดลอส": "{:,.2f}", "คัดลอส %": "{:.1f}%",
            "ขายครึ่งแรก": "{:,.2f}", "ขายครึ่งแรก %": "{:+.1f}%", "ขายที่เหลือ": "{:,.2f}", "ขายที่เหลือ %": "{:+.1f}%",
            "R:R": "{:.2f}", "ลงทุน (บาท)": "{:,.0f}", "จำนวนหุ้น": "{:,.0f}",
            "ย้อนหลัง ชนะ %": "{:.0f}%", "ย้อนหลัง เฉลี่ย R": "{:+.2f}", "ย้อนหลัง ไม้": "{:.0f}",
            "คะแนน": "{:.0f}", "งบอีก (วัน)": "{:.0f}", "% วันนี้": "{:+.2f}%", "RSI": "{:.0f}",
            "RS 3 เดือน": "{:+.1f}%", "Vol เทียบเฉลี่ย": "{:.1f}x"}, na_rep="–"),
        width="stretch", hide_index=True, height=min(38 * (len(table) + 1), 900),
        on_select="rerun", selection_mode="single-row", key="scan_tbl")
    st.caption("หุ้น DR: ราคาทั้งหมดเป็นของหุ้นต้นทาง (USD/HKD/CNY) ให้ใช้ช่อง % ไปคิดกับราคา DR ในแอปโบรกเกอร์ · "
               "\"ลงทุน (บาท)\" คือขนาดไม้ที่ถ้าโดนคัดลอสจะเสียเท่ากับความเสี่ยงต่อไม้ (ปรับตามภาวะตลาดแล้ว) · "
               "\"ย้อนหลัง\" คือผลถ้าใช้กฎชุดนี้กับหุ้นตัวนั้นใน 3 ปีที่ผ่านมา ไม้น้อยกว่า 5 ไม้ถือว่ายังสรุปไม่ได้")
    rows = event.selection.rows if event is not None else []
    if rows:
        sym = table.iloc[rows[0]]["หุ้น"]
        st.session_state["picked"] = sym
        r_sel = res[res["symbol"] == sym]
        if len(r_sel) and r_sel.iloc[0]["status"] != "ข้อมูลไม่พอ":
            st.subheader(f"{sym} · {r_sel.iloc[0]['status']}")
            render_detail(r_sel.iloc[0], "inline")
    else:
        st.caption("คลิกแถวในตารางเพื่อดูกราฟและแผนเทรดของหุ้นตัวนั้นด้านล่างนี้")

# ---------------------------------------------------------------- chart
with tab_chart:
    syms = res[res["status"] != "ข้อมูลไม่พอ"]["symbol"].tolist()
    if syms:
        picked = st.session_state.get("picked")
        idx = syms.index(picked) if picked in syms else 0
        pick = st.selectbox("เลือกหุ้น", syms, index=idx)
        render_detail(res[res["symbol"] == pick].iloc[0], "tab")

# ---------------------------------------------------------------- fundamentals
with tab_fund:
    st.markdown("เกณฑ์ 1–4 ดึงอัตโนมัติจาก Yahoo (เก็บไว้ 7 วัน) เกณฑ์ 5 กรอกเองจากเอกสารประกาศงบ "
                "หุ้นไทยมักไม่มีข้อมูลบางช่อง")
    if st.button("โหลด / อัปเดตข้อมูลพื้นฐาน"):
        st.session_state["fund"] = True
    if st.session_state.get("fund") or E.FUND_CACHE.exists():
        with st.spinner("กำลังดึงข้อมูลพื้นฐาน (ครั้งแรกใช้เวลาราว 1 นาที)..."):
            fund = E.fetch_fundamentals(watch["yahoo"].tolist())
        gaps = E.load_manual_gap()
        rows = []
        mark = lambda b: "ผ่าน" if b is True else ("ตก" if b is False else "ไม่มีข้อมูล")
        for _, w in watch.iterrows():
            sc = E.score_fundamentals(fund.get(w["yahoo"], {}), gaps.get(w["symbol"]))
            rows.append({
                "หุ้น": w["symbol"], "ผ่าน": f"{sc['passed']}/{sc['known']}",
                "1 PEG": sc["peg"], "การเติบโตที่ตลาดคาด %": (sc["implied_growth"]),
                "2 Rule of 40": sc["rule40"], "3 FCF/รายได้ %": sc["fcf_margin"],
                "4 เงินสดสุทธิ (ล้าน)": sc["net_cash"] / 1e6 if sc["net_cash"] is not None else None,
                "5 ช่องว่างมาร์จิ้น (จุด)": sc["gap_pts"],
                "ผล 1": mark(sc["c1"]), "ผล 2": mark(sc["c2"]), "ผล 3": mark(sc["c3"]),
                "ผล 4": mark(sc["c4"]), "ผล 5": mark(sc["c5"]),
            })
        fdf = pd.DataFrame(rows)
        st.dataframe(fdf.style.format({
            "1 PEG": "{:.2f}", "การเติบโตที่ตลาดคาด %": "{:.0f}", "2 Rule of 40": "{:.0f}",
            "3 FCF/รายได้ %": "{:.1f}", "4 เงินสดสุทธิ (ล้าน)": "{:,.0f}", "5 ช่องว่างมาร์จิ้น (จุด)": "{:.1f}"},
            na_rep="–"), width="stretch", hide_index=True)
        st.caption("เกณฑ์ผ่าน: PEG < 2 · Rule of 40 ≥ 40 · FCF/รายได้ ≥ 5% · เงินสดมากกว่าหนี้ที่มีดอกเบี้ย · "
                   "ช่องว่างมาร์จิ้นปรับปรุงกับมาตรฐานบัญชี ≤ 10 จุด · หุ้นวัฏจักร (ชิปหน่วยความจำ พลังงาน) ตัวเลขช่วงพีคจะดูดีเกินจริง")

        st.subheader("กรอกเกณฑ์ 5 เอง")
        p = E.BASE / "fundamentals_manual.csv"
        man = pd.read_csv(p) if p.exists() else pd.DataFrame({"symbol": watch["symbol"], "gap_pts": None, "source": ""})
        man = st.data_editor(man, num_rows="dynamic", width="stretch", key="man",
                             column_config={"gap_pts": st.column_config.NumberColumn("ช่องว่าง (จุด)", help="มาร์จิ้นปรับปรุง − มาร์จิ้นตามมาตรฐานบัญชี"),
                                            "source": "ที่มา / ไตรมาส"})
        if st.button("บันทึกเกณฑ์ 5"):
            man.to_csv(p, index=False)
            st.success("บันทึกแล้ว")

# ---------------------------------------------------------------- watchlist editor
with tab_list:
    st.markdown("แก้ไข เพิ่ม หรือลบหุ้นได้ แล้วกดบันทึก · หุ้นไทยใช้รหัสตามด้วย `.BK` · "
                "หุ้นต่างประเทศของ DR ใช้รหัสต้นทาง เช่น `NVDA`, `0700.HK`, `300750.SZ`")
    ed = st.data_editor(watch, num_rows="dynamic", width="stretch", key="wl",
                        column_config={"symbol": "ชื่อย่อ", "yahoo": "รหัส Yahoo",
                                       "market": st.column_config.SelectboxColumn("ตลาด", options=["TH", "DR"]),
                                       "group": "กลุ่ม", "note": "หมายเหตุ"})
    if st.button("บันทึกรายชื่อ"):
        E.save_watchlist(ed)
        get_prices.clear()
        st.success("บันทึกแล้ว กำลังโหลดใหม่...")
        st.rerun()

# ---------------------------------------------------------------- help
with tab_help:
    st.markdown("""
**เงื่อนไข 3 ข้อ**
1. **แนวโน้ม**: ราคาปิด > EMA50 > EMA200
2. **ย่อ EMA20**: ราคาต่ำสุดใน 3 วันล่าสุดลงมาถึงเส้น EMA20 (ห่างไม่เกิน 0.25 ATR) และยังปิดเหนือ EMA50
3. **RSI หักขึ้น**: RSI(14) เคยลงไปช่วง 30–50 ใน 5 วันล่าสุด และวันนี้สูงกว่าเมื่อวาน

**สถานะ**
- **พร้อมเข้า**: ครบ 3 ข้อ และ R:R ถึงขั้นต่ำ
- **ระวังงบ**: เข้าเงื่อนไข แต่จะประกาศงบภายในช่วงที่ตั้งไว้ (ค่าเริ่มต้น 14 วัน) ราคาอาจกระโดดข้าม stop ถ้าจะเข้า ให้ลดขนาดไม้ หรือรอหลังงบออก
- **R:R ต่ำ**: ครบ 3 ข้อ แต่เป้าใกล้เกินไป ให้ตั้งซื้อที่ "ราคาเข้าสูงสุด"
- **ใกล้เข้า**: ผ่าน 2 ข้อ เฝ้าดูพรุ่งนี้
- **รอย่อ**: แนวโน้มดี แต่ราคายังไม่ย่อ
- **นอกแนวโน้ม**: ข้ามไปก่อน

**คะแนน (0–100) ใช้จัดอันดับตัวที่สถานะเดียวกัน**
- 40% **Relative Strength**: ผลตอบแทน 3 เดือน (น้ำหนัก 70%) และ 1 เดือน (30%) เทียบดัชนีของตลาดตัวเอง แล้วจัดอันดับในลิสต์
- 30% **Volume**: วันล่าสุดเทียบค่าเฉลี่ย 20 วัน และสัดส่วน volume วันขึ้นต่อวันลงใน 10 วัน
- 30% **R:R**: เต็มเมื่อ R:R ถึง 3

**ภาวะตลาด** ดูจากดัชนี (SET สำหรับหุ้นไทย, Nasdaq สำหรับหุ้นสหรัฐ, Hang Seng สำหรับ Tencent, CSI 300 สำหรับ CATL)
- ขาขึ้น: ดัชนี > EMA50 > EMA200 · ขนาดไม้ปกติ
- ระวัง: ยังอยู่เหนือ EMA200 แต่ไม่ใช่ขาขึ้นชัด · ขนาดไม้ 50%
- ขาลง: ต่ำกว่า EMA200 · ขนาดไม้ 25%

**แผนการเทรด (คำนวณจากหลายวิธีประกอบกัน)**
- **ซื้อที่**: พร้อมเข้า = ราคาปัจจุบัน ไม่เกิน +1% และไม่เกินราคาที่ยังได้ R:R ขั้นต่ำ · R:R ต่ำ = ราคาที่ควรตั้งซื้อรอ · ใกล้เข้า/รอย่อ = แถวเส้น EMA20
- **คัดลอส**: วางใต้จุดต่ำสุดของการย่อ 10 วัน (เผื่อ 0.2 ATR) ถ้าจุดนั้นใกล้ราคาเกิน 1 ATR จะขยับลงเป็น 1 ATR กันโดนสะบัด ถ้าไกลเกินจะใช้ ATR × ค่าที่ตั้งไว้
- **ขายครึ่งแรก / ขายที่เหลือ**: เลือกจาก 3 วิธี ได้แก่ แนวต้านเดิม, 2R (กำไร 2 เท่าของความเสี่ยง) และกรอบแกว่งตามธรรมชาติในช่วงที่ถือ (ATR × √วันที่ถือ) ใช้เฉพาะเป้าที่ไกลอย่างน้อย 1R จุดใกล้สุดคือขายครึ่งแรก จุดไกลสุดคือขายที่เหลือ แต่ไม่เกินกรอบแกว่ง เพื่อให้เป็นไปได้จริงใน 2–3 สัปดาห์
- **หลังขายครึ่งแรก** เลื่อนคัดลอสของที่เหลือมาที่ราคาทุน ไม้นี้จะไม่ขาดทุนแล้ว
- **ถือไม่เกิน**: ครบกำหนดแล้วยังไม่ถึงเป้า ให้ขายที่ราคาปิดวันนั้น
- **ย้อนหลัง 3 ปี**: นำกฎทั้งหมดนี้ไปทดสอบกับราคาจริงย้อนหลังของหุ้นตัวนั้น (ซื้อที่ราคาเปิดวันถัดจากสัญญาณ, วันไหนแตะทั้งคัดลอสและเป้า ถือว่าโดนคัดลอสก่อน) "เฉลี่ย R" เป็นบวกแปลว่ากฎนี้เคยทำเงินกับหุ้นตัวนั้น ถ้าน้อยกว่า 5 ไม้ ยังเชื่อถือไม่ได้

ข้อมูลจาก Yahoo Finance ล่าช้าได้ และบางครั้งดึงไม่สำเร็จ ผลสแกนเป็นเครื่องมือช่วยตามกฎที่ตั้งไว้ ไม่ใช่คำแนะนำการลงทุน
""")
