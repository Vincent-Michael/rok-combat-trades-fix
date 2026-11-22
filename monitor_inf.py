#!/usr/bin/env python3
"""ROK Battles Combat Lab infantry monitor; Python 3.10+, standard library only."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from combat_source import fetch_snapshot, save_run_status, status_label, report_status_summary

# Manual data-refresh trigger: retain 7d/Open field setting.
SCENARIO_KEY = "7d/openField"
SCENARIO_LABEL = "7 days / Open field"
MAX_FRESH_AGE_HOURS = 8  # site-generation age, not retrieval success
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "trades_inf.json"
REPORT = ROOT / "REPORT_INF.md"

PAIRS = [
    ("Yi Do / Bai Qi", 621, 545),
    ("Yi Do / Ivar", 621, 596),
    ("Yi Do / Liu Che", 621, 185),
    ("Sun Tzu / Yi Do", 595, 621),
    ("Sun Tzu / Ivar", 595, 596),
    ("Bai Qi / Liu Che", 545, 185),
    ("Sun Tzu / Bai Qi", 595, 545),
    ("Bai Qi / Yi Do", 545, 621),
    ("Sun Tzu / Liu Che", 595, 185),
    ("Sun Tzu / Vercingetorix", 595, 616),
    ("Bai Qi / Vercingetorix", 545, 616),
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def timestamp(ms):
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid numeric value: {value!r}")
    return value


def rate(numerator, duration_ms):
    return round(numerator / (duration_ms / 1000), 3) if duration_ms > 0 else None


def parse_payload(payload, primary, secondary):
    pair = payload.get("pairing") or {}
    if (int(pair.get("primaryCommanderId", -1)), int(pair.get("secondaryCommanderId", -1))) != (primary, secondary):
        raise ValueError("API response is for a DIFFERENT commander pairing")
    generation_ms = number(payload["generatedAtMs"])
    if generation_ms <= 0:
        raise ValueError("Invalid generatedAtMs")
    rows = [r for r in payload.get("summaries", []) if isinstance(r, list) and len(r) >= 12 and r[:2] == [3, 1]]
    if len(rows) != 1:
        raise ValueError("Missing/ambiguous summary for 7d / Open field scenario")
    r = rows[0]
    battles, unique, gained, lost, sev_inf, sev_taken, rate_ms, dmg, heal = (
        number(r[2]), number(r[3]), number(r[4]), number(r[5]),
        number(r[6]), number(r[7]), number(r[9]), number(r[10]), number(r[11])
    )
    if battles < 0 or gained < 0 or lost < 0:
        raise ValueError("Negative values in summary")
    trade = round(gained / lost * 100, 4) if lost > 0 else (100.0 if gained == 0 else None)
    return {
        "generatedAtMs": generation_ms,
        "generatedAtUTC": timestamp(generation_ms),
        "primary": primary,
        "secondary": secondary,
        "battles": int(battles),
        "uniqueGovernors": int(unique),
        "killPointsGained": round(gained),
        "killPointsLost": round(lost),
        "tradePercent": trade,
        "dps": rate(dmg, rate_ms),
        "sps": rate(sev_inf, rate_ms),
        "tps": rate(sev_taken, rate_ms),
        "hps": rate(heal, rate_ms),
    }


def site_age_hours(generated_at_ms):
    """Age of the site's generatedAtMs; successful retrieval does not reset it."""
    return max(0.0, (time.time() * 1000 - generated_at_ms) / 3_600_000)


def fetch(primary, secondary, previous_generated_ms=None):
    """Fetch only verified 7d/Open Field data using shared retry/freshness logic."""
    return fetch_snapshot(primary, secondary, previous_generated_ms, parse_payload)


def fmt_num(value, digits=0):
    return "N/A" if value is None else f"{value:,.{digits}f}"


def build_report(store, results, now):
    def key(pair):
        return f"{pair[1]}-{pair[2]}"
    def ranking(pair):
        snap = results[key(pair)]["snapshot"]
        trade = snap.get("tradePercent") if snap else None
        return (trade is None, -(trade if trade is not None else 0))
    ranked_pairs = sorted(PAIRS, key=ranking)
    verified = sum(v["ok"] for v in results.values())
    fresh = sum(bool(v["ok"] and v["snapshot"] and site_age_hours(v["snapshot"]["generatedAtMs"]) <= MAX_FRESH_AGE_HOURS) for v in results.values())
    stale_count = sum(bool(v["snapshot"] and site_age_hours(v["snapshot"]["generatedAtMs"]) > MAX_FRESH_AGE_HOURS) for v in results.values())
    stamps = sorted(set(v["snapshot"]["generatedAtUTC"] for v in results.values() if v["snapshot"]))
    site_stamp = ", ".join(stamps) if stamps else "N/A"
    lines = [
        "# RoK Combat Lab — Infantry Trade Report", "",
        f"**Workflow checked UTC:** {now}  ",
        f"**API site-generated UTC:** {site_stamp}  ",
        f"**Successful monitor checks:** {verified}/{len(PAIRS)}  ",
        f"**Source verification:** {report_status_summary(results)}  ",
        f"**Fresh site snapshots (age <= {MAX_FRESH_AGE_HOURS}h):** {fresh}/{len(PAIRS)}  ",
        f"**Stale site snapshots:** {stale_count}/{len(PAIRS)}  ",
        f"**Scenario:** 7 Days / Open Field ([3,1]); rolling seven days, independent of eight-hour monitoring.",
        "",
        "**Data age:** Successful API retrieval does NOT imply newly generated statistics. Snapshots older than 8 hours are marked STALE, even if retrievals succeed. Cache bypass cannot force an upstream data refresh.",
        "",
        "## Trade Efficiency Ranking", "",
        "![Trade efficiency ranking](charts/infantry.svg)", "",
        "## Trade Ranking & Battle Reports", "",
        "| Rank | Commander Pairing | Trade % | Δ pp | Reports | Site-generated UTC | Source status |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for rank,(name,p,s) in enumerate(ranked_pairs,1):
        r = results[f"{p}-{s}"]
        v,old = r["snapshot"],r.get("previous")
        trade = f'{v["tradePercent"]:.2f}%' if v and v.get("tradePercent") is not None else "N/A"
        delta = f'{v["tradePercent"]-old["tradePercent"]:+.2f}' if v and old and v.get("tradePercent") is not None and old.get("tradePercent") is not None else "N/A"
        battles = fmt_num(v.get("battles")) if v else "N/A"
        url = f"https://rokbattles.com/combat-lab?primary={p}&secondary={s}"
        lines.append(f"| {rank} | [{name}]({url}) | {trade} | {delta} | {battles} | {v.get('generatedAtUTC', 'N/A') if v else 'N/A'} | {status_label(r['status'], v)} |")
    stale_retained = [name for name,p,s in ranked_pairs if results[f"{p}-{s}"]["snapshot"] and not results[f"{p}-{s}"]["ok"]]
    unknown = [name for name,p,s in ranked_pairs if not results[f"{p}-{s}"]["snapshot"]]
    lines += ["",f"Site-generated: {site_stamp} · Retrieved: {verified}/{len(PAIRS)} · Fresh site snapshots: {fresh}/{len(PAIRS)} · Stale site snapshots: {stale_count}/{len(PAIRS)} · Retained after errors: {len(stale_retained)} · Unavailable: {len(unknown)}.", "",
              "## Detailed Combat Statistics", "", "KP Gained and KP Lost are in millions (M). DPS, SPS and TPS are per-second rates.", "",
              "| Commander Pairing | KP Gained | KP Lost | DPS | SPS | TPS |", "|---|---:|---:|---:|---:|---:|"]
    for name,p,s in ranked_pairs:
        v=results[f"{p}-{s}"]["snapshot"]
        def metric(field):
            if not v or v.get(field) is None: return "N/A"
            if field in ("killPointsGained","killPointsLost"): return f'{v[field]/1000000:,.3f}M'
            return f'{v[field]:.3f}'
        lines.append(f"| {name} | " + " | ".join(metric(f) for f in ("killPointsGained","killPointsLost","dps","sps","tps")) + " |")
    valid=[(name,p,s,results[f"{p}-{s}"]["snapshot"]) for name,p,s in ranked_pairs if results[f"{p}-{s}"]["snapshot"] and results[f"{p}-{s}"]["snapshot"].get("tradePercent") is not None]
    lines += ["","## Key Findings",""]
    if valid:
        best=valid[0]; worst=valid[-1]
        largest=max(valid,key=lambda x:x[3].get("battles",0))
        smallest=min(valid,key=lambda x:x[3].get("battles",0))
        lines.append(f'**Best trade:** {best[0]} at {best[3]["tradePercent"]:.2f}%. **Worst trade:** {worst[0]} at {worst[3]["tradePercent"]:.2f}%.')
        lines.append(f'**Largest dataset:** {largest[0]} ({largest[3]["battles"]:,} reports). **Smallest dataset:** {smallest[0]} ({smallest[3]["battles"]:,} reports; interpret cautiously).')
    else:
        lines.append("No verified 7-day/Open Field trade values are currently available.")
    changes=[(name,v,results[f"{p}-{s}"].get("previous")) for name,p,s,v in valid if results[f"{p}-{s}"].get("previous") and v.get("tradePercent") is not None]
    if changes:
        lines.append("**Distinct-snapshot changes:** " + "; ".join(f'{name} {v["tradePercent"]-old["tradePercent"]:+.2f} pp' for name,v,old in changes if old.get("tradePercent") is not None) + ".")
    else:
        lines.append("**Distinct-snapshot changes:** N/A (no preceding distinct valid 7-day/Open Field snapshot).")
    if stale_retained: lines.append("**Old verified snapshots retained after failed requests:** " + ", ".join(stale_retained) + ".")
    if stale_count: lines.append(f"**Source age warning:** {stale_count}/{len(PAIRS)} site-generated snapshots exceed {MAX_FRESH_AGE_HOURS} hours. These are historical 7-day rolling windows, NOT current live statistics.")
    if unknown: lines.append("**Unverified / N/A:** " + ", ".join(unknown) + ".")
    errors=[f'{name}: {results[f"{p}-{s}"]["error"]}' for name,p,s in ranked_pairs if results[f"{p}-{s}"]["error"]]
    if errors: lines.append("**Retrieval failures:** " + "; ".join(errors) + ".")
    lines += ["","**Source / monitor status:** [trades_inf.json](data/trades_inf.json) · [REPORT_INF.md](REPORT_INF.md) · "
              + f"Workflow checked: {now} · API generated: {site_stamp} · "
              + f"Retrievals: {verified}/{len(PAIRS)} · Fresh site data: {fresh}/{len(PAIRS)} · Stale source: {stale_count}/{len(PAIRS)} · Historical data preserved; no 1-year baselines.",
              ""]
    return "\n".join(lines)


def build_svg(results):
    from html import escape
    ranked=sorted(PAIRS,key=lambda p:(results[f"{p[1]}-{p[2]}"]["snapshot"] is None or results[f"{p[1]}-{p[2]}"]["snapshot"].get("tradePercent") is None,
                                   -(results[f"{p[1]}-{p[2]}"]["snapshot"] or {}).get("tradePercent",0) if (results[f"{p[1]}-{p[2]}"]["snapshot"] or {}).get("tradePercent") is not None else 0))
    trades=[r["snapshot"].get("tradePercent") for r in results.values() if r["snapshot"] and r["snapshot"].get("tradePercent") is not None]
    limit=max(170,10*(int(max(trades)/10)+1)) if trades else 170
    x0, bw, y0, step=328,660,90,52
    yaxis=y0+len(PAIRS)*step
    h=yaxis+77
    line=x0+bw*100/limit
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {h}" role="img" aria-label="Infantry trade efficiency ranking">',
         f'<rect x="1" y="1" width="1198" height="{h-2}" rx="16" fill="#172234" stroke="#344258" stroke-width="2"/>',
         '<circle cx="26" cy="31" r="7" fill="#22c55e"/><text x="43" y="37" fill="#22c55e" font-family="Arial,sans-serif" font-size="18" font-weight="600">Positive (&gt;100%)</text>',
         '<circle cx="280" cy="31" r="7" fill="#ef4444"/><text x="297" y="37" fill="#ef4444" font-family="Arial,sans-serif" font-size="18" font-weight="600">Negative (&lt;100%)</text>']
    for i,(name,p,s) in enumerate(ranked):
        y=y0+i*step
        v=results[f"{p}-{s}"]["snapshot"]
        trade=v.get("tradePercent") if v else None
        col="#22c55e" if trade is not None and trade>100 else "#ef4444" if trade is not None and trade<100 else "#94a3b8"
        svg += [f'<rect x="{x0}" y="{y-25}" width="{bw}" height="32" rx="5" fill="#28374d"/>']
        if trade is not None:
            svg.append(f'<rect x="{x0}" y="{y-25}" width="{max(0,min(bw,bw*trade/limit)):.2f}" height="32" rx="5" fill="{col}"/>')
        svg += [f'<text x="20" y="{y-2}" fill="#9baec9" font-family="Arial,sans-serif" font-size="18">{i+1}</text>',
                f'<text x="53" y="{y-2}" fill="#f1f5f9" font-family="Arial,sans-serif" font-size="19">{escape(name)}</text>',
                f'<text x="1172" y="{y-2}" text-anchor="end" fill="{col}" font-family="Arial,sans-serif" font-weight="bold" font-size="22">{f"{trade:.2f}%" if trade is not None else "N/A"}</text>']
    svg.append(f'<line x1="{line:.2f}" y1="53" x2="{line:.2f}" y2="{yaxis-29}" stroke="#e2e8f0" stroke-width="2" stroke-dasharray="6 7"/>')
    svg += [f'<line x1="{x0}" y1="{yaxis-31}" x2="{x0+bw}" y2="{yaxis-31}" stroke="#51617a"/>',
            f'<text x="{x0}" y="{yaxis-7}" text-anchor="middle" fill="#b4c3d8" font-family="Arial" font-size="18">0%</text>',
            f'<text x="{line:.2f}" y="{yaxis-7}" text-anchor="middle" fill="#f1f5f9" font-family="Arial" font-size="18">100%</text>',
            f'<text x="{x0+bw}" y="{yaxis-7}" text-anchor="middle" fill="#b4c3d8" font-family="Arial" font-size="18">{limit}%</text>',
            f'<text x="600" y="{yaxis+37}" text-anchor="middle" fill="#cbd5e1" font-family="Arial" font-size="16">Dashed line = 100% break-even · Latest verified site snapshot</text>',
            '</svg>']
    return "\n".join(svg)+"\n"


def main():
    store = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {"snapshots": {}, "history": []}
    store.setdefault("snapshots", {})
    store.setdefault("history", [])
    now = utc_now()
    # Never compare a previous reporting window with 7-day Open field values.
    # Array indices [3, 1] select 7d/Open field (not 1y/Open field).
    if store.get("scenario") != SCENARIO_KEY:
        if store.get("snapshots") or store.get("history"):
            store.setdefault("archivedLegacyData", []).append({
                "scenario": store.get("scenario") or "older/unknown",
                "archivedAtUTC": now,
                "snapshots": store.get("snapshots", {}),
                "history": store.get("history", []),
            })
        store["snapshots"] = {}
        store["history"] = []
        store["scenario"] = SCENARIO_KEY
    results = {}
    for name, p, s, *_ in PAIRS:
        key = f"{p}-{s}"
        prior = store["snapshots"].get(key)
        if not isinstance(prior, dict) or (prior.get("primary"), prior.get("secondary")) != (p, s):
            prior = None  # Never reuse another pairing's snapshot.
        data, status, err = fetch(p, s, prior.get("generatedAtMs") if prior else None)
        if data:
            data["checkedAtUTC"] = now
            if prior is None or data["generatedAtMs"] != prior["generatedAtMs"]:
                store["history"].append({"pairing": name, **data})
            store["snapshots"][key] = data
        current = data or prior
        candidates = [h for h in store["history"] if h.get("primary") == p and h.get("secondary") == s and
                      current and isinstance(h.get("generatedAtMs"), (int,float)) and h["generatedAtMs"] < current["generatedAtMs"]]
        previous = max(candidates, key=lambda h: h["generatedAtMs"]) if candidates else None
        if prior and current and prior.get("generatedAtMs",0) < current["generatedAtMs"] and (previous is None or prior["generatedAtMs"] > previous["generatedAtMs"]):
            previous = prior
        results[key] = {"ok": bool(data), "snapshot": current, "previous": previous, "error": err, "status": status}
        print(f"{name}: {status.upper()} | " +
               (f"Trade={data['tradePercent']}% | Site-generated={data['generatedAtUTC']}" if data else f"retrieval failed: {err}"))
        # Avoid bursts against a shared resource.
        time.sleep(1)
    store["lastCheckedAtUTC"] = now
    save_run_status(store, results)
    store["history"] = store["history"][-500:]
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT.write_text(build_report(store, results, now), encoding="utf-8")
    chart_path = ROOT / "charts" / "infantry.svg"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_text(build_svg(results), encoding="utf-8")
    print(f"Saved {REPORT} and {DATA}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
