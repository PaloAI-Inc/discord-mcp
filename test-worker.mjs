import assert from "node:assert/strict";

import { buildNotionDuplicateFilter, buildReadout, normalizeFolderName } from "./worker.mjs";

const note = {
  id: "not_test12345678",
  title: "Palo meeting - Web launch readout",
  created_at: "2026-06-26T18:30:00Z",
  web_url: "https://notes.granola.ai/d/f3e45e0f-24cc-480b-9a6c-8b1f5e3d7a2c",
  attendees: [
    { name: "Neel Shettigar", email: "neel@paloai.co" },
    { name: "Daniel", email: "daniel@paloai.co" },
    { name: "Torgeir", email: "torgeir@paloai.co" },
  ],
  summary_markdown: `## What changed
The web launch plan moved from exploration to a gated practice-test rollout.

## Decisions
- Gate practice tests for unpaid users while leaving Learn open.
- Use PostHog feature flags for the paid-access experiment.
- Keep the Granola link low prominence in Notion.

## Open questions
- Does open Learn access improve conversion or reduce urgency?
- Which practice-test bugs should block the launch?

## Next steps
- Daniel will confirm tracking in PostHog.
- Neel will QA payment gating in staging.

## Why it matters
This ties meeting catch-up to launch decisions instead of vague summaries.`,
};

const readout = buildReadout(note, "f3e45e0f-24cc-480b-9a6c-8b1f5e3d7a2c");

assert.equal(readout.title, "Jun 26 - Web launch readout");
assert.equal(readout.people, "Neel, Daniel, Torgeir");
assert.deepEqual(readout.decisions, [
  "Gate practice tests for unpaid users while leaving Learn open.",
  "Use PostHog feature flags for the paid-access experiment.",
  "Keep the Granola link low prominence in Notion.",
]);
assert.deepEqual(readout.openQuestions, [
  "Does open Learn access improve conversion or reduce urgency?",
  "Which practice-test bugs should block the launch?",
]);
assert.deepEqual(readout.nextActions, [
  "Daniel will confirm tracking in PostHog.",
  "Neel will QA payment gating in staging.",
]);
assert.equal(
  readout.whyItMatters,
  "This ties meeting catch-up to launch decisions instead of vague summaries.",
);
assert.equal(readout.granolaUrl, "https://notes.granola.ai/d/f3e45e0f-24cc-480b-9a6c-8b1f5e3d7a2c");
assert.equal(normalizeFolderName(" Palo   meeting Series "), "palo meeting series");
assert.deepEqual(buildNotionDuplicateFilter(readout), {
  or: [
    {
      property: "Granola Meeting ID",
      rich_text: {
        equals: "f3e45e0f-24cc-480b-9a6c-8b1f5e3d7a2c",
      },
    },
    {
      property: "Granola",
      url: {
        equals: "https://notes.granola.ai/d/f3e45e0f-24cc-480b-9a6c-8b1f5e3d7a2c",
      },
    },
  ],
});

console.log("worker parser fixture passed");
