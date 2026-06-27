# Deployment Status

## Ready

- Notion target: `collection://387036fe-b310-80e1-bb4a-000b910c600b`
- Discord guild: `1390121727526305882` (`dolphin - sat/act prep`)
- Channel config: `channels.dolphin.json`
- Hosted Render cron:
  - `dolphin-discord-notion-digest`
  - service id `crn-d8vjofe8bjmc738ca9e0`
  - dashboard `https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0`
  - repo `https://github.com/PaloAI-Inc/discord-mcp`
  - path `discord-notion-digest/`
  - schedule `7 * * * *` UTC
- Digest classifier: Dev, Marketing, and Business signal grouping
- Quiet-run behavior: skips Notion writes when no meaningful signal is found
- Validation:

```bash
DISCORD_GUILD_ID=1390121727526305882 \
DISCORD_CHANNEL_CONFIG_PATH=./channels.dolphin.json \
python3 discord_notion_digest.py --validate-config

python3 -m unittest discover -s tests
```

## Current State

The production path no longer depends on Codex automations or the local laptop.
The hosted Render cron is live and publishing to Notion:

- `DISCORD_BOT_TOKEN` is wired from the existing `discord-mcp-prod`
  `DISCORD_TOKEN` secret through Blueprint `fromService.envVarKey`.
- `NOTION_TOKEN` is set on the Render cron from the Dolphin Labs Notion
  internal integration `Granola Notion Hosted Sync`.
- The Notion integration has access to the `Discord Digest` data source.

Verified current live state:

- Discord env probe `job-d8vk4nbtqb8s73esvilg` succeeded after deploy
  `dep-d8vk4c68bjmc738cmhvg`, confirming `DISCORD_BOT_TOKEN` is available to
  the cron through the existing `discord-mcp-prod` secret.
- Corrected env deploy `dep-d8vlqu68bjmc738eev60` is live.
- Manual run at 2026-06-27 05:21 UTC completed successfully with
  `finished_digest` return code `0`.
- The run created Notion row `Discord Digest - 2026-06-26 05:00 UTC`
  (`38c036fe-b310-818d-8b55-da1540453903`) with status `Published` and
  signal count `5`.

The old Codex automations were deleted:

- `dolphin-discord-digest-hourly`
- `dolphin-discord-digest-daily-glance`
- `retry-dolphin-discord-mcp-readiness`

## Operations

Render service:

- `https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0`

The cron runs hourly at minute 7 UTC. The entrypoint always runs the hourly
digest and also runs the daily digest when the local `America/Los_Angeles` hour
is `23`.

Quiet hourly runs do not create filler rows when no meaningful Discord signal
is found.
