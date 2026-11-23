#!/usr/bin/env python3
"""Shared retrieval and source-freshness logic for the 7d/Open Field monitors.

A successful HTTP request is not proof that rokbattles.com generated new data.
Never replace a verified snapshot with a response carrying an older generation time.
"""
import json
import time
from html.parser import HTMLParser
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAX_FRESH_AGE_HOURS = 8
ENDPOINT = "https://rokbattles.com/proxy/v2/global/combat-lab"



class _FlightScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.scripts = []
    def handle_starttag(self, tag, attrs):
        self.in_script = tag == "script"
    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
    def handle_data(self, data):
        if self.in_script and "self.__next_f.push(" in data and "generatedAtMs" in data:
            self.scripts.append(data)


def parse_page_snapshot(html, primary, secondary):
    """Read the exact 7d/Open field summary embedded in Next.js Flight HTML."""
    finder = _FlightScripts()
    finder.feed(html)
    for script in finder.scripts:
        start = script.find("self.__next_f.push(")
        raw = script[start + len("self.__next_f.push("):].rstrip()
        if not raw.endswith(")"):
            continue
        flight = json.loads(raw[:-1])
        if not isinstance(flight, list) or len(flight) < 2 or not isinstance(flight[1], str):
            continue
        payload = flight[1]
        if ":" not in payload:
            continue
        tree = json.loads(payload.split(":", 1)[1])
        if not isinstance(tree, list) or len(tree) < 4 or not isinstance(tree[3], dict):
            continue
        data = tree[3].get("data", {})
        pairing = data.get("pairing", {})
        if (pairing.get("primaryCommanderId"), pairing.get("secondaryCommanderId")) != (primary, secondary):
            continue
        summary = data["ranges"]["7d"]["scenarios"]["openField"]["summary"]
        stamp = int(data["generatedAtMs"])
        if stamp <= 0:
            raise ValueError("Invalid site generation timestamp")
        gained, lost = int(summary["killPointsGained"]), int(summary["killPointsLost"])
        trade = round(gained / lost * 100, 4) if lost else (100.0 if not gained else None)
        return {
            "generatedAtMs": stamp,
            "generatedAtUTC": datetime.fromtimestamp(stamp / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "primary": primary, "secondary": secondary,
            "battles": int(summary["battles"]),
            "uniqueGovernors": int(summary["uniqueGovernors"]),
            "killPointsGained": gained, "killPointsLost": lost,
            "tradePercent": trade,
            "dps": round(float(summary["dps"]), 3),
            "sps": round(float(summary["sps"]), 3),
            "tps": round(float(summary["tps"]), 3),
            "hps": round(float(summary["hps"]), 3),
        }
    raise ValueError("No matching 7d/Open field Next.js data found")


def fetch_page_snapshot(primary, secondary):
    url = "https://rokbattles.com/combat-lab?" + urlencode({"primary": primary, "secondary": secondary})
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; RoKCombatTradesMonitor/4.0)", "Accept": "text/html", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=35) as response:
        if response.status != 200:
            raise ValueError(f"HTML HTTP {response.status}")
        html = response.read(8 * 1024 * 1024).decode("utf-8")
    return parse_page_snapshot(html, primary, secondary)

def site_age_hours(generated_ms):
    return max(0.0, (time.time() * 1000 - generated_ms) / 3_600_000)


def is_fresh(snapshot):
    return bool(snapshot and site_age_hours(snapshot["generatedAtMs"]) <= MAX_FRESH_AGE_HOURS)


def fetch_snapshot(primary, secondary, previous_generated_ms, parser, previous_snapshot=None):
    """Return (verified snapshot, status, error). Status: new, revised, unchanged, error.

    Try up to three requests with unique cache-busting URLs after the first.
    A stale source timestamp or unchanged generation time triggers retries, but
    cannot be refreshed forcibly by query parameters. No data is invented.
    """
    issues = []
    best = None
    try:
        page_snapshot = fetch_page_snapshot(primary, secondary)
        if previous_generated_ms is None or page_snapshot['generatedAtMs'] >= previous_generated_ms:
            status = 'new' if previous_generated_ms is None or page_snapshot['generatedAtMs'] > previous_generated_ms else ('revised' if isinstance(previous_snapshot, dict) and any(page_snapshot.get(k) != previous_snapshot.get(k) for k in page_snapshot) else 'unchanged')
            return page_snapshot, status, None
        issues.append('HTML page snapshot older than stored data')
    except Exception as exc:
        issues.append(f'HTML source: {type(exc).__name__}: {str(exc)[:160]}')
    previous_core = ({k: v for k, v in previous_snapshot.items() if k not in ("checkedAtUTC",)}
                     if isinstance(previous_snapshot, dict) else None)
    for attempt in range(3):
        params = {"primary": primary, "secondary": secondary}
        if attempt:
            params["_cb"] = f"{time.time_ns()}-{attempt}"
        url = ENDPOINT + "?" + urlencode(params)
        try:
            request = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "RoKCombatTradesMonitor/3.0",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
            })
            with urlopen(request, timeout=25) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                payload = json.loads(response.read(12 * 1024 * 1024))
            snapshot = parser(payload, primary, secondary)
            stamp = snapshot["generatedAtMs"]
            if previous_generated_ms is not None and stamp < previous_generated_ms:
                issues.append(f"attempt {attempt + 1}: source older than stored snapshot")
            else:
                if best is None or stamp > best["generatedAtMs"]:
                    best = snapshot
                if previous_generated_ms is not None and stamp == previous_generated_ms:
                    issues.append(f"attempt {attempt + 1}: source generation unchanged")
                if not is_fresh(snapshot):
                    issues.append(f"attempt {attempt + 1}: source generation older than {MAX_FRESH_AGE_HOURS}h")
                if is_fresh(snapshot) and (previous_generated_ms is None or stamp > previous_generated_ms):
                    return snapshot, "new", None
        except Exception as exc:
            issues.append(f"attempt {attempt + 1}: {type(exc).__name__}: {str(exc)[:160]}")
        if attempt < 2:
            time.sleep(2)

    if best is not None:
        changed = previous_generated_ms is None or best["generatedAtMs"] > previous_generated_ms
        revised = (not changed and previous_core is not None and best != previous_core)
        return best, "new" if changed else "revised" if revised else "unchanged", None
    return None, "error", "; ".join(issues) or "No valid 7d/openField response"


def status_label(status, snapshot):
    if not snapshot:
        return "UNVERIFIED (no valid source data)"
    suffix = "STALE (>8h)" if not is_fresh(snapshot) else "within 8h"
    if status == "error":
        return f"Retained last verified snapshot; retrieval failed; {suffix}"
    if status == "revised":
        return f"Source values REVISED at same generation timestamp; {suffix}"
    if status == "unchanged":
        return f"Site-generated snapshot UNCHANGED; {suffix}"
    return f"Distinct site-generated snapshot; {suffix}"


def save_run_status(store, results):
    """Track retrieval, distinct generation, source age, and errors separately."""
    store["lastRunSuccessCount"] = sum(bool(x["ok"]) for x in results.values())
    store["lastRunNewCount"] = sum(x["status"] == "new" for x in results.values())
    store["lastRunRevisedCount"] = sum(x["status"] == "revised" for x in results.values())
    store["lastRunUnchangedCount"] = sum(x["status"] == "unchanged" for x in results.values())
    store["lastRunFailureCount"] = sum(x["status"] == "error" for x in results.values())
    store["lastRunFreshCount"] = sum(bool(x["ok"] and is_fresh(x["snapshot"])) for x in results.values())
    store["lastRunStaleCount"] = sum(bool(x["snapshot"] and not is_fresh(x["snapshot"])) for x in results.values())
    store["lastErrors"] = {key: x["error"] for key, x in results.items() if x["error"]}
    store["lastWarnings"] = {
        key: status_label(x["status"], x["snapshot"])
        for key, x in results.items()
        if x["status"] in ("unchanged", "revised") or (x["snapshot"] and not is_fresh(x["snapshot"]))
    }
    store["lastRunStatuses"] = {key: x["status"] for key, x in results.items()}


def report_status_summary(results):
    total = len(results)
    ok = sum(bool(x["ok"]) for x in results.values())
    new = sum(x["status"] == "new" for x in results.values())
    unchanged = sum(x["status"] == "unchanged" for x in results.values())
    revised = sum(x["status"] == "revised" for x in results.values())
    fresh = sum(bool(x["ok"] and is_fresh(x["snapshot"])) for x in results.values())
    stale = sum(bool(x["snapshot"] and not is_fresh(x["snapshot"])) for x in results.values())
    return (f"API checks: {ok}/{total}; distinct site snapshots: {new}/{total}; "
            f"revised at same timestamp: {revised}/{total}; unchanged: {unchanged}/{total}; fresh site timestamps (<=8h): {fresh}/{total}; "
            f"stale site timestamps: {stale}/{total}")
