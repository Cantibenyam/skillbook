# SkillBook — Specification

> **Status:** v0.1 (MVP scope), 2026-06-04
> **Owner:** @imangaliduisebayev
> A Python CLI that turns a learning request (a topic or roadmap) into a personalized,
> book-length **PDF** — written to fit *you*, in a casual or scientific register, with
> exercises, worked examples, quizzes, a visual roadmap, and **verified** further-reading links.

---

## 1. What it is

You describe what you want to learn. SkillBook interviews you (briefly), combines that with a
saved profile of your background and goals, plans a coherent **table of contents**, then writes a
full book chapter by chapter and renders it to a polished PDF. Resource links are gathered from
real search results and reachability-checked — the model is never allowed to invent a URL.

The north star: *the same topic produces a meaningfully different book for a beginner with 3 hrs/week
than for an experienced engineer who wants depth — and both read like a real book, not chatbot output.*

---

## 2. Goals & Non-Goals

### MVP goals (this spec)
- One command produces a valid, attractive `book.pdf` end-to-end from a topic + profile.
- **Personalization:** a persistent profile + a short per-book interview shape every prompt.
- **Two registers** (`casual` / `scientific`) selectable per book — the register steers the writing voice (via prompts) **and** swaps the CSS theme; one pipeline, no code branching.
- **Configurable depth:** `primer` / `standard` (default) / `comprehensive`.
- **Per-chapter content:** explanatory prose + worked examples + hands-on exercises + a self-check quiz (with answers) + a *verified* Further-Reading list.
- **One visual roadmap** diagram (Mermaid) showing how the chapters build on each other.
- **Anti-hallucination resources:** provenance-first — the LLM emits search *queries* and *ranks* real results; it never emits raw URLs. Dead links are dropped.
- **Configurable multi-provider LLM layer** (Anthropic default, OpenAI supported) behind one internal protocol.
- **Checkpoint/resume:** a killed run resumes without re-generating completed chapters.
- **Windows-clean install:** `pip install -e .` + `playwright install chromium`. No MSYS2/GTK/Pango, no Node.js, no Docker.

### Explicit Non-Goals for MVP (quarantined to §13 "Later")
- ❌ WeasyPrint / page-numbered TOC / content-driven running headers (Playwright gives a clickable bookmarked TOC, which is right for an on-screen PDF).
- ❌ Multi-model cost routing (Opus/Sonnet/Haiku per stage), prompt-cache tuning, Batch API.
- ❌ Concept-ledger anti-repetition with per-section running summaries (MVP uses a lightweight deterministic recap).
- ❌ The full 6-provider resource fan-out + soft-404 content heuristics (MVP uses 2 sources + reachability check).
- ❌ **Mixing multiple roadmaps** into one book (MVP is one topic → one book).
- ❌ Web UI, multi-user, hosted service.

These are real features we want — they're deferred so the first slice actually ships.

---

## 3. CLI surface (UX)

Built with **Typer** (+ **Rich** for progress/output).

```
skillbook init                 # create/edit your saved profile (interactive)
skillbook new                  # plan + generate a book (interactive interview)
    --topic "Learn Rust for systems programming"
    --depth standard           # primer | standard | comprehensive
    --style scientific         # casual | scientific  (overrides profile default)
    --model anthropic/claude-opus-4-8
    --out ./books/rust.pdf
    --yes                      # skip the per-book interview + TOC-approval prompt
skillbook resume <run-id>      # continue an interrupted generation
skillbook list                 # past runs / generated books
skillbook config               # set provider/model/keys, user-agent, etc.
```

`skillbook new` flow: load profile → topic interview → **outline** → *show TOC, ask to approve/edit*
→ draft chapters (live progress) → gather+verify resources → roadmap → assemble → render PDF →
print path + token/cost summary.

---

## 4. Personalization model

### Saved profile (`~/.skillbook/profile.json`, Pydantic-validated)
```jsonc
{
  "name": "Iman",
  "background": "CS undergrad, 2 yrs Python, some web dev",   // free text
  "current_level": "intermediate",                            // overall self-rating
  "goals": ["land a backend role", "understand systems deeply"],
  "learning_style": "hands-on, example-first, likes analogies",
  "time_budget": "~6 hrs/week",
  "prior_knowledge": ["Python", "basic SQL", "git"],
  "preferred_style": "casual",                                // default register
  "language": "English"
}
```

### Per-book interview (not persisted; merged into the run's `BookSpec`)
- What's the topic / roadmap? (the request)
- What do you already know about **this** topic? (calibrates the starting point)
- What's the outcome you want? (a job, a project, exam, curiosity…)
- Any must-cover or must-skip subtopics? Constraints (tools, language, OS)?
- Confirm depth + register (defaults pulled from profile/flags).

Profile + interview → a single `BookSpec` object that is injected (compactly) into **every** LLM call.

---

## 5. Generation pipeline (MVP)

Sequential, checkpointed. Each stage writes its artifact to the **run directory** before the next runs.

```
0. assemble BookSpec        (local)   profile + interview  ->  BookSpec
1. OUTLINE                  (LLM·json) BookSpec             ->  Outline {chapters[]}
   └─ approval gate         (local)   show TOC; approve/edit/regenerate
2. CHAPTERS (loop)          (LLM·text) per chapter, sequential, truncation-safe
3. RESOURCES (per chapter)  (LLM+web)  provenance-first gather + validate  ->  Resource[]
4. ROADMAP                  (local)    Outline -> one Mermaid flowchart (deterministic)
5. ASSEMBLE                 (local)    cover + TOC + roadmap + chapters + resources -> book.html
6. RENDER                   (local)    Playwright Chromium -> book.pdf
```

**Outline (stage 1)** — one structured (JSON-schema) call returns:
```jsonc
{
  "title": "...", "subtitle": "...",
  "chapters": [{
    "id": "ch01", "title": "...", "learning_objectives": ["..."],
    "sections": [{ "title": "...", "key_points": ["..."], "target_words": 1200 }],
    "introduces": ["ownership", "borrowing"]   // lightweight concept tags
  }]
}
```
`target_words` per section is derived from the depth tier. A human approval gate here is cheap and
prevents wasting a whole generation on a bad plan.

**Chapter drafting (stage 2)** — sequential loop. Each call receives a **stable prefix**
(compact BookSpec + style directive + full TOC titles/objectives) plus the current chapter's spec
and a **lightweight recap** (deterministic: prior chapter titles + their one-line objectives — *not*
the full concept-ledger machinery). The model returns Markdown for the whole chapter including
prose, ≥1 worked example, exercises, and a quiz with an answer key. **Truncation handling:** if the
provider reports `stop_reason == "max_tokens"`, append the partial text and continue until complete.
(When the provider is Anthropic, the stable prefix is sent with `cache_control` so repeated prefixes
are cheap — an optimization LiteLLM passes through, not a correctness requirement.)

**Checkpoint/resume:** `run_state.json` tracks `{stage, completed_chapter_ids[]}`; every artifact is
written immediately. `skillbook resume <id>` re-loads state, skips completed chapters, continues.

### Ballpark cost/time (Anthropic Sonnet drafting, from research; verify per-run)
| Depth | Pages | Output toks | Time | Cost |
|---|---|---|---|---|
| Standard | ~50 | ~35k | ~10–20 min | ~$0.85–$2.30 |
| Comprehensive | ~120 | ~84k | ~25–45 min | ~$1.85–$4.90 |

> **Default = Opus 4.8** (user's pick), so real cost ≈ **2–3× the table above** (Standard ≈ $2.50–7). Use `--model anthropic/claude-sonnet-4-6` for the cheaper figures shown.

The CLI prints a usage + USD summary after each run (via LiteLLM cost accounting).

---

## 6. Resource gathering — provenance-first (the anti-hallucination guarantee)

**Invariant: the LLM never outputs a URL.** It only (a) writes 2–3 search **queries** per chapter and
(b) later **selects/ranks** among real results. Every link in the book carries provenance
`{url, source, query, retrieved_at}`; a link with no provenance record is rejected.

```
for each chapter:
  queries  = LLM(chapter)                      # 2-3 search strings, no URLs
  results  = gather(queries)                   # real SearchResult[] from providers
  results  = validate(results)                 # reachability + dedup
  picks    = LLM.rank(chapter, results)[:N]    # choose top 4-7 REAL urls, diverse kinds
  attach picks (with provenance) to chapter as "Further Reading"
```

**MVP providers (2):**
- `WikipediaProvider` — no key, canonical low-rot URLs (descriptive User-Agent required).
- `WebProvider` (`ddgs` ≥9.14.4, the renamed `duckduckgo-search`) — general web breadth; **best-effort** with retry+backoff+jitter (known intermittent 202s); never the sole source. *Do not use ddgs's "books" backend (Anna's Archive / piracy).*

**Validation (`httpx`, sync is fine for MVP volume):** normalize URL (strip `utm_*`/fragment) → `HEAD`,
fall back to `GET` on 405 → follow redirects → classify:
- **DEAD → drop:** 404/410, DNS/connection failure, TLS error, timeout.
- **INDETERMINATE → keep (lower confidence):** 403/429/503 or JS-challenge — these are real WAF-protected pages (docs/Medium/.edu), *not* dead. Dropping them would hurt quality.
- **OK → keep:** 2xx.

Providers sit behind a `ResourceProvider` protocol so Tavily / HN / GitHub / Open Library drop in later (§13) without touching call sites.

---

## 7. PDF rendering + diagrams

**Engine: Playwright (headless Chromium), sync API.** Markdown → HTML (`markdown-it-py` + `pygments`
for code) → themed HTML → `page.pdf(print_background=True, prefer_css_page_size=True, outline=True)`
→ clickable, bookmarked PDF.

- **Themes = CSS swap.** `base.css` + one of `casual.css` / `scientific.css` (serif, justified,
  numbered headings, tighter academic layout). Same HTML, different stylesheet. No content branching.
- **Diagrams = client-side Mermaid in the same Chromium.** Vendor a pinned `mermaid.min.js` (v11.x) as
  package data → emit `<pre class="mermaid">…</pre>` → `mermaid.run()` in-page → **`wait_for_selector`
  until all `<svg>` rendered** (avoids the blank-diagram race) → then `page.pdf()`. Zero extra deps.
- The roadmap Mermaid is generated **deterministically** from the outline (one node per chapter, linear
  progression), so it is always valid — no parse-error risk, no extra LLM call. Mermaid runs with
  `securityLevel:'strict'`. (LLM-authored prerequisite graphs with validate/retry are a "Later" item.)
- `.diagram { break-inside: avoid }` and `svg { max-width:100%; height:auto }` for clean pagination.

A one-method `PdfRenderer` protocol wraps this so a WeasyPrint "print/academic" backend *could* be
added later — but it is **not** built now.

---

## 8. LLM provider layer

**LiteLLM (`>=1.87,<2`, pinned, PyPI-only) wrapped behind an internal `LLMProvider` protocol** — the
rest of the code never imports `litellm`. Model strings are `provider/model`
(`anthropic/claude-sonnet-4-6`, `openai/gpt-5.5`, `ollama/llama3`). Rationale: multi-provider breadth
and USD cost accounting are LiteLLM's strengths and exactly the user's stated needs; the protocol seam
keeps the exit cost near-zero if we ever swap to native SDKs.

```python
@dataclass(frozen=True)
class Usage:      input_tokens:int; output_tokens:int; cost_usd:float
@dataclass(frozen=True)
class Completion: text:str; stop_reason:str; usage:Usage   # stop_reason in {"stop","max_tokens","error"}
    @property
    def truncated(self) -> bool: return self.stop_reason == "max_tokens"

class LLMProvider(Protocol):
    model: str
    def complete(self, system, messages, *, max_tokens, **kw) -> Completion: ...
    # stream-first for long chapters: streams deltas to on_delta, returns the full Completion
    def stream_complete(self, system, messages, *, max_tokens, on_delta=None, **kw) -> Completion: ...
    def complete_json(self, system, messages, *, schema, max_tokens, **kw) -> tuple[dict, Usage]: ...
```

Notes baked into the design (from research):
- **No book fits in one call** (best max output ≈128k tok ≈ ~96k words; a book is far larger) → per-chapter loop + truncation continuation is mandatory, not optional.
- **Stream chapter prose** (non-streaming long calls hit the ~10-min timeout).
- For **Anthropic structured output**, pass the JSON **dict** schema (`model.model_json_schema()`), not a raw Pydantic class (known LiteLLM translation bug).
- Default model: `anthropic/claude-opus-4-8` (top quality/coherence — the user's pick); switch to `claude-sonnet-4-6` for ~2–3× cheaper, faster runs. Fully configurable per book.

Keys via env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) — never stored in the repo.

---

## 9. Project structure

```
skillbook/
├─ pyproject.toml            # deps, entry point `skillbook = skillbook.cli:app`
├─ README.md                 # install + quickstart (incl. `playwright install chromium`)
├─ SPEC.md                   # this file
├─ .gitignore                # books/, runs/, .venv/, __pycache__, *.pdf, secrets
├─ src/skillbook/
│  ├─ cli.py                 # Typer app: init / new / resume / list / config (+ interview, approval gate)
│  ├─ config.py              # config + env (provider, model, keys, user-agent)
│  ├─ models.py              # Pydantic: Profile, BookSpec, Outline, Chapter, Resource, RunState
│  ├─ profile.py             # profile load/save
│  ├─ prompts.py             # prompt builders: outline / chapter / resource queries + ranking
│  ├─ llm/
│  │  ├─ base.py             # LLMProvider protocol, Completion, Usage
│  │  └─ litellm_provider.py
│  ├─ generate/
│  │  ├─ outline.py          # stage 1 (structured)
│  │  ├─ chapters.py         # stage 2 (sequential, truncation-safe)
│  │  ├─ roadmap.py          # deterministic Mermaid flowchart from the outline
│  │  └─ pipeline.py         # orchestrator + atomic checkpoint/resume
│  ├─ resources/
│  │  ├─ base.py             # ResourceProvider protocol, SearchResult
│  │  ├─ wikipedia.py
│  │  ├─ web.py              # ddgs
│  │  ├─ validate.py         # httpx reachability + provenance
│  │  └─ gather.py           # aggregate + LLM rank + attach
│  ├─ render/
│  │  ├─ base.py             # PdfRenderer protocol
│  │  ├─ playwright_renderer.py
│  │  ├─ assemble.py         # book model -> HTML
│  │  ├─ themes/{base,casual,scientific}.css
│  │  └─ assets/mermaid.min.js   # vendored, pinned v11.x
└─ tests/
```

Runtime artifacts live in `~/.skillbook/` (profile, config) and `./runs/<run-id>/` (checkpoints,
chapter `.md`, `book.html`, `book.pdf`).

---

## 10. Tech stack (web-verified, June 2026)

| Concern | Choice | Version |
|---|---|---|
| Language | Python | **3.11+** |
| CLI | Typer + Rich | latest |
| LLM layer | **litellm** (PyPI-only, pinned) | `>=1.87,<2` |
| Validation/models | pydantic | `>=2` |
| Markdown→HTML | markdown-it-py + pygments | latest |
| PDF | **playwright** (+ `playwright install chromium`) | latest |
| Diagrams | vendored mermaid UMD | **v11.x** |
| Web search | **ddgs** (renamed from duckduckgo-search) | `>=9.14.4` |
| HTTP / link-check | httpx | latest |

**Install (Windows 11):**
```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium      # bundled Chromium; no GTK/Node/Docker
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```
*Supply-chain note:* pin litellm to a recent patched version, install only from PyPI (a malicious
`litellm 1.82.8` once shipped a bad `.pth`).

---

## 11. Acceptance criteria (MVP "done")

1. `skillbook init` writes a valid `profile.json`.
2. `skillbook new --topic "…" --depth standard --style scientific` runs end-to-end and emits a valid `book.pdf` near the target length.
3. The PDF contains: cover, clickable bookmarked TOC, a rendered Mermaid roadmap, and N chapters — each with prose + ≥1 worked example + exercises + a quiz-with-answers + a Further-Reading list.
4. **Every** external URL traces to a real search result (provenance recorded); DEAD links are absent.
5. `--style casual` vs `scientific` shapes the prose register (via prompts) **and** swaps the CSS theme — one pipeline, no code branching.
6. A killed run resumes via `skillbook resume <id>` and skips completed chapters.
7. The run prints a token + USD usage summary.
8. Clean install on Windows 11 with **no** MSYS2/GTK/Node/Docker.

---

## 12. Risks & mitigations (MVP)

| Risk | Mitigation |
|---|---|
| Chapter exceeds max output tokens (silent truncation) | `stop_reason=="max_tokens"` continuation loop (built into the provider contract). |
| Mermaid renders blank (async race) | `mermaid.run()` then `wait_for_selector` on `<svg>` count before `page.pdf()`. |
| `ddgs` rate-limited (202s) | retry+backoff+jitter; Wikipedia is the reliable backbone; empty results are normal. |
| LLM-invented or rotted links | provenance-first (no LLM URLs) + reachability check; 403/429 kept as *unverified*, not dropped. |
| Anthropic structured-output schema bug in LiteLLM | pass dict `model_json_schema()`, not a raw Pydantic class. |
| Cost surprise on Comprehensive | print estimate before drafting; depth-gated word budgets; offer Sonnet for cheaper runs (default is Opus 4.8). |
| Long run dies near the end | per-chapter checkpointing is load-bearing — write artifacts immediately. |

---

## 13. Later (Phase 2+) — deferred, not forgotten

In rough priority order, build only after the MVP slice runs green:
1. **Mix multiple roadmaps** into one coherent book (cross-topic prerequisite merge at outline; strongest model + human TOC gate).
2. **Concept-ledger anti-repetition** + per-section running summaries (cheap model) for tighter long books.
3. **Multi-model cost routing** (outline=strong, draft=mid, summaries=cheap) + prompt-cache 1h-TTL tuning + **Batch API** "overnight comprehensive" mode (~50% cheaper).
4. **Richer resources:** Tavily (keyed, 1k free/mo) + HN Algolia + GitHub + Open Library (books) + YouTube; soft-404 content heuristics; per-host politeness + async validation; validation cache.
5. **WeasyPrint "print/academic" `PdfRenderer`** backend for page-numbered TOC / running headers / footnotes (opt-in; documents the MSYS2/Pango step).
6. Math support (pre-rendered KaTeX, since Chromium can also run it live).
7. **LLM-authored roadmap** — a real prerequisite graph (not just linear) with a render-and-validate/retry loop, replacing the deterministic chapter-order flowchart.
8. SSRF hardening of the link validator (block private/loopback/link-local IPs, re-checked across redirects).
9. Web UI wrapper; library/export of past books.

---

## 14. Open questions
1. Profile location — `~/.skillbook/` (proposed) vs project-local `./.skillbook/`?
2. ~~Default model~~ — **resolved: `anthropic/claude-opus-4-8`** (Sonnet available via `--model`).
3. Should generated books + run artifacts be git-ignored by default? (proposed: yes.)
