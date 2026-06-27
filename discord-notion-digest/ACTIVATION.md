# Activation

The hosted Render cron is deployed and active:

- Service: `dolphin-discord-notion-digest`
- Service ID: `crn-d8vjofe8bjmc738ca9e0`
- Dashboard: <https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0>

`DISCORD_BOT_TOKEN` is wired from the existing `discord-mcp-prod`
`DISCORD_TOKEN` Render secret through Blueprint `fromService.envVarKey`, so it
does not need to be pasted or copied.

`NOTION_TOKEN` is set on the Render cron from the Dolphin Labs Notion internal
integration `Granola Notion Hosted Sync`. That integration has access to the
`Discord Digest` data source.

The cron runs every hour at minute 7 UTC. The same hourly process also writes
the daily glance when the local `America/Los_Angeles` hour is `23`.

Current verification:

- Latest hosted commit is `512482d`.
- Corrected env deploy `dep-d8vlqu68bjmc738eev60` is live.
- Discord env probe `job-d8vk4nbtqb8s73esvilg` succeeded, confirming the cron
  can read `DISCORD_BOT_TOKEN` from the existing `discord-mcp-prod` service.
- Local Notion create/archive smoke test returned `200`/`200`.
- Manual Render run at 2026-06-27 05:21 UTC completed with `finished_digest`
  return code `0`.
- Notion row `Discord Digest - 2026-06-26 05:00 UTC`
  (`38c036fe-b310-818d-8b55-da1540453903`) was created with status
  `Published` and signal count `5`.
- No local Codex automation is active for this workflow.
