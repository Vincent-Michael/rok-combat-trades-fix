#!/usr/bin/env python3
"""Deduplicate successful Combat Lab collections in each Berlin reporting window.

cron-job.org is the sole configured workflow scheduler. A site snapshot may stay
unchanged or become older than eight hours; neither warrants a second collection
after all three monitors completed successfully in this reporting window.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EXPECTED_COUNTS = {"inf": 13, "cav": 13, "archer": 9}


def reporting_window(moment: datetime) -> tuple[str, int]:
    """Identify the last local 01:50, 09:50, or 17:50 collection window."""
    local = moment.astimezone(BERLIN)
    for hour in (17, 9, 1):
        if (local.hour, local.minute) >= (hour, 50):
            return local.date().isoformat(), hour
    return (local.date() - timedelta(days=1)).isoformat(), 17


def completed_in_window(troop: str, expected_count: int, window: tuple[str, int]) -> bool:
    """Check monitor execution, not whether upstream site data changed."""
    try:
        data = json.loads((DATA_DIR / f"trades_{troop}.json").read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(data["lastCheckedAtUTC"].replace("Z", "+00:00"))
        snapshots = data["snapshots"]
        return (
            reporting_window(checked) == window
            and data.get("scenario") == "7d/openField"
            and data.get("lastRunSuccessCount") == expected_count
            and not data.get("lastErrors")
            and data.get("lastRunFailureCount", 0) == 0
            and len(snapshots) == expected_count
        )
    except (OSError, KeyError, ValueError, TypeError, OverflowError, json.JSONDecodeError):
        return False


def main() -> None:
    now = datetime.now(timezone.utc)
    window = reporting_window(now)
    checks = {
        troop: completed_in_window(troop, count, window)
        for troop, count in EXPECTED_COUNTS.items()
    }
    force_refresh = os.environ.get('FORCE_REFRESH', 'false').strip().lower() in ('true', '1', 'yes')
    collect = force_refresh or not all(checks.values())
    print(f"Berlin reporting window: {window}; completed monitors: {checks}; force_refresh={force_refresh}; collect={collect}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"collect={'true' if collect else 'false'}\n")


if __name__ == "__main__":
    main()
