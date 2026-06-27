import { pathToFileURL } from "node:url";

const GRANOLA_API_BASE = process.env.GRANOLA_API_BASE || "https://public-api.granola.ai/v1";
const GRANOLA_API_KEY = process.env.GRANOLA_API_KEY || "";
const NOTION_API_KEY = process.env.NOTION_API_KEY || "";
const NOTION_DATABASE_ID = process.env.NOTION_DATABASE_ID || "";
const NOTION_VERSION = process.env.NOTION_VERSION || "2022-06-28";
const GRANOLA_FOLDER_ID = process.env.GRANOLA_FOLDER_ID || "";
const GRANOLA_FOLDER_NAME = process.env.GRANOLA_FOLDER_NAME || "";
const SYNC_CREATED_AFTER = process.env.SYNC_CREATED_AFTER || "2026-01-01T00:00:00Z";
const TITLE_ALLOW = new RegExp(
  process.env.MEETING_TITLE_ALLOW_REGEX ||
    "palo|team|product|roadmap|launch|practice|question|web|ios|fundraising|investor|growth|marketing|retention|onboarding|streak|vocab|dashboard",
  "i",
);
const DRY_RUN = process.env.DRY_RUN === "true";
const VALIDATE_ONLY = process.env.VALIDATE_ONLY === "true" || process.argv.includes("--validate");

async function main() {
  requireRuntimeConfig();

  const folderId = await resolveGranolaFolderId();
  const notes = await listGranolaNotes(folderId);
  const candidates = notes.filter((note) => shouldSyncNote(note, folderId));

  console.log(`Granola notes found: ${notes.length}`);
  if (folderId) console.log(`Granola folder filter: ${folderId}`);
  console.log(`Candidate notes after filtering: ${candidates.length}`);

  if (VALIDATE_ONLY) {
    await validateRuntimeAccess(candidates);
    return;
  }

  let created = 0;
  let skipped = 0;

  for (const summary of candidates) {
    const note = await getGranolaNote(summary.id);
    const granolaKey = granolaStableKey(note);

    if (!granolaKey) {
      console.warn(`Skipping note without stable key: ${summary.id}`);
      skipped += 1;
      continue;
    }

    const readout = buildReadout(note, granolaKey);

    if (await notionPageExists(readout)) {
      skipped += 1;
      continue;
    }

    if (DRY_RUN) {
      console.log(`[dry-run] would create: ${readout.title} (${granolaKey})`);
      created += 1;
      continue;
    }

    await createNotionMeetingPage(readout);
    created += 1;
  }

  console.log(`Done. Created=${created}, skipped=${skipped}`);
}

async function validateRuntimeAccess(candidates) {
  await notionFetch(`/databases/${NOTION_DATABASE_ID}/query`, {
    method: "POST",
    body: JSON.stringify({ page_size: 1 }),
  });
  console.log("Notion database query: ok");

  if (!candidates.length) {
    console.log("No candidate Granola notes found for detail validation.");
    return;
  }

  const note = await getGranolaNote(candidates[0].id);
  const granolaKey = granolaStableKey(note);
  if (!granolaKey) throw new Error("Granola note detail did not include a stable note key.");

  await notionPageExists(buildReadout(note, granolaKey));
  console.log("Granola note detail and Notion duplicate check: ok");
}

async function resolveGranolaFolderId() {
  if (GRANOLA_FOLDER_ID) return GRANOLA_FOLDER_ID;
  if (!GRANOLA_FOLDER_NAME) return "";

  const folders = await listGranolaFolders();
  const normalizedTarget = normalizeFolderName(GRANOLA_FOLDER_NAME);
  const matches = folders.filter((folder) => normalizeFolderName(folder.name) === normalizedTarget);

  if (matches.length === 1) return matches[0].id;
  if (matches.length > 1) {
    console.warn(
      `Multiple Granola folders named "${GRANOLA_FOLDER_NAME}" found; using ${matches[0].id}.`,
    );
    return matches[0].id;
  }

  console.warn(`Granola folder "${GRANOLA_FOLDER_NAME}" not found; falling back to title filter.`);
  return "";
}

async function listGranolaFolders() {
  const folders = [];
  let cursor = "";

  do {
    const params = new URLSearchParams();
    params.set("page_size", "30");
    if (cursor) params.set("cursor", cursor);

    const result = await granolaFetch(`/folders?${params.toString()}`);
    folders.push(...(result.folders || []));
    cursor = result.hasMore ? result.cursor || "" : "";
  } while (cursor);

  return folders;
}

async function listGranolaNotes(folderId = "") {
  const notes = [];
  let cursor = "";

  do {
    const params = new URLSearchParams();
    params.set("page_size", "30");
    if (folderId) params.set("folder_id", folderId);
    if (SYNC_CREATED_AFTER) params.set("created_after", SYNC_CREATED_AFTER);
    if (cursor) params.set("cursor", cursor);

    const result = await granolaFetch(`/notes?${params.toString()}`);
    notes.push(...(result.notes || []));
    cursor = result.hasMore ? result.cursor || "" : "";
  } while (cursor);

  return notes;
}

async function getGranolaNote(id) {
  return granolaFetch(`/notes/${encodeURIComponent(id)}?include=transcript`);
}

function shouldSyncNote(note, folderId = "") {
  const createdAt = note.created_at || note.start_time || note.started_at || "";
  if (SYNC_CREATED_AFTER && createdAt && new Date(createdAt) < new Date(SYNC_CREATED_AFTER)) {
    return false;
  }

  if (folderId) return true;

  const title = note.title || note.name || "";
  return TITLE_ALLOW.test(title);
}

function normalizeFolderName(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function granolaStableKey(note) {
  const url = note.url || note.web_url || note.granola_url || "";
  const match = url.match(/\/d\/([^/?#]+)/);
  return match?.[1] || note.id || note.note_id || "";
}

function buildReadout(note, granolaKey) {
  const title = note.title || note.name || note.calendar_event?.event_title || "Untitled Granola note";
  const date =
    note.calendar_event?.scheduled_start_time ||
    note.start_time ||
    note.started_at ||
    note.created_at ||
    new Date().toISOString();
  const people = firstNames(
    note.attendees?.length ? note.attendees : note.people || note.calendar_event?.invitees || [],
  );
  const granolaUrl = note.url || note.web_url || `https://notes.granola.ai/d/${granolaKey}`;
  const summaryMarkdown = note.summary_markdown || note.summary || note.summary_text || note.notes || "";
  const summary = stripMarkdown(summaryMarkdown);
  const sections = parseMarkdownSections(summaryMarkdown);

  const decisions =
    extractSectionBullets(sections, [/decision/i, /decided/i, /outcome/i, /alignment/i, /agreed/i]) ||
    inferBullets(summaryMarkdown, [
      /\bdecided\b/i,
      /\bagreed\b/i,
      /\baligned\b/i,
      /\bapproved\b/i,
      /\bchose\b/i,
      /\bwill\b/i,
      /\bowner\b/i,
      /\bprioriti[sz]e/i,
    ]) || ["No clear decision captured in Granola summary."];

  const openQuestions =
    extractSectionBullets(sections, [/open questions?/i, /unanswered/i, /unresolved/i, /unknowns?/i]) ||
    inferOpenQuestions(summaryMarkdown) || ["No clear open questions captured in Granola summary."];

  const nextActions =
    extractSectionBullets(sections, [/action/i, /next steps?/i, /follow.?ups?/i, /todos?/i]) ||
    inferBullets(summaryMarkdown, [
      /\baction\b/i,
      /\bfollow up\b/i,
      /\bnext\b/i,
      /\bneeds? to\b/i,
      /\bwill\b/i,
      /\bowner\b/i,
      /\bassigned\b/i,
    ]) || ["No clear next actions captured in Granola summary."];

  return {
    title: normalizeTitle(title, date),
    date,
    people,
    granolaKey,
    granolaUrl,
    whatChanged: extractWhatChanged(sections, summary) || "Meeting note imported from Granola.",
    decisions,
    openQuestions,
    nextActions,
    whyItMatters: inferWhyItMatters(sections, summary),
  };
}

function normalizeTitle(title, date) {
  const d = new Date(date);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const day = d.toLocaleString("en-US", { day: "numeric", timeZone: "UTC" });
  const cleaned = title.replace(/\s+/g, " ").replace(/^palo meeting\s*[-:]?\s*/i, "").trim();
  return `${month} ${day} - ${cleaned || "Meeting"}`;
}

function firstNames(attendees) {
  const names = attendees
    .map((person) => {
      const raw = typeof person === "string" ? person : person.name || person.email || "";
      return raw.split("@")[0].split(/\s+/)[0].replace(/[^A-Za-z-]/g, "");
    })
    .filter(Boolean);
  return Array.from(new Set(names)).join(", ");
}

function parseMarkdownSections(markdown) {
  const sections = [{ heading: "", lines: [] }];

  for (const line of String(markdown || "").split(/\r?\n/)) {
    const heading = line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
    if (heading) {
      sections.push({ heading: heading[1].trim(), lines: [] });
      continue;
    }
    sections[sections.length - 1].lines.push(line);
  }

  return sections;
}

function extractSectionBullets(sections, headingPatterns) {
  const matches = sections.filter((section) =>
    headingPatterns.some((pattern) => pattern.test(section.heading)),
  );
  const items = matches.flatMap((section) => extractItems(section.lines.join("\n")));
  return cleanItems(items);
}

function inferBullets(markdown, linePatterns) {
  const items = extractItems(markdown);
  const matches = items.filter((item) => linePatterns.some((pattern) => pattern.test(item)));
  return cleanItems(matches);
}

function inferOpenQuestions(markdown) {
  const items = extractItems(markdown);
  return cleanItems(items.filter((item) => item.includes("?")));
}

function extractItems(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const bullets = [];
  let paragraph = [];

  for (const line of lines) {
    const trimmed = stripMarkdown(line).trim();
    if (!trimmed) {
      flushParagraph(paragraph, bullets);
      paragraph = [];
      continue;
    }

    const bullet = trimmed.match(/^([-*•]|\d+[.)])\s+(.+)$/);
    if (bullet) {
      flushParagraph(paragraph, bullets);
      paragraph = [];
      bullets.push(bullet[2]);
      continue;
    }

    if (!/^#{1,6}\s+/.test(line)) paragraph.push(trimmed);
  }

  flushParagraph(paragraph, bullets);
  return bullets;
}

function flushParagraph(paragraph, bullets) {
  const text = paragraph.join(" ").trim();
  if (!text) return;

  for (const sentence of text.split(/(?<=[.!?])\s+/)) {
    const cleaned = sentence.trim();
    if (cleaned.length >= 18) bullets.push(cleaned);
  }
}

function cleanItems(items) {
  const cleaned = items
    .map((item) =>
      stripMarkdown(item)
        .replace(/^(decision|decisions|action items?|next steps?|open questions?|questions?)[:\s-]*/i, "")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter(Boolean)
    .filter((item) => !/^none\.?$/i.test(item));

  return cleaned.length ? Array.from(new Set(cleaned)).slice(0, 6) : null;
}

function extractWhatChanged(sections, summary) {
  const explicit =
    extractSectionBullets(sections, [/what changed/i, /summary/i, /overview/i, /context/i])?.[0] ||
    "";
  return explicit || firstSentence(summary);
}

function inferWhyItMatters(sections, summary) {
  const explicit =
    extractSectionBullets(sections, [/why it matters/i, /impact/i, /importance/i, /context/i])?.[0] ||
    "";
  if (explicit) return explicit;
  if (!summary) return "This keeps absent teammates aligned on what changed and what needs follow-up.";
  return firstSentence(summary) || "This keeps absent teammates aligned on what changed and what needs follow-up.";
}

function buildNotionDuplicateFilter(readout) {
  const filters = [];

  if (readout.granolaKey) {
    filters.push({
      property: "Granola Meeting ID",
      rich_text: {
        equals: readout.granolaKey,
      },
    });
  }

  if (readout.granolaUrl) {
    filters.push({
      property: "Granola",
      url: {
        equals: readout.granolaUrl,
      },
    });
  }

  if (!filters.length) throw new Error("Cannot build Notion duplicate filter without a Granola key or URL.");
  return filters.length === 1 ? filters[0] : { or: filters };
}

async function notionPageExists(readout) {
  const body = {
    filter: buildNotionDuplicateFilter(readout),
    page_size: 1,
  };
  const result = await notionFetch(`/databases/${NOTION_DATABASE_ID}/query`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  return result.results?.length > 0;
}

async function createNotionMeetingPage(readout) {
  const properties = {
    "Meeting name": title(readout.title),
    Date: {
      date: {
        start: new Date(readout.date).toISOString(),
      },
    },
    People: richText(readout.people || "Unknown"),
    "What changed": richText(readout.whatChanged),
    Decisions: richText(toBulletText(readout.decisions)),
    "Open questions": richText(toBulletText(readout.openQuestions)),
    "Next actions": richText(toBulletText(readout.nextActions)),
    "Why it matters": richText(readout.whyItMatters),
    Granola: {
      url: readout.granolaUrl,
    },
    "Granola Meeting ID": richText(readout.granolaKey),
    Series: {
      select: {
        name: "Palo meeting",
      },
    },
  };

  const children = [
    paragraph(`People: ${readout.people || "Unknown"}`),
    heading("What changed"),
    paragraph(readout.whatChanged),
    heading("Decisions"),
    ...bullets(readout.decisions),
    heading("Open Questions"),
    ...bullets(readout.openQuestions),
    heading("Next Actions"),
    ...bullets(readout.nextActions),
    heading("Why It Matters"),
    paragraph(readout.whyItMatters),
    paragraphLink("Granola", readout.granolaUrl),
  ];

  await notionFetch("/pages", {
    method: "POST",
    body: JSON.stringify({
      parent: { database_id: NOTION_DATABASE_ID },
      properties,
      children,
    }),
  });
}

async function granolaFetch(path) {
  const response = await fetch(`${GRANOLA_API_BASE}${path}`, {
    headers: {
      Authorization: `Bearer ${GRANOLA_API_KEY}`,
      Accept: "application/json",
    },
  });
  if (!response.ok) throw new Error(`Granola ${response.status}: ${await response.text()}`);
  return response.json();
}

async function notionFetch(path, options = {}) {
  const response = await fetch(`https://api.notion.com/v1${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${NOTION_API_KEY}`,
      "Notion-Version": NOTION_VERSION,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) throw new Error(`Notion ${response.status}: ${await response.text()}`);
  return response.json();
}

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
}

function requireRuntimeConfig() {
  required("GRANOLA_API_KEY");
  required("NOTION_API_KEY");
  required("NOTION_DATABASE_ID");
}

function title(content) {
  return { title: [{ text: { content: truncate(content, 2000) } }] };
}

function richText(content) {
  return { rich_text: [{ text: { content: truncate(content || "", 1900) } }] };
}

function paragraph(content) {
  return {
    object: "block",
    type: "paragraph",
    paragraph: { rich_text: [{ text: { content: truncate(content, 2000) } }] },
  };
}

function paragraphLink(content, url) {
  return {
    object: "block",
    type: "paragraph",
    paragraph: { rich_text: [{ text: { content, link: { url } } }] },
  };
}

function heading(content) {
  return {
    object: "block",
    type: "heading_2",
    heading_2: { rich_text: [{ text: { content } }] },
  };
}

function bullets(items) {
  return items.map((item) => ({
    object: "block",
    type: "bulleted_list_item",
    bulleted_list_item: { rich_text: [{ text: { content: truncate(item, 2000) } }] },
  }));
}

function toBulletText(items) {
  return items.map((item) => `- ${item}`).join("\n");
}

function firstSentence(text) {
  const cleaned = stripMarkdown(text).replace(/\s+/g, " ").trim();
  return cleaned.match(/^(.{20,240}?[.!?])(\s|$)/)?.[1] || cleaned.slice(0, 240);
}

function stripMarkdown(text) {
  return String(text || "")
    .replace(/\[[^\]]+\]\([^)]+\)/g, "")
    .replace(/[#>*_`]/g, "")
    .trim();
}

function truncate(text, length) {
  const value = String(text || "");
  return value.length <= length ? value : `${value.slice(0, length - 1)}…`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}

export {
  buildReadout,
  buildNotionDuplicateFilter,
  parseMarkdownSections,
  extractSectionBullets,
  inferBullets,
  inferOpenQuestions,
  normalizeFolderName,
};
