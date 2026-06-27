# Activation

The hosted Render cron is already deployed:

- Service: `dolphin-discord-notion-digest`
- Service ID: `crn-d8vjofe8bjmc738ca9e0`
- Dashboard: <https://dashboard.render.com/cron/crn-d8vjofe8bjmc738ca9e0>

Add these environment variables in Render. Do not commit them or paste them in
chat.

```text
DISCORD_BOT_TOKEN=<Discord bot token with message history access>
NOTION_TOKEN=<Notion internal integration secret with Discord Digest access>
```

After saving the variables, trigger a manual run in Render. The cron then runs
every hour at minute 7 UTC. The same hourly process also writes the daily glance
when the local `America/Los_Angeles` hour is `23`.

Current verification:

- Latest hosted deploy is live on commit `73295b5`.
- A no-secret env probe job, `job-d8vjsq8k1i2s73eqb7g0`, failed because at
  least one required secret is missing.
- No local Codex automation is active for this workflow.
