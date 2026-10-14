<!-- start-here -->
## Quick Start & Context Index

Zero-touch video and image downloader for Windows editors producing Premiere Pro-ready files.

intent: BRIEF.md
work: BUILD.md
features: FEATURES.md
verify: VERIFY.md
architecture: ARCHITECTURE.md
commands: docs/commands.md

Read [BRIEF.md](BRIEF.md) for goals/decisions, [BUILD.md](BUILD.md) for next steps, [FEATURES.md](FEATURES.md) for entry points, [VERIFY.md](VERIFY.md) for checks, [ARCHITECTURE.md](ARCHITECTURE.md) for boundaries, and [docs/commands.md](docs/commands.md) for commands.
Read [CONTEXT.md](CONTEXT.md) for domain terminology and [DECISION_LEDGER.md](DECISION_LEDGER.md) for architectural decisions.
A changed decision replaces its line in the brief or its linked area.
Consult project-context Task Context when missing project decisions, state, history, or verification context.
Upkeep: authorized updates refresh affected intent, evidence, and Next; read-only reviews report gaps.
<!-- /start-here -->

<!-- agent-routing -->
## Agent Routing & Roles

- **Coordinator**: Current session model (Claude Code: user selects Opus if desired). Judges proof, owns task context.
- **Execution**: Plugin agent `agents/drive-executor.md` (Sonnet) for bounded implementation and local checks.
- **Discovery**: Plugin agent `agents/setup-reader.md` (Haiku) for bounded read-only evidence collection.
- **Ownership**: `project-foundation` owns foundation preparation; Drive owns execution gates and task context upkeep.
- **Task Boundaries**: Workers receive assigned paths, acceptance checks, allowed edits, and output limits; no full chat history dump.
- **Authority**: Workers cannot modify acceptance oracles or authorize external actions. Coordinator evaluates evidence.
- **Host Policy**: Honor host overrides; if configured worker types/delegation are unsupported, fallback to single-agent execution.
- **Existing Context**: [CONTEXT.md](CONTEXT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DECISION_LEDGER.md](DECISION_LEDGER.md).
<!-- /agent-routing -->

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout — root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
