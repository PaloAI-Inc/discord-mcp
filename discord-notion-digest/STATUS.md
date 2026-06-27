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

## Current Blocker

The production path no longer depends on Codex automations or the local laptop.
The hosted Render cron is live and safe-idles until required secrets are
available:

- `DISCORD_BOT_TOKEN` is wired from the existing `discord-mcp-prod`
  `DISCORD_TOKEN` secret through Blueprint `fromService.envVarKey`.
- `NOTION_TOKEN` still needs to be added in the Render dashboard.

Until those are present, `run_render_cron.py` exits with
`waiting_for_secrets` and does not publish anything.

Verified current secret state:

- Manual digest job `job-d8vjrrjsq97s738eell0` succeeded quickly, but no new
  `Discord Digest` row appeared.
- Env-presence probe job `job-d8vjsq8k1i2s73eqb7g0` failed with a command that
  exits non-zero unless both `DISCORD_BOT_TOKEN` and `NOTION_TOKEN` are present.
- Therefore at least one required Render secret is still missing. After the
  Discord secret wiring deploy, the expected remaining manual secret is
  `NOTION_TOKEN`.

The old Codex automations were deleted:

- `dolphin-discord-digest-hourly`
- `dolphin-discord-digest-daily-glance`
- `retry-dolphin-discord-mcp-readiness`

## Activation Path

Add the two secrets to the Render cron service:

- Render service: `https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0`
- Environment variable:
  - `NOTION_TOKEN`

Then trigger a manual run from Render. The cron runs hourly at minute 7 UTC.
The entrypoint always runs the hourly digest and also runs the daily digest when
the local `America/Los_Angeles` hour is `23`.

The direct script writes to Notion using the Notion API, so it needs an actual
Notion integration secret with access to the `Discord Digest` data source.
