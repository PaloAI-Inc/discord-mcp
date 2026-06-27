# Granola to Notion Hosted Sync

This is a deploy-ready skeleton for moving the current laptop-bound sync into a cloud cron job.

It polls Granola, filters for Palo/company meetings, checks the existing Notion database by `Granola Meeting ID` or the Granola URL, and creates a readable Notion page with:

- What changed
- Decisions
- Open questions
- Next actions
- Why it matters
- People
- Date
- One small Granola link

## Recommended hosted target

Use a Render Cron Job or any serverless cron that can run Node 20:

```bash
node worker.mjs
```

Run it every 30-60 minutes. That is usually enough for meeting-note sync without creating noisy duplicate writes.

The worker uses Granola's public API at `https://public-api.granola.ai/v1`.
On Render, use `npm test` as the build command and `node worker.mjs` as the start command.

The readout extraction is intentionally biased toward useful async catch-up:

- First it reads explicit Granola summary sections like `Decisions`, `Open questions`, `Next steps`, and `Why it matters`.
- If those sections are missing, it falls back to conservative inference from decision/action/question language.
- If a meeting has no clear decision/action/question, it says that plainly instead of inventing one.

## Required environment variables

```bash
GRANOLA_API_KEY=...
NOTION_API_KEY=...
NOTION_DATABASE_ID=385036feb31080499dfccabfe8c0b533
```

## Strongly recommended environment variables

```bash
GRANOLA_FOLDER_NAME=Palo meeting Series
SYNC_CREATED_AFTER=2026-01-01T00:00:00Z
MEETING_TITLE_ALLOW_REGEX=palo|team|product|roadmap|launch|practice|question|web|ios|fundraising|investor|growth|marketing|retention|onboarding|streak|vocab|dashboard
```

Use `GRANOLA_FOLDER_NAME` when Granola keeps the Palo/company meeting series in a dedicated folder. The worker resolves the folder ID at runtime. If multiple folders have the same name, set `GRANOLA_FOLDER_ID` instead.

## Optional environment variables

```bash
DRY_RUN=true
NOTION_VERSION=2022-06-28
```

`DRY_RUN=true` prints what would be created without writing to Notion.

## Local verification

```bash
node --check worker.mjs
node test-worker.mjs
```

After setting real credentials, run a no-write access check before enabling the scheduled job:

```bash
npm run validate
```

This validates Granola listing, folder resolution, one note-detail fetch, Notion database query access, and the duplicate-check query without creating Notion pages.

## Deployment notes

- Native Granola -> Notion export is cloud-hosted, but Granola documents it as a per-note export flow and explicitly says automatic sync and bulk export are not currently supported.
- Zapier is viable if Granola notes are routed into a folder. Use the Granola "new note added to folder" trigger, then create a Notion database page.
- This worker is the most controllable path if you need exactly the custom fields and page body format already created in Dolphin Brain.
- The code intentionally does not include secrets. It cannot be run or deployed until `GRANOLA_API_KEY` and `NOTION_API_KEY` are available in the cloud environment.
- The planned Render service is `granola-notion-hosted-sync` in the Dolphin Render workspace, region `ohio`, starter cron plan, schedule `*/30 * * * *`.

## Relevant Granola docs

- API overview: https://docs.granola.ai/introduction
- List notes: https://docs.granola.ai/api-reference/list-notes
- Get note: https://docs.granola.ai/api-reference/get-note
- Zapier: https://docs.granola.ai/help-center/sharing/integrations/zapier
- Notion export: https://docs.granola.ai/help-center/sharing/notion

## Current Notion target

- Meetings page: https://app.notion.com/p/7ec29c5d7ab14055925f090c073a5328
- Meeting Readouts page: https://app.notion.com/p/38c036feb31081c28e64c43566d2c528
- Meeting Notes database: `385036feb31080499dfccabfe8c0b533`
- Data source currently used by the MCP connector: `collection://385036fe-b310-80ff-bc61-000b726ec514`
