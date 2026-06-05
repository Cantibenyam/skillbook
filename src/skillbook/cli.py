"""SkillBook command-line interface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import typer

# Never crash on a non-UTF-8 Windows console (cp1252 can't encode some glyphs /
# LLM-produced characters). Reconfigure before Rich captures the stream.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .agent_build import build_pdf, scaffold_run, search_resources
from .config import load_config, save_config
from .generate.outline import build_outline, format_toc
from .generate.pipeline import Reporter, RunStore, new_run_id, run_pipeline, slugify
from .llm import Usage, get_provider
from .models import BookSpec, Depth, Outline, Profile, RunState, Style
from .profile import load_profile, save_profile
from .resources import default_providers, default_validator

app = typer.Typer(
    help="SkillBook - generate personalized, book-length learning PDFs with AI.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
}


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _ask_list(prompt: str, default: list[str] | None = None) -> list[str]:
    raw = Prompt.ask(prompt, default=", ".join(default or []))
    return [item.strip() for item in raw.split(",") if item.strip()]


def _run_profile_interview(existing: Profile | None) -> Profile:
    e = existing or Profile()
    console.print("[bold]Let's build your learner profile.[/] It's reused for every book.\n")
    name = Prompt.ask("Your name", default=e.name)
    background = Prompt.ask("Your background (education, experience)", default=e.background)
    level = Prompt.ask(
        "Overall level", choices=["beginner", "intermediate", "advanced"],
        default=e.current_level or "beginner",
    )
    goals = _ask_list("Your learning goals (comma-separated)", e.goals)
    learning_style = Prompt.ask(
        "How you learn best (e.g. hands-on, examples-first, theory-first)", default=e.learning_style
    )
    time_budget = Prompt.ask("Time you can commit (e.g. 5 hrs/week)", default=e.time_budget)
    prior = _ask_list("Skills you already have (comma-separated)", e.prior_knowledge)
    pref = Prompt.ask(
        "Default writing style", choices=["casual", "scientific"], default=e.preferred_style.value
    )
    language = Prompt.ask("Language", default=e.language or "English")
    return Profile(
        name=name, background=background, current_level=level, goals=goals,
        learning_style=learning_style, time_budget=time_budget, prior_knowledge=prior,
        preferred_style=Style(pref), language=language,
    )


def _book_interview(topic: str) -> dict:
    console.print(f"\n[dim]A few quick questions to tailor your book on '{topic}':[/]")
    return {
        "already_known": Prompt.ask("What do you already know about this topic?", default=""),
        "outcome": Prompt.ask("What outcome do you want? (job, project, exam, curiosity…)", default=""),
        "must_cover": _ask_list("Anything it MUST cover? (comma-separated)", []),
        "must_skip": _ask_list("Anything to skip? (comma-separated)", []),
        "constraints": Prompt.ask("Constraints? (tools, language, OS…)", default=""),
    }


def _require_api_key(model: str) -> None:
    if model.startswith("mock"):
        return
    provider = model.split("/", 1)[0]
    env = _PROVIDER_ENV.get(provider)
    if env and not os.getenv(env):
        console.print(f"[red]No API key found for provider '{provider}'.[/]")
        console.print(f'  Set it first, e.g. PowerShell: [cyan]$env:{env} = "..."[/]')
        raise typer.Exit(code=1)


def _edit_outline(outline: Outline) -> Outline | None:
    edited = click.edit(outline.model_dump_json(indent=2), extension=".json")
    if edited is None:
        console.print("[yellow]No changes made.[/]")
        return None
    try:
        return Outline.model_validate_json(edited)
    except Exception as exc:
        console.print(f"[red]Invalid outline ({exc}); keeping the previous one.[/]")
        return None


def _approve_outline(provider, spec: BookSpec, auto: bool) -> tuple[Outline, Usage]:
    total = Usage()
    with console.status("[bold]Planning the table of contents…"):
        outline, usage = build_outline(provider, spec)
    total = total + usage
    while not auto:
        console.print(Panel(format_toc(outline), title="Proposed Table of Contents", border_style="cyan"))
        choice = Prompt.ask(
            "[a]pprove · [r]egenerate · [e]dit · [q]uit",
            choices=["a", "r", "e", "q"], default="a",
        )
        if choice == "a":
            break
        if choice == "q":
            raise typer.Abort()
        if choice == "r":
            with console.status("[bold]Regenerating…"):
                outline, usage = build_outline(provider, spec)
            total = total + usage
        elif choice == "e":
            edited = _edit_outline(outline)
            if edited is not None:
                outline = edited
    return outline, total


class RichReporter(Reporter):
    def stage(self, name, detail=""):
        console.rule(f"[bold]{name}[/]" + (f" - [dim]{detail}[/]" if detail else ""))

    def chapter_start(self, index, total, title):
        console.print(f"[cyan]> Chapter {index}/{total}[/]: {title}")

    def chapter_done(self, index, total, title, usage):
        console.print(f"   [green]done[/] {usage.output_tokens:,} tokens, ${usage.cost_usd:.3f}")

    def info(self, msg):
        console.print(f"[dim]{msg}[/]")

    def warn(self, msg):
        console.print(f"[yellow]! {msg}[/]")


def _print_summary(state: RunState) -> None:
    console.print()
    panel = (
        f"[bold green]Book ready![/]\n\n"
        f"[bold]File:[/] {state.out_path}\n"
        f"[bold]Chapters:[/] {len(state.completed_chapter_ids)}\n"
        f"[bold]Tokens:[/] {state.input_tokens:,} in / {state.output_tokens:,} out\n"
        f"[bold]Cost:[/] ${state.cost_usd:.2f}\n"
        f"[dim]Run id: {state.run_id} (resume with: skillbook resume {state.run_id})[/]"
    )
    console.print(Panel(panel, border_style="green"))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


@app.command()
def init() -> None:
    """Create or edit your saved learner profile."""
    profile = _run_profile_interview(load_profile())
    save_profile(profile)
    console.print("\n[green]Profile saved.[/] Run [cyan]skillbook new[/] to make a book.")


@app.command()
def new(
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="What you want to learn."),
    depth: Depth = typer.Option(Depth.standard, "--depth", "-d", help="Book depth."),
    style: Optional[Style] = typer.Option(None, "--style", "-s", help="Register (default: your profile)."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="provider/model override."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output PDF path."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interview and TOC approval."),
    mock: bool = typer.Option(False, "--mock", help="Offline dry-run with placeholder content (no API)."),
) -> None:
    """Plan and generate a personalized book."""
    config = load_config()
    model = model or config.model

    profile = load_profile()
    if profile is None:
        if yes or mock:
            profile = Profile()
        else:
            console.print("[yellow]No profile found.[/] Let's create one first.")
            profile = _run_profile_interview(None)
            save_profile(profile)

    provider = get_provider(model, mock=mock)
    if not mock:
        _require_api_key(model)

    topic = topic or Prompt.ask("What do you want to learn?")
    chosen_style = style or profile.preferred_style
    interview = {} if (yes or mock) else _book_interview(topic)
    spec = BookSpec(
        topic=topic, profile=profile, depth=depth, style=chosen_style,
        model=model, **interview,
    )

    out_path = out or Path(config.books_dir) / f"{slugify(topic)}.pdf"
    run_id = new_run_id(topic)
    store = RunStore(run_id, config.runs_dir)
    store.ensure()

    outline, usage = _approve_outline(provider, spec, auto=(yes or mock))
    state = RunState(
        run_id=run_id, spec=spec, out_path=str(out_path), outline=outline, stage="outline",
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=usage.cost_usd,
    )
    store.save_state(state)

    final = run_pipeline(
        spec, provider=provider, out_path=out_path, run_id=run_id, resume=True,
        base_dir=config.runs_dir, reporter=RichReporter(), config=config,
        gather_sources=not mock,
    )
    _print_summary(final)


@app.command()
def resume(run_id: str = typer.Argument(..., help="The run id to continue.")) -> None:
    """Continue an interrupted generation."""
    config = load_config()
    store = RunStore(run_id, config.runs_dir)
    if not store.state_path.exists():
        console.print(f"[red]No run '{run_id}' found under {config.runs_dir}/.[/]")
        raise typer.Exit(code=1)
    state = store.load_state()
    provider = get_provider(state.spec.model)
    _require_api_key(state.spec.model)
    out_path = state.out_path or str(Path(config.books_dir) / f"{slugify(state.spec.topic)}.pdf")
    final = run_pipeline(
        state.spec, provider=provider, out_path=out_path, run_id=run_id, resume=True,
        base_dir=config.runs_dir, reporter=RichReporter(), config=config,
    )
    _print_summary(final)


@app.command("list")
def list_runs() -> None:
    """List past runs and generated books."""
    config = load_config()
    base = Path(config.runs_dir)
    runs = sorted(base.glob("*/run_state.json")) if base.exists() else []
    if not runs:
        console.print("[dim]No runs yet. Make one with[/] [cyan]skillbook new[/].")
        return
    table = Table(title="SkillBook runs")
    table.add_column("Run id", style="cyan")
    table.add_column("Topic")
    table.add_column("Stage")
    table.add_column("Chapters", justify="right")
    table.add_column("Cost", justify="right")
    for state_file in runs:
        try:
            st = RunState.model_validate_json(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        table.add_row(st.run_id, st.spec.topic, st.stage, str(len(st.completed_chapter_ids)), f"${st.cost_usd:.2f}")
    console.print(table)


@app.command()
def config(
    model: Optional[str] = typer.Option(None, "--model", help="Set the default model."),
    email: Optional[str] = typer.Option(None, "--email", help="Contact email for resource fetching User-Agent."),
    show: bool = typer.Option(False, "--show", help="Show the current configuration."),
) -> None:
    """View or change configuration (non-secret settings)."""
    cfg = load_config()
    changed = False
    if model:
        cfg.model = model
        changed = True
    if email is not None:
        cfg.contact_email = email
        changed = True
    if changed:
        save_config(cfg)
        console.print("[green]Configuration saved.[/]")
    if show or not changed:
        console.print_json(cfg.model_dump_json())


# --------------------------------------------------------------------------- #
# Claude Code mode — the agent authors the book; these helpers do the no-LLM work
# (used by the /skillbook slash command). None of them need an API key.
# --------------------------------------------------------------------------- #


@app.command()
def scaffold(
    topic: str = typer.Option(..., "--topic", "-t", help="What the book teaches."),
    style: Style = typer.Option(Style.casual, "--style", "-s", help="Register."),
) -> None:
    """[Claude Code mode] Create a run directory for the agent to fill in."""
    config = load_config()
    profile = load_profile()
    run_dir = scaffold_run(
        topic, style=style, runs_dir=config.runs_dir, learner_name=profile.name if profile else ""
    )
    console.print(f"[green]Run created:[/] {run_dir}")
    console.print(
        "Next: fill [cyan]book.json[/] (title, subtitle, chapters:[{id,title}]), write each "
        f"[cyan]chapters/<id>.md[/], add [cyan]chapters/<id>.resources.json[/] from "
        f"`skillbook search`, then run [cyan]skillbook build {run_dir}[/]."
    )


@app.command()
def search(
    queries: list[str] = typer.Argument(..., help="One or more search queries."),
    limit: int = typer.Option(5, "--limit", "-n", help="Results per query, per source."),
) -> None:
    """[Claude Code mode] Provenance-first search: print REAL, reachability-checked links as JSON."""
    config = load_config()
    results = search_resources(
        queries,
        providers=default_providers(config),
        validator=default_validator(config),
        limit=limit,
    )
    typer.echo(json.dumps(results, indent=2, ensure_ascii=False))


@app.command()
def build(
    run: str = typer.Argument(..., help="Run directory path or run id."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output PDF path."),
) -> None:
    """[Claude Code mode] Render a PDF from the agent's on-disk artifacts (no API key)."""
    config = load_config()
    run_dir = Path(run)
    if not run_dir.exists():
        run_dir = Path(config.runs_dir) / run
    if not (run_dir / "book.json").exists():
        console.print(f"[red]No book.json found in {run_dir}.[/]")
        raise typer.Exit(code=1)
    meta = json.loads((run_dir / "book.json").read_text(encoding="utf-8-sig"))
    out_path = out or Path(
        meta.get("out") or Path(config.books_dir) / f"{slugify(meta.get('topic') or 'book')}.pdf"
    )
    result = build_pdf(run_dir, Path(out_path))
    console.print(f"[green]PDF written:[/] {result}")


@app.command()
def verify(
    pdf: Path = typer.Argument(..., help="A finished book PDF to quality-check."),
    raster: Optional[Path] = typer.Option(None, "--raster", help="Also write page PNGs to this dir."),
) -> None:
    """Read a finished book and flag layout problems (blank/near-empty pages)."""
    from .render.verify import analyze_pdf, rasterize_pages

    report = analyze_pdf(pdf)
    verdict = "[green]no layout issues[/]" if report.ok else "[yellow]issues found[/]"
    console.print(f"{report.page_count} pages · {verdict}")
    for issue in report.issues:
        console.print(f"  [yellow]! {issue}[/]")
    for note in report.notes:
        console.print(f"  [dim]- {note}[/]")
    if raster is not None:
        paths = rasterize_pages(pdf, raster)
        console.print(f"[dim]wrote {len(paths)} page images to {raster}[/]")
    raise typer.Exit(code=0 if report.ok else 1)
