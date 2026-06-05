# SkillBook 📚

Turn any learning request — a topic or a roadmap — into a **personalized, book-length PDF**,
written to fit *you*, in a casual or scientific register, with worked examples, hands-on
exercises, self-check quizzes, a visual roadmap, and **verified** further-reading links.

> Previously you might use AI to get a roadmap with scattered links. SkillBook turns that into
> an actual book — extensive, coherent, and tailored to your background, level, and goals.

## How it works

```
your profile + a short interview
        │
        ▼
   plan a table of contents   ──►  you approve / edit the TOC
        │
        ▼
   write each chapter (prose + examples + exercises + quiz)
        │
        ▼
   gather & verify resources  (the AI never invents a URL — it ranks real search results)
        │
        ▼
   render a polished PDF  (themed: casual ↔ scientific, with a Mermaid roadmap)
```

See [`SPEC.md`](./SPEC.md) for the full design.

## Status

🚧 Early development — MVP in progress. See `SPEC.md` §13 for the roadmap.

## Install (Windows / macOS / Linux)

```bash
python -m venv .venv
# Windows:  .\.venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -e .
playwright install chromium        # one-time: bundled browser for PDF rendering (no GTK/Node/Docker)
```

Set an API key for your provider:

```bash
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# or OPENAI_API_KEY, etc.
```

## Usage

```bash
skillbook init                       # create your saved profile
skillbook new --topic "Learn Rust"   # plan + generate a book
skillbook resume <run-id>            # continue an interrupted run
skillbook list                       # past runs / books
```

Key options for `new`: `--depth primer|standard|comprehensive`, `--style casual|scientific`,
`--model <provider/model>` (default `anthropic/claude-opus-4-8`; use
`anthropic/claude-sonnet-4-6` for cheaper, faster runs), `--out <path.pdf>`.

## License

MIT
