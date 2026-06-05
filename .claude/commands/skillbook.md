---
description: Generate a personalized SkillBook — a book-length learning PDF — with Claude Code as the author (no API key).
argument-hint: [topic or roadmap you want to learn]
---

You are running **SkillBook in Claude Code mode**. In this mode *you* are the author of the
book — you do all the writing yourself, and you call the project's Python helpers only for the
deterministic work (real-link search and PDF rendering). No Anthropic API key is involved.

The user wants a personalized, book-length learning PDF on: **$ARGUMENTS**
(If that is empty, ask them what they want to learn before continuing.)

Produce a genuinely useful, *extensive* book — not a summary — tailored to this specific learner.

---

## How to run the helper (`skillbook`)

All helper calls go through the project's Python. Prefer the project virtualenv:

- Windows: `.\.venv\Scripts\python.exe -m skillbook <args>`
- macOS/Linux: `./.venv/bin/python -m skillbook <args>`

If `.venv` is missing or `... -m skillbook --help` fails, set it up once:
`python -m venv .venv` → activate it → `pip install -e .` → `playwright install chromium`.

The helpers you'll use: `scaffold`, `search`, `build`. They need NO API key.

---

## Workflow

### 1. Learner profile
Read `~/.skillbook/profile.json` if it exists (use it). Otherwise ask the user a few quick
questions and remember the answers for this run: background, current level
(beginner/intermediate/advanced), goals, how they learn best, time budget, and preferred
register (casual or scientific).

### 2. Topic interview (brief)
Confirm/ask: what they already know about this topic, the outcome they want (job, project,
exam, curiosity), anything that MUST be covered or skipped, the **depth**
(`primer` ≈ 4–6 chapters · `standard` ≈ 7–10 · `comprehensive` ≈ 12–18), and the **register**
(`casual` = warm, second-person, analogies · `scientific` = precise, third-person, structured).

### 3. Scaffold the run
Run: `... -m skillbook scaffold --topic "<topic>" --style <casual|scientific>`
Note the printed run directory (e.g. `runs/<id>/`). You will fill it in.

### 4. Plan the outline → get approval
Design a coherent, personalized table of contents: order chapters prerequisites-first so the
book reads as one arc; calibrate the starting point to the learner's level; honor must-cover/skip.
Edit `runs/<id>/book.json` and set `title`, `subtitle`, and `chapters` as a list of
`{"id": "ch01", "title": "..."}` (ids `ch01`, `ch02`, … in order).
**Show the TOC to the user and get approval (or edits) before drafting.**

### 5. Draft the chapters
For each chapter write `runs/<id>/chapters/<id>.md` as **extensive Markdown**:
- Open with a specific motivation (no generic "In this chapter we will…").
- Use `##` for sections and `###` for sub-parts. **Do NOT add an H1 title** — it is added automatically.
- Where the topic is technical, include at least one `### Worked example` with a fenced code block and a walk-through.
- Include a `### Exercises` section (2–4 hands-on tasks or a mini-project).
- Include a `### Quiz` (2–4 questions) followed by a bold `**Answers:**` block.
- Match the chosen register, write at the learner's level, and **build on earlier chapters without repeating them**.
- **Never write a URL or citation here** — resources are attached in the next step.

### 6. Attach verified resources (provenance-first — important)
For each chapter, think of 2–3 search queries, then run:
`... -m skillbook search "<query 1>" "<query 2>" --limit 6`
This prints a JSON list of **real, reachability-checked** candidate links. Choose the best 3–6
(prefer a mix of kinds: doc, course, article, video, book, repo) and write them to
`runs/<id>/chapters/<id>.resources.json` as a list of objects with
`title, url, source, query, kind, status` — copied from the search output.
**Only use URLs that appear in the `skillbook search` output. Never invent, guess, or modify a URL.**

### 7. Render the PDF
Run: `... -m skillbook build runs/<id> --out books/<slug>.pdf`
This assembles your chapters + verified resources into a themed PDF with a Mermaid roadmap and a
bookmarked table of contents.

### 8. Quality-check the PDF
Run: `... -m skillbook verify books/<slug>.pdf`
It reads through the rendered pages and reports the page count plus any **blank / near-empty
pages**. If it flags blank pages, find the offending chapter (usually content far too short for
its own page, or an empty chapter file), fix it, and rebuild. "Low-density" notes about normal
chapter ends are fine to ignore.

### 9. Report
Tell the user the PDF path and a one-line summary (topic, register, chapter count, page count).
Mention they can open the PDF, and that re-running with a different `--style` re-themes the same content.

---

## Guardrails
- **No invented links.** Every URL in the book must come from `skillbook search` output.
- This is a *book*: be thorough, concrete, and pedagogically sound — favor depth over breadth-of-fluff.
- Keep ids consistent: a chapter listed as `ch03` in `book.json` must have `chapters/ch03.md`.
- If `skillbook build` reports a missing chapter file or bad `book.json`, fix the artifact and re-run it.
