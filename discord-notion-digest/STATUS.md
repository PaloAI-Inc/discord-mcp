# Deployment Status

## Ready

- Notion target: `collection://387036fe-b310-80e1-bb4a-000b910c600b`
- Discord guild: `1390121727526305882` (`dolphin - sat/act prep`)
- Channel config: `channels.dolphin.json`
- Saved paused Codex automations:
  - `dolphin-discord-digest-hourly`
  - `dolphin-discord-digest-daily-glance`
- Saved follow-up heartbeat:
  - `retry-dolphin-discord-mcp-readiness`
- Digest classifier: Dev, Marketing, and Business signal grouping
- Quiet-run behavior: skips Notion writes when no meaningful signal is found
- Validation:

```bash
DISCORD_GUILD_ID=1390121727526305882 \
DISCORD_CHANNEL_CONFIG_PATH=./channels.dolphin.json \
python3 discord_notion_digest.py --validate-config

python3 -m unittest discover -s tests
```

## Current Blocker

The existing Dolphin Render service `discord-mcp-prod`
(`srv-d8rn5s6gvqtc73f97f90`) is now HTTP/MCP healthy and configured for
REST-only digest reads, but Discord REST is still waiting on Discord
Cloudflare rate limiting:

- Pushed `bb430c2` to `PaloAI-Inc/discord-mcp` to avoid blocking Spring HTTP
  startup on Discord gateway readiness and to fix the Docker healthcheck port.
- Pushed `713e430` to lazy-start the JDA Discord client in the background so
  Tomcat can bind its port while Discord is still connecting.
- Pushed `cad285d` / `69cde3b` to add REST-backed MCP read tools:
  `read_messages_rest`, `list_active_threads_rest`, and `list_channels_rest`.
- Pushed `e66dbdc` to preserve Discord REST error previews in MCP tool output.
- Pushed `8057328` to disable Discord gateway startup by default in the Docker
  image (`DISCORD_GATEWAY_ENABLED=false`), so the digest path does not keep
  extending Discord gateway login rate limits.
- Canceled superseded deploy `dep-d8vj1dojo6nc73c4gg30`.
- Render deploy `dep-d8vjg1jbc2fs738up6vg` is live.
- `https://discord-mcp-prod.onrender.com/actuator/health` returns `UP`.
- MCP `initialize` succeeds.
- Gateway-backed Discord tools now return: `Discord gateway is disabled; use
  REST-backed tools.`
- REST-backed Discord tools currently return: `Discord REST returned invalid
  JSON: error code: 1015`.
- Render logs showed Discord Cloudflare `Retry-After: 57666 s` at
  `2026-06-27T02:37:30Z` during the prior gateway startup. The latest
  REST-only startup did not show a new JDA Cloudflare hit.

Do not activate hourly/daily jobs until REST-backed Discord tool calls succeed,
or move the collector to a runtime/IP path that is not Cloudflare-rate-limited.
A direct Render cron with valid `DISCORD_BOT_TOKEN` and `NOTION_TOKEN` secrets
is the alternate production path.

## Activation Path

Preferred no-raw-Discord-token path:

```bash
export DISCORD_GUILD_ID=1390121727526305882
export DISCORD_CHANNEL_CONFIG_PATH=./channels.dolphin.json

python3 discord_mcp_collect.py \
  --guild-id "$DISCORD_GUILD_ID" \
  --lookback-minutes 75 \
  --out messages.json

python3 discord_notion_digest.py \
  --cadence Hourly \
  --messages-json messages.json \
  --dry-run
```

If that publishes signal in dry-run, turn on the Codex hourly and daily Notion
automations using the Notion connector to write only published non-quiet
digests.

Direct Render cron path:

- Store `DISCORD_BOT_TOKEN` and `NOTION_TOKEN` as Render secrets.
- Set `DISCORD_GUILD_ID=1390121727526305882`.
- Set `DISCORD_CHANNEL_CONFIG_PATH=./channels.dolphin.json` or inline
  `DISCORD_CHANNEL_CONFIG_JSON`.
- Run `python3 discord_notion_digest.py --cadence Hourly` hourly and
  `python3 discord_notion_digest.py --cadence Daily` daily.
