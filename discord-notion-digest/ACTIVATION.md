# Activation

The hosted Render cron is already deployed:

- Service: `dolphin-discord-notion-digest`
- Service ID: `crn-d8vjofe8bjmc738ca9e0`
- Dashboard: <https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0>

`DISCORD_BOT_TOKEN` is wired from the existing `discord-mcp-prod`
`DISCORD_TOKEN` Render secret through Blueprint `fromService.envVarKey`, so it
does not need to be pasted or copied.

Add this environment variable in Render. Do not commit it or paste it in chat.

```text
NOTION_TOKEN=<Notion internal integration secret with Discord Digest access>
```

After saving the variables, trigger a manual run in Render. The cron then runs
every hour at minute 7 UTC. The same hourly process also writes the daily glance
when the local `America/Los_Angeles` hour is `23`.

Current verification:

- Latest hosted deploy is live on commit `73295b5`.
- A no-secret env probe job, `job-d8vjsq8k1i2s73eqb7g0`, failed because at
  least one required secret is missing. After the Discord secret wiring deploy,
  the remaining expected manual secret is `NOTION_TOKEN`.
- No local Codex automation is active for this workflow.
