#!/usr/bin/env python3
"""
Collect Discord messages through a streamable HTTP MCP server.

This is the no-raw-token path for the Dolphin Labs digest: the Discord bot token
stays inside the existing Render-hosted discord-mcp-prod service.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from discord_notion_digest import (
    ChannelConfig,
    discord_snowflake_from_datetime,
    iso_z,
    load_channel_configs,
    parse_discord_time,
    utc_now,
)


DEFAULT_MCP_URL = "https://discord-mcp-prod.onrender.com/mcp"
MESSAGE_RE = re.compile(
    r"(?:^|\n)- \(ID: (?P<id>\d+)\) \*\*\[(?P<author>.*?)\]\*\* "
    r"`(?P<timestamp>[^`]+)`: ```(?P<content>.*?)```",
    re.S,
)
THREAD_RE = re.compile(
    r"^- (?P<name>.*?) \(ID: (?P<id>\d+)\) in #(?P<parent>[^ \n]+)"
)


class McpClient:
    def __init__(self, url: str, max_retries: int = 3, retry_delay_seconds: float = 5.0):
        self.url = url
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.next_id = 1
        self.session_id: str | None = None

    def initialize(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "dolphin-discord-digest", "version": "0.1"},
            },
        )
        self.request("notifications/initialized", {}, expect_response=False)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", []) if isinstance(result, dict) else []
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n".join(parts)
        lowered = text.lower()
        operational_failures = [
            "discord client is still connecting",
            "discord rest returned invalid json",
            "discord rest request failed",
            "discord rest rate limited",
            "exception",
        ]
        if any(fragment in lowered for fragment in operational_failures):
            raise RuntimeError(f"Discord MCP tool {name} failed: {text}")
        if lowered.startswith("error") or lowered.startswith("failed"):
            raise RuntimeError(f"Discord MCP tool {name} failed: {text}")
        return text

    def request(
        self,
        method: str,
        params: dict[str, Any],
        expect_response: bool = True,
    ) -> Any:
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if expect_response:
            body["id"] = self.next_id
            self.next_id += 1

        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    session_id = response.headers.get("Mcp-Session-Id")
                    if session_id:
                        self.session_id = session_id
                    raw = response.read().decode("utf-8")
                    if not expect_response:
                        return None
                    payload = parse_mcp_response(raw, response.headers.get("Content-Type", ""))
                    break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds)
                    continue
                raise RuntimeError(f"MCP {method} failed: {exc.code} {detail}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds)
                    continue
                raise RuntimeError(f"MCP {method} failed: {exc}") from exc
        else:
            raise RuntimeError(f"MCP {method} failed after retries")

        if "error" in payload:
            raise RuntimeError(f"MCP {method} failed: {payload['error']}")
        return payload.get("result")


def parse_mcp_response(raw: str, content_type: str) -> dict[str, Any]:
    if "text/event-stream" not in content_type:
        return json.loads(raw) if raw else {}
    data_lines = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return {}
    return json.loads("\n".join(data_lines))


def parse_messages_text(
    text: str,
    guild_id: str,
    channel_id: str,
    channel_name: str,
    area_hint: str | None,
    thread_name: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for match in MESSAGE_RE.finditer(text):
        message_id = match.group("id")
        timestamp = parse_discord_time(match.group("timestamp"))
        messages.append(
            {
                "id": message_id,
                "channel_id": channel_id,
                "guild_id": guild_id,
                "channel_name": channel_name,
                "author_name": match.group("author"),
                "content": match.group("content").strip(),
                "timestamp": iso_z(timestamp),
                "link": f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
                "thread_name": thread_name,
                "area_hint": area_hint,
                "is_bot": False,
            }
        )
    return messages


def parse_active_threads(text: str) -> list[dict[str, str]]:
    threads = []
    for line in text.splitlines():
        match = THREAD_RE.match(line.strip())
        if match:
            threads.append(match.groupdict())
    return threads


def collect(
    mcp: McpClient,
    guild_id: str,
    channels: list[ChannelConfig],
    since: dt.datetime,
    tool_mode: str,
) -> list[dict[str, Any]]:
    after = discord_snowflake_from_datetime(since)
    messages: list[dict[str, Any]] = []
    channels_by_name = {channel.name: channel for channel in channels if channel.name}
    read_messages_tool = "read_messages_rest" if tool_mode == "rest" else "read_messages"
    list_threads_tool = "list_active_threads_rest" if tool_mode == "rest" else "list_active_threads"

    for channel in channels:
        if not channel.read_parent:
            continue
        text = mcp.call_tool(
            read_messages_tool,
            {"channelId": channel.id, "count": "100", "after": after},
        )
        messages.extend(
            parse_messages_text(text, guild_id, channel.id, channel.name or channel.id, channel.area)
        )

    if any(channel.include_threads for channel in channels):
        thread_text = mcp.call_tool(list_threads_tool, {"guildId": guild_id})
        for thread in parse_active_threads(thread_text):
            parent = channels_by_name.get(thread["parent"])
            if not parent or not parent.include_threads:
                continue
            text = mcp.call_tool(
                read_messages_tool,
                {"channelId": thread["id"], "count": "100", "after": after},
            )
            messages.extend(
                parse_messages_text(
                    text,
                    guild_id,
                    thread["id"],
                    parent.name or parent.id,
                    parent.area,
                    thread_name=thread["name"],
                )
            )

    return sorted({message["id"]: message for message in messages}.values(), key=lambda m: m["timestamp"])


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_MCP_URL)
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--since", help="UTC ISO timestamp. Overrides --lookback-minutes.")
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=75,
        help="Minutes to look back when --since is omitted.",
    )
    parser.add_argument("--out", default="-", help="Output JSON path, or '-' for stdout.")
    parser.add_argument("--mcp-retries", type=int, default=3)
    parser.add_argument("--mcp-retry-delay-seconds", type=float, default=5.0)
    parser.add_argument(
        "--tool-mode",
        choices=["rest", "jda"],
        default="rest",
        help="Use REST-backed digest MCP tools by default; jda uses the original gateway-backed tools.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    since = (
        parse_discord_time(args.since)
        if args.since
        else utc_now() - dt.timedelta(minutes=args.lookback_minutes)
    )
    try:
        mcp = McpClient(args.url, args.mcp_retries, args.mcp_retry_delay_seconds)
        mcp.initialize()
        payload = {
            "messages": collect(mcp, args.guild_id, load_channel_configs(), since, args.tool_mode),
            "collected_at": iso_z(utc_now()),
            "source": args.url,
            "tool_mode": args.tool_mode,
        }
    except RuntimeError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    output = json.dumps(payload, indent=2)
    if args.out == "-":
        print(output)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
