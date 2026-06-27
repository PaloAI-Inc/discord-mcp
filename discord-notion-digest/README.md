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

For production, use the hosted Render cron below. The MCP collector remains as
a local diagnostic path only.

Suggested schedules:

- Hourly: run at minute 7 of every hour.
- Daily: run once per day after the team's active day ends.

The job uses a 75-minute hourly lookback and writes `Source message IDs`, so an
overlapping scheduler window does not need persistent local disk state.

## Render

The production hosted cron is:

- Service: `dolphin-discord-notion-digest`
- Service ID: `crn-d8vjofe8bjmc738ca9e0`
- Dashboard: <https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0>
- Repo: <https://github.com/PaloAI-Inc/discord-mcp>
- Path: `discord-notion-digest/`
- Region: Ohio
- Schedule: `7 * * * *` UTC

The cron runs `python3 run_render_cron.py` hourly. That entrypoint always runs
the hourly digest and also runs the daily glance when the local
`America/Los_Angeles` hour is `23`.

The service is live. `DISCORD_BOT_TOKEN` is wired from the existing
`discord-mcp-prod` service through the Render Blueprint, and `NOTION_TOKEN` is
set on the cron from the Dolphin Labs Notion internal integration
`Granola Notion Hosted Sync`.

Activation was verified by manual Render run at 2026-06-27 05:21 UTC. The run
created `Discord Digest - 2026-06-26 05:00 UTC` in Notion with status
`Published` and signal count `5`.
