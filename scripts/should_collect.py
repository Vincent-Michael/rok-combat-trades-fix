#!/usr/bin/env python3
"""Skip duplicate RoK collections within one Europe/Berlin reporting window.

An unchanged API snapshot is valid; an old or failed API check is not.
The external cron-job.org dispatcher runs at :50. GitHub's schedule is backup at :55.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EXPECTED_COUNTS = {"inf": 11, "cav": 11, "archer": 9}
MAX_SITE_AGE = timedelta(hours=8)


def reporting_window(moment: datetime) -> tuple[str, int]:
    """Identify the local date/hour of the last 01:50, 09:50 or 17:50 slot."""
    local = moment.astimezone(BERLIN)
    for hour in (17, 9, 1):
        if local.hour >= hour:
            return local.date().isoformat(), hour
    return (local.date() - timedelta(days=1)).isoformat(), 17


def completed_in_window(troop: str, count: int, window: tuple[str, int], now: datetime) -> bool:
    try:
        data = json.loads((DATA_DIR / f"trades_{troop}.json").read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(data["lastCheckedAtUTC"].replace("Z", "+00:00"))
        snapshots = data["snapshots"]

        if (
            reporting_window(checked) != window
            or data.get("scenario") != "7d/openField"
            or data.get("lastRunSuccessCount") != count
            or data.get("lastErrors")
            or len(snapshots) != count
        ):
            return False

        # Check actual API generation times, not only the workflow check timestamp.
        for snapshot in snapshots.values():
            generated = datetime.fromtimestamp(snapshot["generatedAtMs"] / 1000, tz=timezone.utc)
            age = now - generated
            if age < -timedelta(minutes=5) or age > MAX_SITE_AGE:
                return False
        return True
    except (OSError, KeyError, ValueError, TypeError, OverflowError, json.JSONDecodeError):
        return False


def main() -> None:
    now = datetime.now(timezone.utc)
    window = reporting_window(now)
    force = os.getenv("FORCE_COLLECTION", "false").lower() == "true"
    checks = {
        troop: completed_in_window(troop, count, window, now)
        for troop, count in EXPECTED_COUNTS.items()
    }
    collect = force or not all(checks.values())
    print(f"Berlin reporting window: {window}; verified checks: {checks}; force={force}; collect={collect}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"collect={'true' if collect else 'false'}\n")


if __name__ == "__main__":
    main()
