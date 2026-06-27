# Discord Notion Digest

Hourly and daily Discord signal digest for the Dolphin Labs Notion workspace.

This job reads recent Discord channel messages and active thread messages, keeps
only meaningful signal, and writes compact pages to the existing Notion
`Discord Digest` data source.

## Destination

- Notion data source: `collection://387036fe-b310-80e1-bb4a-000b910c600b`
- Parent database: <https://app.notion.com/p/387036feb31080faa6d8c137ef04ab86>

## Signal Policy

Include:

- Decisions or direction changes.
- Unanswered questions that block dev, marketing, business, support, or launch work.
- Feedback requests from a named person/team or the whole team.
- Action items, blockers, owner handoffs, or next-step commitments.
- Customer, market, growth, partnership, pricing, funnel, product, or reliability signal.

Omit:

- Chatter, reactions, acknowledgements, jokes, status-only bot noise, repeated links, and raw high-volume report noise.
- Any item without a direct Discord message or thread link.
- Old context unless a newer message changes the decision, owner, urgency, or risk.

## Environment

Use real values in the scheduler or Render environment. Do not commit secrets.

```bash
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=1390121727526305882
DISCORD_CHANNEL_CONFIG_PATH=./channels.dolphin.json
# Or use this instead of DISCORD_CHANNEL_CONFIG_PATH:
# DISCORD_CHANNEL_IDS=111111111111111111,222222222222222222
NOTION_TOKEN=
NOTION_DATA_SOURCE_ID=387036fe-b310-80e1-bb4a-000b910c600b
NOTION_VERSION=2025-09-03
INCLUDE_ACTIVE_THREADS=true
IGNORE_BOTS=true
WRITE_QUIET_RUNS=false
LOOKBACK_MINUTES_HOURLY=75
LOOKBACK_HOURS_DAILY=24
REPORT_TIMEZONE=America/Los_Angeles
RUN_SOURCE=discord-notion-digest
```

Use either `DISCORD_CHANNEL_IDS` or `DISCORD_CHANNEL_CONFIG_PATH`, not both. The
plain channel list works, but the JSON config is preferred because it lets the
job classify each channel as `Dev`, `Marketing`, or `Business` before keyword
fallbacks.

Example channel config:

```json
{
  "channels": [
    {
      "id": "111111111111111111",
      "name": "dev-chat",
      "area": "Dev",
      "include_threads": true
    },
    {
      "id": "222222222222222222",
      "name": "advertisement",
      "area": "Marketing",
      "include_threads": true
    },
    {
      "id": "333333333333333333",
      "name": "business",
      "area": "Business",
      "include_threads": true
    },
    {
      "id": "444444444444444444",
      "name": "forum-or-thread-parent",
      "area": "Business",
      "include_threads": true,
      "read_parent": false
    }
  ]
}
```

## Run

```bash
python3 discord_notion_digest.py --validate-config
python3 discord_notion_digest.py --cadence Hourly --dry-run
python3 discord_notion_digest.py --cadence Hourly
python3 discord_notion_digest.py --cadence Daily
```

## Dolphin Channel Config

The current Dolphin Discord server/channel IDs were read from the logged-in
Discord UI, not from browser tokens:

- Guild: `1390121727526305882` (`dolphin - sat/act prep`)
- Config: `channels.dolphin.json`

Configured sources:

- Dev: `dev-chat`
- Business/customer signal: `intercom-updates`, `general`, `ask-for-help`,
  `math-and-science`, `success`, `college-app-help`, and active `chance-me`
  forum threads.
- Marketing: keyword-driven inside the configured channels unless a dedicated
  marketing channel is added later.

## No-Raw-Discord-Token Mode

The Dolphin Render workspace already has a `discord-mcp-prod` service at
<https://discord-mcp-prod.onrender.com/mcp>. That service owns the Discord bot
token, so this digest can collect through MCP instead of handling the raw
Discord token locally:

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

For a Codex/Notion automation, keep the second command in `--dry-run` mode and
let the Notion connector write only published, non-quiet digests into
`collection://387036fe-b310-80e1-bb4a-000b910c600b`. That avoids exposing a
Notion integration token to the local script. A standalone Render cron that
writes directly to Notion still needs `NOTION_TOKEN` as a Render secret.

Suggested schedules:

- Hourly: run at minute 7 of every hour.
- Daily: run once per day after the team's active day ends.

The job uses a 75-minute hourly lookback and writes `Source message IDs`, so an
overlapping scheduler window does not need persistent local disk state.

## Render

The existing Dolphin Render service discovered for Discord is:

- Service: `discord-mcp-prod`
- Service ID: `srv-d8rn5s6gvqtc73f97f90`
- URL: <https://discord-mcp-prod.onrender.com>
- MCP endpoint: <https://discord-mcp-prod.onrender.com/mcp>

Current operational caveat: `discord-mcp-prod` is HTTP/MCP healthy after commit
`8057328`, and the deployed Docker image now defaults to
`DISCORD_GATEWAY_ENABLED=false` so digest reads do not start the JDA gateway.
Health returns `UP` and MCP `initialize` succeeds. Gateway tools intentionally
return `Discord gateway is disabled; use REST-backed tools.`

REST-backed Discord read tools are deployed, but Discord currently returns
Cloudflare `1015` to Render. The last gateway startup before REST-only mode
logged `Retry-After: 57666 s` at `2026-06-27T02:37:30Z`; the REST-only startup
did not show a new JDA Cloudflare hit. Do not activate hourly/daily Notion
writes until `list_channels_rest` or `read_messages_rest` succeeds.

Production activation needs either the Discord rate-limit window to clear on
this Render IP/token path, a runtime/IP path that is not Cloudflare-rate-limited,
or a direct Render cron that has valid `DISCORD_BOT_TOKEN` and `NOTION_TOKEN`
secrets.

Use a cron job with:

```bash
python3 discord_notion_digest.py --cadence Hourly
```

and a second daily cron job with:

```bash
python3 discord_notion_digest.py --cadence Daily
```
