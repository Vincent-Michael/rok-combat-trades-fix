#!/usr/bin/env python3
"""ROK Battles Combat Lab cavalry monitor; Python 3.10+, standard library only."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from combat_source import fetch_snapshot, save_run_status, status_label, report_status_summary
from combat_presentation import build_trade_report, build_trade_svg

# Cavalry-only snapshot history. Retain 7d/Open field setting.
SCENARIO_KEY = "7d/openField"
SCENARIO_LABEL = "7 days / Open field"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "trades_cav.json"
REPORT = ROOT / "REPORT_CAV.md"

PAIRS = [
    ("Ivan IV / William Marshal", 619, 620),
    ("Ivan IV / Achilles", 619, 575),
    ("Attila / Achilles", 103, 575),
    ("Ivan IV / Vercingetorix", 619, 616),
    ("Arthur Pendragon / Ivan IV", 540, 619),
    ("Arthur Pendragon / Achilles", 540, 575),
    ("Arthur Pendragon / Gang Gamchan", 540, 579),
    ("Arthur Pendragon / Hector", 540, 576),
    ("Arthur Pendragon / Vercingetorix", 540, 616),
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


def fetch(primary, secondary, previous_generated_ms=None, previous_snapshot=None):
    """Fetch only verified 7d/Open Field data using shared retry/freshness logic."""
    return fetch_snapshot(primary, secondary, previous_generated_ms, parse_payload, previous_snapshot)


def fmt_num(value, digits=0):
    return "N/A" if value is None else f"{value:,.{digits}f}"


def build_report(store, results, now):
    return build_trade_report("cavalry", PAIRS, results, now)


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
        data, status, err = fetch(p, s, prior.get('generatedAtMs') if prior else None)
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
    chart_path = ROOT / "charts" / "cavalry.svg"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_text(build_trade_svg("cavalry", PAIRS, results), encoding="utf-8")
    print(f"Saved {REPORT} and {DATA}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
