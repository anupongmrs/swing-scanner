"""Run the scan once and print a summary; post to Slack when SLACK_WEBHOOK_URL is set.

    python notify.py            # print only
    set SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...   (Windows)
    python notify.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

import engine as E


def summary(res, s) -> str:
    def line(r):
        bt = f" | ย้อนหลังชนะ {r['bt_win']:.0f}% ({r['bt_n']:.0f} ไม้)" if r.get("bt_n", 0) else ""
        earn = (f" | งบอีก {r['earn_days']:.0f} วัน" if r.get("earn_days") == r.get("earn_days")
                and r.get("earn_days") is not None and r.get("earn_days") <= 30 else "")
        return (f"*{r['symbol']}* {r['action']}\n"
                f"    ซื้อ {r['buy_price']:,.2f} | คัดลอส {r['stop']:,.2f} ({r['stop_pct']:.1f}%) | "
                f"ขายครึ่งแรก {r['target']:,.2f} (+{r['target_pct']:.1f}%) | ขายที่เหลือ {r['target2']:,.2f} "
                f"(+{r['target2_pct']:.1f}%) | R:R {r['rr']:.2f} | ถือถึง {r['hold_until']}{bt}{earn}")
    date = res["date"].dropna().max() if "date" in res else "-"
    out = [f"Swing Scanner · ข้อมูลวันที่ {date}"]
    reg = res.attrs.get("regimes", {})
    rl = [f"{g['name']} {g['state']}" + (f" (ไม้ ×{g['mult']:g})" if g.get("mult", 1) < 1 else "")
          for g in reg.values() if g.get("state") != "ไม่ทราบ"]
    if rl:
        out.append("ภาวะตลาด: " + " · ".join(rl))
    full = os.environ.get("FULL_REPORT") == "1" or "--full" in sys.argv
    statuses = ["พร้อมเข้า", "ระวังงบ", "R:R ต่ำ", "ใกล้เข้า"] + (["รอย่อ", "นอกแนวโน้ม"] if full else [])
    if full:
        out[0] += " · รายงานประจำสัปดาห์"
    for status in statuses:
        part = res[res["status"] == status]
        if len(part):
            out.append(f"\n{status} ({len(part)})")
            out += [line(r) if status in ("พร้อมเข้า", "ระวังงบ", "R:R ต่ำ", "ใกล้เข้า") else f"{r['symbol']} {r['close']:,.2f} RSI {r['rsi']:.0f}" for _, r in part.iterrows()]
    if not any(len(res[res["status"] == st_]) for st_ in statuses):
        out.append("วันนี้ยังไม่มีตัวที่เข้าเงื่อนไข")
    miss = res[res["status"] == "ข้อมูลไม่พอ"]["symbol"].tolist()
    if miss:
        out.append("\nดึงข้อมูลไม่ได้: " + ", ".join(miss))
    return "\n".join(out)


def main() -> int:
    s = E.Settings.load()
    watch = E.load_watchlist()
    res = E.scan(watch, s)
    try:
        res = E.apply_earnings(res, E.fetch_earnings(watch), s)
    except Exception as e:
        print("หาวันงบไม่ได้:", e)
    text = summary(res, s)
    print(text)
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if url:
        req = urllib.request.Request(url, data=json.dumps({"text": text}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        print("ส่ง Slack แล้ว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
