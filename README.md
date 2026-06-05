# SkillBook 📚

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

**Turn any topic or roadmap into a personalized, book-length learning PDF** — written to fit *you*,
in a casual or scientific register, with worked examples, hands-on exercises, self-check quizzes, a
visual roadmap, and **verified** further-reading links.

> Instead of an AI handing you a roadmap with scattered links, SkillBook writes you an actual
> *book* — coherent, extensive, and tailored to your background, level, and goals.

You can run it two ways:

- **API mode** — a standalone CLI that calls an LLM provider (needs an API key).
- **Claude Code mode** — open the repo in [Claude Code](https://claude.com/claude-code) and run
  `/skillbook <topic>`; Claude Code writes the book itself.

---

## What you get

- 🎯 **Personalized** — a saved profile (background, level, goals, learning style, time) plus a short
  per-book interview shape every chapter.
- 🧭 **Coherent** — you approve a table of contents, then chapters are written in order, building on
  each other.
- 🔗 **Verified resources, no hallucinated links** — the model only ranks **real, reachability-checked**
  search results; it never invents a URL.
- 🎨 **Two designed themes** — *casual* (modern sans, violet accent) or *scientific* (elegant serif,
  teal accent, numbered sections), with callout cards for exercises/quizzes, a styled cover, and a
  one-page Mermaid roadmap.
- ✅ **Quality-checked** — after rendering, SkillBook reads the PDF back and flags blank/empty pages.
- 🔌 **Configurable** — any LiteLLM provider (Anthropic, OpenAI, …); depth and register per book.

---

## How it works

```
your profile + a short interview
        │
        ▼
   plan a table of contents   ──►  you approve / edit it
        │
        ▼
   write each chapter (prose + worked examples + exercises + quiz)
        │
        ▼
   gather & verify resources  (real search results, reachability-checked)
        │
        ▼
   render a themed PDF  (cover, Mermaid roadmap, bookmarked TOC)  ──►  quality check
```

See [`SPEC.md`](./SPEC.md) for the full design and the deferred roadmap.

---

## Installation

**Prerequisites:** Python 3.11+ and [git](https://git-scm.com/). (No Node, Docker, or system
libraries needed — the PDF renderer ships its own browser.)

```bash
git clone https://github.com/Cantibenyam/skillbook.git
cd skillbook

# create and activate a virtual environment
python -m venv .venv
#   Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
#   macOS / Linux:         source .venv/bin/activate

pip install -e .
playwright install chromium      # one-time: downloads the bundled browser used to render PDFs
```

Verify it installed:

```bash
skillbook --help          # or:  python -m skillbook --help
```

---

## Mode A — standalone CLI (uses an API key)

**1. Set a provider API key** (Anthropic is the default; OpenAI and others work too):

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# macOS / Linux
export ANTHROPIC_API_KEY="sk-ant-..."
```

**2. Create your profile once** (reused for every book):

```bash
skillbook init
```

**3. Generate a book:**

```bash
skillbook new --topic "Learn Rust for systems programming"
```

You'll answer a couple of quick questions, approve the table of contents, then watch the chapters
stream in. When it's done you get a PDF path plus a token/cost summary.

**Options for `new`:**

| Option | Values | Default |
|---|---|---|
| `--depth` | `primer` (~4–6 ch) · `standard` (~7–10) · `comprehensive` (~12–18) | `standard` |
| `--style` | `casual` · `scientific` | your profile's default |
| `--model` | any `provider/model` | `anthropic/claude-opus-4-8` |
| `--out`   | output PDF path | `books/<topic>.pdf` |
| `--yes`   | skip the interview + TOC approval | off |

> 💡 `--model anthropic/claude-sonnet-4-6` is noticeably cheaper and faster than the Opus default.

**Other commands:**

```bash
skillbook resume <run-id>     # continue an interrupted generation
skillbook list                # past runs and their cost
skillbook verify books/x.pdf  # quality-check a finished PDF (blank-page detection)
skillbook config --show       # view settings (model, contact email for the resource User-Agent)
```

---

## Mode B — Claude Code (no API key)

Open this folder in [Claude Code](https://claude.com/claude-code) and run:

```
/skillbook Learn Rust for systems programming
```

Here **Claude Code itself authors the book** using your Claude Code session — no API key needed.
The Python package does the deterministic work: real-link search and PDF rendering. The slash
command lives in [`.claude/commands/skillbook.md`](.claude/commands/skillbook.md).

The helper commands it uses are also runnable by hand (no key required):

```bash
python -m skillbook scaffold --topic "Learn Rust" --style scientific   # create a run folder
python -m skillbook search "rust ownership tutorial" --limit 6          # real candidate links (JSON)
python -m skillbook build runs/<id> --out books/rust.pdf                # render artifacts -> PDF
python -m skillbook verify books/rust.pdf                               # quality-check
```

Both modes share the same renderer, themes, roadmap, and resource validation, so the output looks
identical.

---

## Output & design

Books are typeset with vendored open-source fonts (Inter / Sora for *casual*, Source Serif 4 for
*scientific*, JetBrains Mono for code — all inlined, so rendering works fully offline). Each chapter
opens with a large outlined number; Exercises / Quiz / Worked-example sections become colored
**callout cards**; the learning roadmap is constrained to a single page (it never splits across a
page break). After rendering, `skillbook verify` rasterizes the PDF and flags any blank / near-empty
pages.

Runtime artifacts (profile and config) live in `~/.skillbook/`; generated books and run checkpoints
go to `./books/` and `./runs/` (both git-ignored).

---

## Configuration

| What | Where |
|---|---|
| API keys | environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …) — never stored on disk |
| Default model, contact email | `~/.skillbook/config.json` (edit via `skillbook config`) |
| Output / run folders | `SKILLBOOK_BOOKS_DIR`, `SKILLBOOK_RUNS_DIR`, `SKILLBOOK_MODEL` env vars |

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The codebase is small and layered: `llm/` (provider abstraction), `generate/` (outline → chapters →
pipeline), `resources/` (provenance-first search + validation), `render/` (themed HTML → PDF +
verifier), and `agent_build.py` (the Claude Code helpers). See `SPEC.md` for the architecture.

---

## License

[MIT](LICENSE) © Cantibenyam
