#!/usr/bin/env python3
"""Shared retrieval and source-freshness logic for the 7d/Open Field monitors.

A successful HTTP request is not proof that rokbattles.com generated new data.
Never replace a verified snapshot with a response carrying an older generation time.
"""
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAX_FRESH_AGE_HOURS = 8
ENDPOINT = "https://rokbattles.com/proxy/v2/global/combat-lab"


def site_age_hours(generated_ms):
    return max(0.0, (time.time() * 1000 - generated_ms) / 3_600_000)


def is_fresh(snapshot):
    return bool(snapshot and site_age_hours(snapshot["generatedAtMs"]) <= MAX_FRESH_AGE_HOURS)


def fetch_snapshot(primary, secondary, previous_generated_ms, parser):
    """Return (verified snapshot, status, error). Status: new, unchanged, error.

    Try up to three requests with unique cache-busting URLs after the first.
    A stale source timestamp or unchanged generation time triggers retries, but
    cannot be refreshed forcibly by query parameters. No data is invented.
    """
    issues = []
    best = None
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
        return best, "new" if changed else "unchanged", None
    return None, "error", "; ".join(issues) or "No valid 7d/openField response"


def status_label(status, snapshot):
    if not snapshot:
        return "UNVERIFIED (no valid source data)"
    suffix = "STALE (>8h)" if not is_fresh(snapshot) else "within 8h"
    if status == "error":
        return f"Retained last verified snapshot; retrieval failed; {suffix}"
    if status == "unchanged":
        return f"Site-generated snapshot UNCHANGED; {suffix}"
    return f"Distinct site-generated snapshot; {suffix}"


def save_run_status(store, results):
    """Track retrieval, distinct generation, source age, and errors separately."""
    store["lastRunSuccessCount"] = sum(bool(x["ok"]) for x in results.values())
    store["lastRunNewCount"] = sum(x["status"] == "new" for x in results.values())
    store["lastRunUnchangedCount"] = sum(x["status"] == "unchanged" for x in results.values())
    store["lastRunFailureCount"] = sum(x["status"] == "error" for x in results.values())
    store["lastRunFreshCount"] = sum(bool(x["ok"] and is_fresh(x["snapshot"])) for x in results.values())
    store["lastRunStaleCount"] = sum(bool(x["snapshot"] and not is_fresh(x["snapshot"])) for x in results.values())
    store["lastErrors"] = {key: x["error"] for key, x in results.items() if x["error"]}
    store["lastWarnings"] = {
        key: status_label(x["status"], x["snapshot"])
        for key, x in results.items()
        if x["status"] == "unchanged" or (x["snapshot"] and not is_fresh(x["snapshot"]))
    }
    store["lastRunStatuses"] = {key: x["status"] for key, x in results.items()}


def report_status_summary(results):
    total = len(results)
    ok = sum(bool(x["ok"]) for x in results.values())
    new = sum(x["status"] == "new" for x in results.values())
    unchanged = sum(x["status"] == "unchanged" for x in results.values())
    fresh = sum(bool(x["ok"] and is_fresh(x["snapshot"])) for x in results.values())
    stale = sum(bool(x["snapshot"] and not is_fresh(x["snapshot"])) for x in results.values())
    return (f"API checks: {ok}/{total}; distinct site snapshots: {new}/{total}; "
            f"unchanged: {unchanged}/{total}; fresh site timestamps (<=8h): {fresh}/{total}; "
            f"stale site timestamps: {stale}/{total}")
