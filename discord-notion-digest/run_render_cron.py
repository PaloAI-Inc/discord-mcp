#!/usr/bin/env python3
"""Render cron entrypoint for the Dolphin Discord Notion digest."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from zoneinfo import ZoneInfo


REQUIRED_SECRETS = ("DISCORD_BOT_TOKEN", "NOTION_TOKEN")


def missing_secrets() -> list[str]:
    return [name for name in REQUIRED_SECRETS if not os.getenv(name, "").strip()]


def run_digest(cadence: str) -> int:
    env = os.environ.copy()
    env["RUN_SOURCE"] = f"{env.get('RUN_SOURCE_BASE', 'discord-notion-digest-render')}-{cadence.lower()}"
    print(json.dumps({"event": "starting_digest", "cadence": cadence}))
    completed = subprocess.run(
        [sys.executable, "discord_notion_digest.py", "--cadence", cadence],
        env=env,
        check=False,
    )
    print(
        json.dumps(
            {
                "event": "finished_digest",
                "cadence": cadence,
                "returncode": completed.returncode,
            }
        )
    )
    return completed.returncode


def should_run_daily(now_utc: dt.datetime) -> bool:
    if os.getenv("FORCE_DAILY_DIGEST", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    timezone = ZoneInfo(os.getenv("REPORT_TIMEZONE", "America/Los_Angeles"))
    daily_hour = int(os.getenv("DAILY_REPORT_HOUR_LOCAL", "23"))
    return now_utc.astimezone(timezone).hour == daily_hour


def main() -> int:
    missing = missing_secrets()
    if missing:
        print(
            json.dumps(
                {
                    "status": "waiting_for_secrets",
                    "missing": missing,
                    "message": "Set these Render environment variables before the digest can publish.",
                }
            )
        )
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    exit_code = run_digest("Hourly")
    if should_run_daily(now):
        exit_code = max(exit_code, run_digest("Daily"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
