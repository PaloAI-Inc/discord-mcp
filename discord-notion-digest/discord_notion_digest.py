#!/usr/bin/env python3
"""
Discord to Notion signal digest.

This job reads recent Discord messages, keeps only actionable team signal, and
writes a compact digest into the Dolphin Labs Discord Digest Notion data source.
It intentionally avoids raw transcript storage.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DISCORD_API = "https://discord.com/api/v10"
NOTION_API = "https://api.notion.com/v1"
DISCORD_EPOCH_MS = 1420070400000
DEFAULT_NOTION_DATA_SOURCE_ID = "387036fe-b310-80e1-bb4a-000b910c600b"

AREA_KEYWORDS = {
    "Dev": {
        "api",
        "backend",
        "bug",
        "build",
        "deploy",
        "frontend",
        "incident",
        "migration",
        "planetscale",
        "pr",
        "prod",
        "render",
        "release",
        "staging",
        "test",
        "tests",
    },
    "Marketing": {
        "ad",
        "ads",
        "cac",
        "conversion",
        "creative",
        "email",
        "funnel",
        "growth",
        "landing",
        "launch",
        "meta",
        "offer",
        "referral",
        "tiktok",
    },
    "Business": {
        "contract",
        "customer",
        "fundraise",
        "hiring",
        "investor",
        "mrr",
        "ops",
        "partner",
        "partnership",
        "price",
        "pricing",
        "revenue",
        "sales",
    },
}

OUTCOME_PATTERNS = {
    "Decision": re.compile(
        r"\b(decided|decision|approved|landed on|going with|ship(ping)?|merge(d)?|use this|we should)\b",
        re.I,
    ),
    "Unanswered question": re.compile(
        r"(\?|blocked|unclear|does anyone|who can|what should|how should|need answer)",
        re.I,
    ),
    "Feedback requested": re.compile(
        r"\b(feedback|review|thoughts|wdyt|can you look|take a look|critique)\b",
        re.I,
    ),
    "Action item": re.compile(
        r"\b(todo|to do|need to|please|assign|owner|next step|i'll|i will|we need)\b",
        re.I,
    ),
    "Blocker": re.compile(
        r"\b(blocked|blocking|blocker|failing|broken|stuck|cannot|can't)\b", re.I
    ),
    "Customer or market signal": re.compile(
        r"\b(customer|user said|feedback|market|cac|mrr|conversion|sales|pricing)\b",
        re.I,
    ),
}

OMIT_PATTERNS = re.compile(
    r"^(ok|okay|yes|yep|no|nah|thanks|thx|lol|lmao|haha|done|fixed|merged)\W*$",
    re.I,
)


@dataclasses.dataclass(frozen=True)
class ChannelConfig:
    id: str
    name: str = ""
    area: str | None = None
    include_threads: bool = True
    read_parent: bool = True


@dataclasses.dataclass(frozen=True)
class Config:
    discord_bot_token: str
    discord_guild_id: str
    discord_channels: list[ChannelConfig]
    notion_token: str
    notion_data_source_id: str
    notion_version: str
    include_active_threads: bool
    ignore_bots: bool
    write_quiet_runs: bool
    dry_run: bool
    run_source: str
    lookback_minutes_hourly: int
    lookback_hours_daily: int
    timezone: str

    @classmethod
    def from_env(cls, args: argparse.Namespace) -> "Config":
        uses_message_json = bool(args.messages_json)
        channel_configs = [] if uses_message_json and not args.validate_config else load_channel_configs()
        notion_token = os.getenv("NOTION_TOKEN", "").strip()
        if not args.dry_run and not args.validate_config and not notion_token:
            raise SystemExit("Missing required environment variable: NOTION_TOKEN")
        return cls(
            discord_bot_token=""
            if uses_message_json or args.validate_config
            else require_env("DISCORD_BOT_TOKEN"),
            discord_guild_id=os.getenv("DISCORD_GUILD_ID", "").strip()
            if uses_message_json or args.validate_config
            else require_env("DISCORD_GUILD_ID"),
            discord_channels=channel_configs,
            notion_token=notion_token,
            notion_data_source_id=os.getenv(
                "NOTION_DATA_SOURCE_ID", DEFAULT_NOTION_DATA_SOURCE_ID
            ).strip(),
            notion_version=os.getenv("NOTION_VERSION", "2025-09-03").strip(),
            include_active_threads=env_bool("INCLUDE_ACTIVE_THREADS", True),
            ignore_bots=env_bool("IGNORE_BOTS", True),
            write_quiet_runs=env_bool("WRITE_QUIET_RUNS", False),
            dry_run=args.dry_run,
            run_source=os.getenv("RUN_SOURCE", "discord-notion-digest").strip(),
            lookback_minutes_hourly=int(os.getenv("LOOKBACK_MINUTES_HOURLY", "75")),
            lookback_hours_daily=int(os.getenv("LOOKBACK_HOURS_DAILY", "24")),
            timezone=os.getenv("REPORT_TIMEZONE", "America/Los_Angeles").strip(),
        )

    @property
    def discord_channel_ids(self) -> list[str]:
        return [channel.id for channel in self.discord_channels]


@dataclasses.dataclass(frozen=True)
class DiscordMessage:
    id: str
    channel_id: str
    guild_id: str
    channel_name: str
    author_name: str
    content: str
    timestamp: dt.datetime
    link: str
    thread_id: str | None = None
    thread_name: str | None = None
    area_hint: str | None = None
    is_bot: bool = False

    @property
    def source_label(self) -> str:
        if self.thread_name:
            return f"#{self.channel_name} / {self.thread_name}"
        return f"#{self.channel_name}"


@dataclasses.dataclass(frozen=True)
class Signal:
    title: str
    summary: str
    area: str
    outcomes: list[str]
    source: DiscordMessage
    score: int


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def load_channel_configs() -> list[ChannelConfig]:
    raw_json = os.getenv("DISCORD_CHANNEL_CONFIG_JSON", "").strip()
    config_path = os.getenv("DISCORD_CHANNEL_CONFIG_PATH", "").strip()
    if raw_json and config_path:
        raise SystemExit(
            "Use only one of DISCORD_CHANNEL_CONFIG_JSON or DISCORD_CHANNEL_CONFIG_PATH"
        )
    if config_path:
        with open(config_path, "r", encoding="utf-8") as handle:
            raw_json = handle.read()
    if raw_json:
        return parse_channel_config(json.loads(raw_json))

    return [
        ChannelConfig(id=channel_id)
        for channel_id in split_csv(require_env("DISCORD_CHANNEL_IDS"))
    ]


def parse_channel_config(payload: Any) -> list[ChannelConfig]:
    if isinstance(payload, list):
        raw_channels = payload
    elif isinstance(payload, dict):
        raw_channels = payload.get("channels", [])
    else:
        raise SystemExit("Discord channel config must be a JSON object or array")

    channels: list[ChannelConfig] = []
    for raw in raw_channels:
        if not isinstance(raw, dict):
            raise SystemExit("Each channel config must be a JSON object")
        channel_id = str(raw.get("id") or "").strip()
        if not channel_id:
            raise SystemExit("Each channel config must include an id")
        area = str(raw.get("area") or "").strip() or None
        if area and area not in AREA_KEYWORDS:
            raise SystemExit(f"Unknown channel area {area!r}; use Dev, Marketing, or Business")
        channels.append(
            ChannelConfig(
                id=channel_id,
                name=str(raw.get("name") or "").strip(),
                area=area,
                include_threads=bool(raw.get("include_threads", True)),
                read_parent=bool(raw.get("read_parent", True)),
            )
        )

    if not channels:
        raise SystemExit("At least one Discord channel must be configured")
    return channels


def load_messages_json(path: str) -> list[DiscordMessage]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    payload = json.loads(raw)
    rows = payload.get("messages", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("Message JSON must be a list or an object with a messages list")
    return [discord_message_from_json(row) for row in rows]


def discord_message_from_json(row: Any) -> DiscordMessage:
    if not isinstance(row, dict):
        raise SystemExit("Each message JSON row must be an object")
    message_id = str(row.get("id") or "").strip()
    channel_id = str(row.get("channel_id") or "").strip()
    guild_id = str(row.get("guild_id") or "").strip()
    timestamp = str(row.get("timestamp") or "").strip()
    if not message_id or not channel_id or not guild_id or not timestamp:
        raise SystemExit("Message JSON rows require id, channel_id, guild_id, and timestamp")
    return DiscordMessage(
        id=message_id,
        channel_id=channel_id,
        guild_id=guild_id,
        channel_name=str(row.get("channel_name") or channel_id),
        author_name=str(row.get("author_name") or "Unknown"),
        content=str(row.get("content") or "").strip(),
        timestamp=parse_discord_time(timestamp),
        link=str(row.get("link") or f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"),
        thread_id=str(row.get("thread_id") or "").strip() or None,
        thread_name=str(row.get("thread_name") or "").strip() or None,
        area_hint=str(row.get("area") or row.get("area_hint") or "").strip() or None,
        is_bot=bool(row.get("is_bot", False)),
    )


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_discord_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        dt.timezone.utc
    )


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def discord_snowflake_from_datetime(value: dt.datetime) -> str:
    millis = int(value.astimezone(dt.timezone.utc).timestamp() * 1000)
    return str((millis - DISCORD_EPOCH_MS) << 22)


def local_report_date(value: dt.datetime, timezone_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo

        local = value.astimezone(ZoneInfo(timezone_name))
    except Exception:
        local = value.astimezone(dt.timezone.utc)
    return local.date().isoformat()


class HttpClient:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        request_headers = dict(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                url,
                data=data,
                headers=request_headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    retry_after = (
                        exc.headers.get("Retry-After")
                        or exc.headers.get("X-RateLimit-Reset-After")
                        or "1"
                    )
                    try:
                        delay = min(float(retry_after), 10.0)
                    except ValueError:
                        delay = 1.0
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


class DiscordClient:
    def __init__(self, token: str, guild_id: str, http: HttpClient):
        self.token = token
        self.guild_id = guild_id
        self.http = http
        self.channel_cache: dict[str, dict[str, Any]] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self.token}",
            "User-Agent": "DolphinLabsDiscordDigest/1.0",
        }

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{DISCORD_API}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self.http.request("GET", url, self._headers())

    def channel(self, channel_id: str) -> dict[str, Any]:
        if channel_id not in self.channel_cache:
            self.channel_cache[channel_id] = self.get_json(f"/channels/{channel_id}")
        return self.channel_cache[channel_id]

    def channel_name(self, channel_id: str) -> str:
        return str(self.channel(channel_id).get("name") or channel_id)

    def active_threads(self, parent_channel_ids: set[str]) -> list[dict[str, Any]]:
        data = self.get_json(f"/guilds/{self.guild_id}/threads/active")
        threads = data.get("threads", []) if isinstance(data, dict) else []
        return [
            thread
            for thread in threads
            if str(thread.get("parent_id") or "") in parent_channel_ids
            or str(thread.get("id") or "") in parent_channel_ids
        ]

    def channel_messages(
        self,
        channel_id: str,
        after_snowflake: str,
        parent_channel_id: str | None = None,
        parent_channel_name: str | None = None,
        thread_name: str | None = None,
        area_hint: str | None = None,
        max_pages: int = 20,
    ) -> list[DiscordMessage]:
        messages: list[DiscordMessage] = []
        after = after_snowflake
        for _ in range(max_pages):
            batch = self.get_json(
                f"/channels/{channel_id}/messages",
                {"limit": "100", "after": after},
            )
            if not isinstance(batch, list) or not batch:
                break

            batch_messages = [
                self._message_from_payload(
                    payload,
                    channel_id=channel_id,
                    parent_channel_id=parent_channel_id,
                    parent_channel_name=parent_channel_name,
                    thread_name=thread_name,
                    area_hint=area_hint,
                )
                for payload in batch
            ]
            messages.extend(batch_messages)
            newest_id = max(batch_messages, key=lambda message: int(message.id)).id
            if newest_id == after:
                break
            after = newest_id
            if len(batch) < 100:
                break
            time.sleep(0.25)

        return sorted(messages, key=lambda message: message.timestamp)

    def _message_from_payload(
        self,
        payload: dict[str, Any],
        channel_id: str,
        parent_channel_id: str | None,
        parent_channel_name: str | None,
        thread_name: str | None,
        area_hint: str | None,
    ) -> DiscordMessage:
        message_id = str(payload["id"])
        source_channel_id = parent_channel_id or channel_id
        channel_name = parent_channel_name or self.channel_name(source_channel_id)
        author = payload.get("author") or {}
        author_name = str(author.get("global_name") or author.get("username") or "Unknown")
        link_channel_id = channel_id
        return DiscordMessage(
            id=message_id,
            channel_id=source_channel_id,
            guild_id=self.guild_id,
            channel_name=channel_name,
            author_name=author_name,
            content=str(payload.get("content") or "").strip(),
            timestamp=parse_discord_time(str(payload["timestamp"])),
            link=f"https://discord.com/channels/{self.guild_id}/{link_channel_id}/{message_id}",
            thread_id=channel_id if parent_channel_id else None,
            thread_name=thread_name,
            area_hint=area_hint,
            is_bot=bool(author.get("bot")),
        )


class NotionClient:
    def __init__(self, token: str, data_source_id: str, notion_version: str, http: HttpClient):
        self.token = token
        self.data_source_id = data_source_id
        self.notion_version = notion_version
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.notion_version,
        }

    def recent_source_ids(self, since: dt.datetime, cadence: str | None = None) -> set[str]:
        filters: list[dict[str, Any]] = [
            {
                "property": "Generated at",
                "date": {"on_or_after": iso_z(since)},
            }
        ]
        if cadence:
            filters.append({"property": "Cadence", "select": {"equals": cadence}})
        body = {"filter": {"and": filters}, "page_size": 100}
        try:
            data = self.http.request(
                "POST",
                f"{NOTION_API}/data_sources/{self.data_source_id}/query",
                self._headers(),
                body,
            )
        except RuntimeError as exc:
            print(f"warning: could not query Notion for dedupe: {exc}", file=sys.stderr)
            return set()

        ids: set[str] = set()
        for row in data.get("results", []):
            prop = row.get("properties", {}).get("Source message IDs", {})
            for rich in prop.get("rich_text", []):
                text = rich.get("plain_text", "")
                ids.update(split_csv(text))
        return ids

    def create_digest(self, digest: dict[str, Any]) -> Any:
        body = {
            "parent": {"data_source_id": self.data_source_id},
            "properties": notion_properties(digest),
            "children": notion_children(digest),
        }
        return self.http.request("POST", f"{NOTION_API}/pages", self._headers(), body)


def collect_messages(
    discord: DiscordClient,
    config: Config,
    window_start: dt.datetime,
) -> list[DiscordMessage]:
    after = discord_snowflake_from_datetime(window_start)
    messages: list[DiscordMessage] = []
    channel_by_id = {channel.id: channel for channel in config.discord_channels}
    thread_parent_ids = {
        channel.id for channel in config.discord_channels if channel.include_threads
    }

    for channel in config.discord_channels:
        if not channel.read_parent:
            continue
        messages.extend(
            discord.channel_messages(
                channel.id,
                after,
                parent_channel_name=channel.name or None,
                area_hint=channel.area,
            )
        )

    if config.include_active_threads and thread_parent_ids:
        for thread in discord.active_threads(thread_parent_ids):
            thread_id = str(thread["id"])
            parent_id = str(thread.get("parent_id") or "")
            parent_config = channel_by_id.get(parent_id)
            thread_name = str(thread.get("name") or thread_id)
            messages.extend(
                discord.channel_messages(
                    thread_id,
                    after,
                    parent_channel_id=parent_id,
                    parent_channel_name=parent_config.name if parent_config else None,
                    thread_name=thread_name,
                    area_hint=parent_config.area if parent_config else None,
                )
            )

    unique = {message.id: message for message in messages}
    return sorted(unique.values(), key=lambda message: message.timestamp)


def meaningful_signals(
    messages: list[DiscordMessage],
    ignore_bots: bool,
    already_seen: set[str],
    max_items: int,
) -> list[Signal]:
    signals: list[Signal] = []
    for message in messages:
        if message.id in already_seen:
            continue
        if ignore_bots and message.is_bot:
            continue
        if not message.content or OMIT_PATTERNS.match(message.content):
            continue

        outcomes = [
            name for name, pattern in OUTCOME_PATTERNS.items() if pattern.search(message.content)
        ]
        area, area_score = classify_area(message.content, message.area_hint)
        score = len(outcomes) * 3 + area_score + min(len(message.content) // 120, 3)
        if not outcomes and score < 3:
            continue

        title = compact_title(message.content)
        signals.append(
            Signal(
                title=title,
                summary=compact_summary(message.content),
                area=area,
                outcomes=outcomes or ["Action item"],
                source=message,
                score=score,
            )
        )

    signals.sort(key=lambda signal: (signal.score, signal.source.timestamp), reverse=True)
    return signals[:max_items]


def classify_area(content: str, area_hint: str | None = None) -> tuple[str, int]:
    lowered = content.lower()
    scores = {
        area: sum(1 for keyword in keywords if keyword in lowered)
        for area, keywords in AREA_KEYWORDS.items()
    }
    if area_hint in scores:
        scores[str(area_hint)] += 2
    area = max(scores, key=scores.get)
    score = scores[area]
    if score == 0 and area_hint in AREA_KEYWORDS:
        return str(area_hint), 0
    if score == 0:
        return "Dev", 0
    return area, score


def compact_title(content: str) -> str:
    summary = compact_summary(content)
    if len(summary) <= 80:
        return summary
    return f"{summary[:77].rstrip()}..."


def compact_summary(content: str) -> str:
    collapsed = re.sub(r"\s+", " ", content).strip()
    collapsed = re.sub(r"<@!?\d+>", "@someone", collapsed)
    return collapsed[:280].rstrip()


def build_digest(
    cadence: str,
    signals: list[Signal],
    window_start: dt.datetime,
    window_end: dt.datetime,
    config: Config,
) -> dict[str, Any]:
    generated_at = utc_now()
    title_time = local_report_date(window_end, config.timezone)
    if cadence == "Hourly":
        hour = window_end.astimezone(dt.timezone.utc).strftime("%H:00 UTC")
        title = f"Discord Digest - {title_time} {hour}"
    else:
        title = f"Discord Digest - {title_time}"

    areas = sorted({signal.area for signal in signals})
    outcomes = sorted({outcome for signal in signals for outcome in signal.outcomes})
    source_channels = sorted({signal.source.source_label for signal in signals})
    source_ids = [signal.source.id for signal in signals]

    return {
        "title": title,
        "cadence": cadence,
        "report_date": title_time,
        "window_start": iso_z(window_start),
        "window_end": iso_z(window_end),
        "generated_at": iso_z(generated_at),
        "areas": areas,
        "outcomes": outcomes,
        "signal_count": len(signals),
        "status": "Published" if signals else "Skipped - quiet",
        "meaningful": bool(signals),
        "primary_link": signals[0].source.link if signals else "",
        "source_channels": ", ".join(source_channels),
        "source_message_ids": ",".join(source_ids),
        "run_source": config.run_source,
        "signals": signals,
    }


def notion_properties(digest: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": digest["title"]}}]},
        "Report date": {"date": {"start": digest["report_date"]}},
        "Window start": {"date": {"start": digest["window_start"]}},
        "Window end": {"date": {"start": digest["window_end"]}},
        "Generated at": {"date": {"start": digest["generated_at"]}},
        "Cadence": {"select": {"name": digest["cadence"]}},
        "Areas": {"multi_select": [{"name": area} for area in digest["areas"]]},
        "Outcome types": {
            "multi_select": [{"name": outcome} for outcome in digest["outcomes"]]
        },
        "Meaningful update": {"checkbox": digest["meaningful"]},
        "Signal count": {"number": digest["signal_count"]},
        "Status": {"select": {"name": digest["status"]}},
        "Source channels": {"rich_text": rich_text(digest["source_channels"])},
        "Source message IDs": {"rich_text": rich_text(digest["source_message_ids"])},
        "Run source": {"rich_text": rich_text(digest["run_source"])},
    }
    if digest["primary_link"]:
        props["Primary Discord link"] = {"url": digest["primary_link"]}
    return props


def rich_text(value: str) -> list[dict[str, Any]]:
    if not value:
        return []
    return [{"text": {"content": value[:1900]}}]


def notion_children(digest: dict[str, Any]) -> list[dict[str, Any]]:
    signals: list[Signal] = digest["signals"]
    if not signals:
        return [
            paragraph(
                "No meaningful decisions, unanswered questions, feedback requests, "
                "actions, blockers, or business/marketing/dev signals were found."
            )
        ]

    children: list[dict[str, Any]] = [
        heading("Overview"),
    ]
    for signal in signals[:4]:
        children.append(
            bullet(
                f"{signal.area}: {signal.title} ({', '.join(signal.outcomes)}) - {signal.source.link}"
            )
        )

    by_area: dict[str, list[Signal]] = {}
    for signal in signals:
        by_area.setdefault(signal.area, []).append(signal)

    for area in ["Dev", "Marketing", "Business"]:
        area_signals = by_area.get(area, [])
        if not area_signals:
            continue
        children.append(heading(area))
        for signal in area_signals:
            children.append(
                bullet(
                    f"{signal.summary} - {signal.source.author_name}, "
                    f"{signal.source.source_label}, {signal.source.link}"
                )
            )
    return children


def heading(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": text}}]},
    }


def paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"text": {"content": text[:1900]}}]},
    }


def bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"text": {"content": text[:1900]}}]},
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cadence", choices=["Hourly", "Daily"], default="Hourly")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate environment/configuration without calling Discord or Notion.",
    )
    parser.add_argument("--now", help="Override current UTC time, ISO-8601")
    parser.add_argument(
        "--messages-json",
        help=(
            "Read normalized Discord messages from a JSON file or '-' instead of "
            "calling Discord directly. Intended for MCP/connector automations."
        ),
    )
    return parser.parse_args(argv)


def window_for(cadence: str, now: dt.datetime, config: Config) -> tuple[dt.datetime, dt.datetime]:
    if cadence == "Daily":
        return now - dt.timedelta(hours=config.lookback_hours_daily), now
    return now - dt.timedelta(minutes=config.lookback_minutes_hourly), now


def dedupe_source_ids(
    notion: NotionClient | None,
    cadence: str,
    now: dt.datetime,
) -> set[str]:
    if not notion:
        return set()
    if cadence == "Daily":
        return notion.recent_source_ids(now - dt.timedelta(hours=36), cadence="Daily")
    return notion.recent_source_ids(now - dt.timedelta(days=7))


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config = Config.from_env(args)
    if args.validate_config:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "channels": [
                        {
                            "id": channel.id,
                            "name": channel.name,
                            "area": channel.area,
                            "include_threads": channel.include_threads,
                            "read_parent": channel.read_parent,
                        }
                        for channel in config.discord_channels
                    ],
                    "notion_data_source_id": config.notion_data_source_id,
                    "notion_version": config.notion_version,
                    "run_source": config.run_source,
                },
                indent=2,
            )
        )
        return 0

    now = parse_discord_time(args.now) if args.now else utc_now()
    window_start, window_end = window_for(args.cadence, now, config)

    http = HttpClient()
    if args.messages_json:
        all_messages = load_messages_json(args.messages_json)
        messages = [
            message
            for message in all_messages
            if window_start <= message.timestamp <= window_end
        ]
    else:
        discord = DiscordClient(config.discord_bot_token, config.discord_guild_id, http)
        messages = collect_messages(discord, config, window_start)

    notion = (
        NotionClient(config.notion_token, config.notion_data_source_id, config.notion_version, http)
        if config.notion_token
        else None
    )
    already_seen = dedupe_source_ids(notion, args.cadence, now)
    max_items = 10 if args.cadence == "Daily" else 5
    signals = meaningful_signals(messages, config.ignore_bots, already_seen, max_items)
    digest = build_digest(args.cadence, signals, window_start, window_end, config)

    if not signals and not config.write_quiet_runs:
        print(
            json.dumps(
                {
                    "status": "skipped_quiet",
                    "messages_seen": len(messages),
                    "window_start": digest["window_start"],
                    "window_end": digest["window_end"],
                },
                indent=2,
            )
        )
        return 0

    if config.dry_run:
        printable = dict(digest)
        printable["signals"] = [dataclasses.asdict(signal) for signal in signals]
        print(json.dumps(printable, indent=2, default=str))
        return 0

    if not notion:
        raise SystemExit("Missing required environment variable: NOTION_TOKEN")

    result = notion.create_digest(digest)
    print(json.dumps({"status": digest["status"], "notion_result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
