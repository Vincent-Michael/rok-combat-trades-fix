#!/usr/bin/env python3
"""ROK Battles Combat Lab cavalry monitor; Python 3.10+, standard library only."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Cavalry-only snapshot history. Retain 7d/Open field setting.
SCENARIO_KEY = "7d/openField"
SCENARIO_LABEL = "7 days / Open field"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "trades_cav.json"
REPORT = ROOT / "REPORT_CAV.md"

PAIRS = [
    ("Ivan IV / William Marshal", 619, 620),
    ("Ivan IV / Achilles", 619, 575),
    ("Arthur Pendragon / Ivan IV", 540, 619),
    ("Arthur Pendragon / Achilles", 540, 575),
    ("Arthur Pendragon / Gang Gamchan", 540, 579),
    ("Arthur Pendragon / Hector", 540, 576),
    ("Achilles / Gang Gamchan", 575, 579),
    ("Achilles / Vercingetorix", 575, 616),
    ("Achilles / William Marshal", 575, 620),
    ("William Marshal / Achilles", 620, 575),
    ("William Marshal / Ivan IV", 620, 619),
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


def fetch(primary, secondary, previous_generated_ms=None):
    """Retry old API snapshots using no-cache headers and cache-busting URLs."""
    from urllib.parse import urlencode
    base = "https://rokbattles.com/proxy/v2/global/combat-lab"
    errors = []
    last_valid = None
    for attempt in range(3):
        query = {"primary": primary, "secondary": secondary}
        if attempt:
            query["_cb"] = str(int(time.time() * 1000))
        url = base + "?" + urlencode(query)
        try:
            req = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; RoKCombatTradesMonitor/2.0)",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
            })
            with urlopen(req, timeout=25) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                payload = json.loads(response.read(12 * 1024 * 1024))
            snapshot = parse_payload(payload, primary, secondary)
            if previous_generated_ms is None or snapshot["generatedAtMs"] > previous_generated_ms:
                return snapshot, None
            if snapshot["generatedAtMs"] == previous_generated_ms:
                last_valid = snapshot
                errors.append(f"attempt {attempt+1}: site snapshot unchanged")
            else:
                errors.append(f"attempt {attempt+1}: site snapshot older than stored")
        except Exception as exc:
            errors.append(f"attempt {attempt+1}: {type(exc).__name__} {str(exc)[:160]}")
        if attempt < 2:
            time.sleep(2)
    if last_valid is not None:
        return last_valid, "Site snapshot unchanged after 3 attempts (cache bypass)"
    return None, "; ".join(errors)


def fmt_num(value, digits=0):
    return "N/A" if value is None else f"{value:,.{digits}f}"


def build_report(store, results, now):
    # Rank by latest 7-day Open field trade; unknown values remain last.
    def sort_key(pair):
        key = f"{pair[1]}-{pair[2]}"
        snapshot = results[key]["snapshot"]
        trade = snapshot.get("tradePercent") if snapshot else None
        return (trade is None, -(trade if trade is not None else 0))

    ranked_pairs = sorted(PAIRS, key=sort_key)
    lines = [
        "# RoK Combat Lab — Cavalry Trade Report",
        "",
        f"**Checked:** {now}  ",
        f"**Scenario:** {SCENARIO_LABEL} (7-day selected time window)  ",
        f"**Live retrieval:** {sum(v['ok'] for v in results.values())}/{len(PAIRS)} successful",
        "",
        "| Rank | Commander pairing | Trade % | Δ Trade (pp) | Battle reports | Δ Reports | Site timestamp (UTC) | Status |",
        "|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for rank, (name, p, s) in enumerate(ranked_pairs, start=1):
        k = f"{p}-{s}"
        result = results[k]
        current = result["snapshot"]
        prior = result.get("previous")
        url = f"https://rokbattles.com/combat-lab?primary={p}&secondary={s}"
        if current:
            trade = fmt_num(current.get("tradePercent"), 2) + "%" if current.get("tradePercent") is not None else "N/A"
            battles = fmt_num(current.get("battles"))
            trade_delta = (fmt_num(current["tradePercent"]-prior["tradePercent"],2) if prior and current.get("tradePercent") is not None and prior.get("tradePercent") is not None else "N/A")
            count_delta = fmt_num(current["battles"]-prior["battles"]) if prior else "N/A"
            stamp = current["generatedAtUTC"]
            status = ("Site snapshot unchanged" if result["ok"] and result["error"] else "Verified new site snapshot" if result["ok"] else "Old verified snapshot")
        else:
            trade, trade_delta, battles, count_delta, stamp, status = "N/A", "N/A", "N/A", "N/A", "N/A", "Not yet verified"
        lines.append(f"| {rank} | [{name}]({url}) | {trade} | {trade_delta} | {battles} | {count_delta} | {stamp} | {status} |")
    lines += ["", "## Detailed metrics (verified API responses only)", "", "| Pairing | KP gained | KP lost | DPS | SPS | TPS |", "|---|---:|---:|---:|---:|---:|"]
    for name, p, s in ranked_pairs:
        x = results[f"{p}-{s}"]
        v = x["snapshot"]
        if v:
            cols = [fmt_num(v.get(n),3 if n in ("dps","sps","tps") else 0) for n in ("killPointsGained","killPointsLost","dps","sps","tps")]
        else:
            cols = ["N/A"] * 5
        lines.append(f"| {name} | " + " | ".join(cols) + " |")
    errors = [f"- **{name}:** {results[f'{p}-{s}']['error']}" for name,p,s in ranked_pairs if results[f"{p}-{s}"]["error"]]
    if errors:
        lines += ["", "## Retrieval errors", "", *errors]
    if sum(v["ok"] for v in results.values()) == 0:
        lines += ["", "**LIVE DATA UNAVAILABLE.** Any retained snapshots are older verified API data, not fresh measurements. No changes are claimed when retrieval fails."]
    lines += ["", "## Scenario integrity", "",
              "This report uses **7 days / Open field** (Combat Lab range index 3, scenario index 1). Older 1-year reports are archived and excluded from change calculations."]
    return "\n".join(lines) + "\n"


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
        data, err = fetch(p, s, prior.get('generatedAtMs') if prior else None)
        if data:
            if prior and data["generatedAtMs"] < prior["generatedAtMs"]:
                err = "Site data older than last verified snapshot; retained last verified snapshot"
                data = None
        if data:
            data["checkedAtUTC"] = now
            if prior is None or data["generatedAtMs"] != prior["generatedAtMs"]:
                store["history"].append({"pairing": name, **data})
            store["snapshots"][key] = data
        current = data or prior
        previous = None
        if current:
            old = [
                item for item in store["history"]
                if item.get("primary") == p
                and item.get("secondary") == s
                and item.get("generatedAtMs", -1) < current["generatedAtMs"]
                and item.get("tradePercent") is not None
            ]
            if old:
                previous = max(old, key=lambda item: item["generatedAtMs"])
        results[key] = {"ok": bool(data), "snapshot": current, "previous": previous, "error": err}
        print(f"{name}: {'OK '+str(data['tradePercent'])+'%' if data else 'FAILED '+str(err)}")
        # Avoid bursts against a shared resource.
        time.sleep(1)
    store["lastCheckedAtUTC"] = now
    store["lastRunSuccessCount"] = sum(v["ok"] for v in results.values())
    store["lastErrors"] = {key: value["error"] for key, value in results.items() if value["error"]}
    store["history"] = store["history"][-500:]
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT.write_text(build_report(store, results, now), encoding="utf-8")
    print(f"Saved {REPORT} and {DATA}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
