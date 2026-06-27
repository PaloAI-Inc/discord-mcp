import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from discord_notion_digest import (  # noqa: E402
    DiscordMessage,
    build_digest,
    classify_area,
    dedupe_source_ids,
    discord_message_from_json,
    meaningful_signals,
    notion_properties,
    load_messages_json,
    parse_channel_config,
)
from discord_mcp_collect import McpClient, parse_active_threads, parse_messages_text  # noqa: E402


class ConfigStub:
    run_source = "test"
    timezone = "America/Los_Angeles"


def msg(
    message_id: str,
    content: str,
    channel_name: str = "dev-chat",
    area_hint: str | None = None,
) -> DiscordMessage:
    return DiscordMessage(
        id=message_id,
        channel_id="111",
        guild_id="999",
        channel_name=channel_name,
        author_name="Daniel",
        content=content,
        timestamp=dt.datetime(2026, 6, 26, 20, 0, tzinfo=dt.timezone.utc),
        link=f"https://discord.com/channels/999/111/{message_id}",
        area_hint=area_hint,
    )


class DigestTests(unittest.TestCase):
    def test_filters_low_signal_chatter(self):
        signals = meaningful_signals(
            [
                msg("1", "ok"),
                msg("2", "Can someone review the Render deploy failure? It is blocking prod."),
            ],
            ignore_bots=True,
            already_seen=set(),
            max_items=5,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].area, "Dev")
        self.assertIn("Feedback requested", signals[0].outcomes)
        self.assertIn("Blocker", signals[0].outcomes)

    def test_builds_notion_properties(self):
        signals = meaningful_signals(
            [msg("2", "We decided to use this landing page offer for the Meta ads test.")],
            ignore_bots=True,
            already_seen=set(),
            max_items=5,
        )
        digest = build_digest(
            "Hourly",
            signals,
            dt.datetime(2026, 6, 26, 19, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 6, 26, 20, 0, tzinfo=dt.timezone.utc),
            ConfigStub(),
        )
        props = notion_properties(digest)
        self.assertEqual(props["Status"]["select"]["name"], "Published")
        self.assertEqual(props["Cadence"]["select"]["name"], "Hourly")
        self.assertEqual(props["Source message IDs"]["rich_text"][0]["text"]["content"], "2")
        self.assertEqual(props["Signal count"]["number"], 1)

    def test_channel_config_accepts_area_metadata(self):
        channels = parse_channel_config(
            {
                "channels": [
                    {
                        "id": "111",
                        "name": "growth",
                        "area": "Marketing",
                        "include_threads": False,
                        "read_parent": False,
                    }
                ]
            }
        )
        self.assertEqual(channels[0].id, "111")
        self.assertEqual(channels[0].area, "Marketing")
        self.assertFalse(channels[0].include_threads)
        self.assertFalse(channels[0].read_parent)

    def test_area_hint_wins_when_content_is_ambiguous(self):
        area, score = classify_area("Need review on this today", "Business")
        self.assertEqual(area, "Business")
        self.assertGreaterEqual(score, 2)

    def test_signal_uses_channel_area_hint(self):
        signals = meaningful_signals(
            [msg("3", "Can someone review this?", area_hint="Marketing")],
            ignore_bots=True,
            already_seen=set(),
            max_items=5,
        )
        self.assertEqual(signals[0].area, "Marketing")

    def test_message_json_can_fill_link_and_area_hint(self):
        message = discord_message_from_json(
            {
                "id": "123",
                "channel_id": "456",
                "guild_id": "789",
                "channel_name": "growth",
                "author_name": "Neel",
                "content": "Can someone review the launch copy?",
                "timestamp": "2026-06-26T20:00:00Z",
                "area": "Marketing",
            }
        )
        self.assertEqual(message.area_hint, "Marketing")
        self.assertEqual(message.link, "https://discord.com/channels/789/456/123")

    def test_load_messages_json_accepts_wrapped_payload(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            json.dump(
                {
                    "messages": [
                        {
                            "id": "123",
                            "channel_id": "456",
                            "guild_id": "789",
                            "content": "We decided to ship this pricing test.",
                            "timestamp": "2026-06-26T20:00:00Z",
                        }
                    ]
                },
                handle,
            )
            path = handle.name
        try:
            messages = load_messages_json(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "123")

    def test_mcp_message_parser_ignores_header_text(self):
        text = (
            "**Retrieved 1 messages:**\n"
            "- (ID: 123) **[Neel]** `2026-06-26T20:00:00Z`: "
            "```Can someone review the launch copy?```"
        )
        messages = parse_messages_text(text, "789", "456", "growth", "Marketing")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["area_hint"], "Marketing")
        self.assertEqual(messages[0]["link"], "https://discord.com/channels/789/456/123")

    def test_mcp_thread_parser_extracts_active_threads(self):
        threads = parse_active_threads("- launch-plan (ID: 222) in #growth")
        self.assertEqual(threads, [{"name": "launch-plan", "id": "222", "parent": "growth"}])

    def test_mcp_connecting_state_is_operational_failure(self):
        class ClientStub(McpClient):
            def __init__(self):
                pass

            def request(self, method, params):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "Discord client is still connecting; retry shortly.",
                        }
                    ]
                }

        with self.assertRaisesRegex(RuntimeError, "still connecting"):
            ClientStub().call_tool("list_channels", {})

    def test_mcp_rest_invalid_json_is_operational_failure(self):
        class ClientStub(McpClient):
            def __init__(self):
                pass

            def request(self, method, params):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "Discord REST returned invalid JSON: <html>rate limited</html>",
                        }
                    ]
                }

        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            ClientStub().call_tool("list_channels_rest", {})

    def test_daily_dedupe_only_checks_prior_daily_rows(self):
        class NotionStub:
            def __init__(self):
                self.calls = []

            def recent_source_ids(self, since, cadence=None):
                self.calls.append((since, cadence))
                return {"123"}

        now = dt.datetime(2026, 6, 26, 20, 0, tzinfo=dt.timezone.utc)
        stub = NotionStub()
        self.assertEqual(dedupe_source_ids(stub, "Daily", now), {"123"})
        self.assertEqual(stub.calls[0][1], "Daily")

    def test_hourly_dedupe_checks_all_recent_rows(self):
        class NotionStub:
            def __init__(self):
                self.calls = []

            def recent_source_ids(self, since, cadence=None):
                self.calls.append((since, cadence))
                return {"123"}

        now = dt.datetime(2026, 6, 26, 20, 0, tzinfo=dt.timezone.utc)
        stub = NotionStub()
        self.assertEqual(dedupe_source_ids(stub, "Hourly", now), {"123"})
        self.assertIsNone(stub.calls[0][1])


if __name__ == "__main__":
    unittest.main()
