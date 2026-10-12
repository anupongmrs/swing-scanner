"""Swing Scanner — Streamlit app. Run:  streamlit run app.py"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import engine as E

st.set_page_config(page_title="Swing Scanner", page_icon="📈", layout="wide")

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
    "พร้อมเข้า": "#d6f2df", "R:R ต่ำ": "#fbeccc", "ใกล้เข้า": "#fff5d6",
    "ระวังงบ": "#f6d9ef", "รอย่อ": "#eef1f4", "นอกแนวโน้ม": "#f8dcd8", "ข้อมูลไม่พอ": "#eeeeee",
}

# ---------------------------------------------------------------- sidebar
s = E.Settings.load()
with st.sidebar:
    st.header("ตั้งค่า")
    s.portfolio = st.number_input("ขนาดพอร์ต (บาท)", min_value=10_000.0, value=float(s.portfolio), step=50_000.0, format="%.0f")
    s.risk_pct = st.number_input("เสี่ยงต่อไม้ (%)", min_value=0.1, max_value=5.0, value=float(s.risk_pct), step=0.1)
    s.atr_mult = st.number_input("Stop = ATR ×", min_value=0.5, max_value=4.0, value=float(s.atr_mult), step=0.25)
    s.min_rr = st.number_input("R:R ขั้นต่ำ", min_value=1.0, max_value=5.0, value=float(s.min_rr), step=0.5)
    s.resistance_lookback = st.number_input("หาแนวต้านย้อนหลัง (วัน)", min_value=20, max_value=250, value=int(s.resistance_lookback), step=10)
    s.earnings_buffer = st.number_input("เตือนเมื่องบออกภายใน (วัน)", min_value=0, max_value=45, value=int(s.earnings_buffer), step=1)
    if st.button("บันทึกค่า", width="stretch"):
        s.save()
        st.success("บันทึกแล้ว")
    st.divider()
    if st.button("ดึงราคาใหม่", width="stretch"):
        get_prices.clear()
    st.caption(f"ความเสี่ยงต่อไม้: {fmt(s.portfolio * s.risk_pct / 100, 0)} บาท")

watch = E.load_watchlist()
with st.spinner(f"กำลังดึงราคา {len(watch)} ตัว จาก Yahoo Finance..."):
    prices = get_prices(tuple(watch["yahoo"]))
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

c = res["status"].value_counts()
m = st.columns(6)
for i, k in enumerate(["พร้อมเข้า", "ระวังงบ", "ใกล้เข้า", "R:R ต่ำ", "รอย่อ", "นอกแนวโน้ม"]):
    m[i].metric(k, int(c.get(k, 0)))

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

    ok = lambda b: "✓" if b is True else ("–" if b is False else "")
    table = pd.DataFrame({
        "สถานะ": view["status"],
        "หุ้น": view["symbol"],
        "ตลาด": view["market"],
        "ราคา": view.get("close"),
        "% วันนี้": view.get("chg_pct"),
        "แนวโน้ม": view.get("trend", pd.Series(dtype=object)).map(ok),
        "ย่อ EMA20": view.get("pullback", pd.Series(dtype=object)).map(ok),
        "RSI หักขึ้น": view.get("rsi_turn", pd.Series(dtype=object)).map(ok),
        "RSI": view.get("rsi"),
        "Stop": view.get("stop"),
        "Stop %": view.get("stop_pct"),
        "เป้า": view.get("target"),
        "เป้า %": view.get("target_pct"),
        "R:R": view.get("rr"),
        "ราคาเข้าสูงสุด": view.get("max_entry"),
        "ลงทุน (บาท)": view.get("position_value"),
        "จำนวนหุ้น": view.get("shares"),
        "งบอีก (วัน)": view.get("earn_days"),
        "วันงบ": view.get("earn_date"),
        "ที่มาวันงบ": view.get("earn_src"),
        "หมายเหตุ": view["note"],
    })

    def paint(row):
        return [f"background-color: {STATUS_COLOR.get(row['สถานะ'], '')}; color: #14201c" if col == "สถานะ" else "" for col in row.index]

    st.dataframe(
        table.style.apply(paint, axis=1).format({
            "ราคา": "{:,.2f}", "% วันนี้": "{:+.2f}%", "RSI": "{:.0f}", "Stop": "{:,.2f}", "Stop %": "{:.1f}%",
            "เป้า": "{:,.2f}", "เป้า %": "{:+.1f}%", "R:R": "{:.2f}", "ราคาเข้าสูงสุด": "{:,.2f}",
            "ลงทุน (บาท)": "{:,.0f}", "จำนวนหุ้น": "{:,.0f}", "งบอีก (วัน)": "{:.0f}"}, na_rep="–"),
        width="stretch", hide_index=True, height=min(38 * (len(table) + 1), 900))
    st.caption("หุ้น DR: ราคา stop และเป้าเป็นของหุ้นต้นทาง (USD/HKD/CNY) ให้ใช้ % ไปคำนวณกับราคา DR ในแอปโบรกเกอร์ · "
               "\"ลงทุน (บาท)\" คือขนาดไม้ที่ทำให้ถ้าโดน stop จะขาดทุนเท่ากับความเสี่ยงต่อไม้พอดี · "
               "วันงบ \"ประมาณ (กฎ SET)\" คือช่วงสุดท้ายก่อนครบกำหนดส่งงบ ไม่ใช่วันประกาศจริง")

# ---------------------------------------------------------------- chart
with tab_chart:
    syms = res[res["status"] != "ข้อมูลไม่พอ"]["symbol"].tolist()
    if syms:
        pick = st.selectbox("เลือกหุ้น", syms)
        r = res[res["symbol"] == pick].iloc[0]
        df = E.add_indicators(prices[r["yahoo"]]).iloc[-160:]
        fig = go.Figure()
        fig.add_candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                            name="ราคา", increasing_line_color="#15804a", decreasing_line_color="#c2362b")
        for n, col in [("EMA20", "#2f7fd8"), ("EMA50", "#d98a1c"), ("EMA200", "#7a4fc9")]:
            fig.add_scatter(x=df.index, y=df[n], name=n, line=dict(width=1.4, color=col))
        for y, label, col in [(r["stop"], "Stop", "#c2362b"), (r["entry"], "ซื้อ", "#555"),
                              (r["target"], "เป้า", "#15804a")]:
            fig.add_hline(y=y, line_dash="dot", line_color=col, annotation_text=f"{label} {fmt(y)}",
                          annotation_position="right")
        fig.update_layout(height=520, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10),
                          legend=dict(orientation="h", y=1.04))
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        st.plotly_chart(fig, width="stretch")

        rsi_fig = go.Figure()
        rsi_fig.add_scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="#0b6e5f"))
        for y in (30, 50, 70):
            rsi_fig.add_hline(y=y, line_dash="dot", line_color="#999")
        rsi_fig.update_layout(height=180, margin=dict(l=10, r=10, t=10, b=10), yaxis_range=[0, 100])
        rsi_fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        st.plotly_chart(rsi_fig, width="stretch")

        k = st.columns(4)
        k[0].metric("สถานะ", r["status"], f"{r['checks']}/3 เงื่อนไข")
        k[1].metric("Stop", fmt(r["stop"]), f"{fmt(r['stop_pct'], 1)}%")
        k[2].metric("เป้า", fmt(r["target"]), f"+{fmt(r['target_pct'], 1)}% ({r['target_src']})")
        k[3].metric("R:R", fmt(r["rr"]), f"ATR {fmt(r['atr'])} ({fmt(r['atr_pct'], 1)}%)")
        st.markdown(
            f"- เลื่อน stop มาที่ทุนเมื่อราคาถึง **{fmt(r['entry'] + (r['entry'] - r['stop']))}** (กำไร 1R)\n"
            f"- เป้า 2R: **{fmt(r['target_2r'])}** · แนวรับ 20 วัน: **{fmt(r['support20'])}**\n"
            f"- ราคาเข้าสูงสุดที่ยังได้ R:R {s.min_rr}: **{fmt(r['max_entry'])}**\n"
            f"- Volume วันล่าสุด = {fmt(r['vol_ratio'], 1)} เท่าของค่าเฉลี่ย 20 วัน\n"
            f"- วันประกาศงบ: **{r.get('earn_date') or '–'}** ({r.get('earn_src') or 'ไม่พบ'})")

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

**แผนการเทรด**
- Stop = ราคาซื้อ − (ตัวคูณ × ATR14)
- เป้า = จุดสูงสุดของช่วงย้อนหลัง (แนวต้าน) ถ้าราคาอยู่ใกล้จุดสูงสุดแล้ว ใช้ 2R แทน
- ถึง 1R เลื่อน stop มาที่ทุน · ถึงแนวต้าน ขายครึ่งหนึ่ง ที่เหลือใช้ EMA20 เป็น trailing stop
- ไม่ถือข้ามวันประกาศงบ ถ้ายังไม่มีกำไรอย่างน้อย 1R · ครบ 4 สัปดาห์ไม่ถึงเป้า ให้ออก

ข้อมูลจาก Yahoo Finance ล่าช้าได้ และบางครั้งดึงไม่สำเร็จ ผลสแกนเป็นเครื่องมือช่วยตามกฎที่ตั้งไว้ ไม่ใช่คำแนะนำการลงทุน
""")
