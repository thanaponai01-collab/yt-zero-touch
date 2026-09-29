## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout — root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Project checks
- `VERIFY.md`: each feature and the command that proves it. Run every check before saying done;
  `verify-loop` builds and maintains it.
- `FEATURES.md`: what the system has and how a user reaches each feature. Read it before driving or
  changing the app; `feature-map` keeps it true.
- Coming back after a gap, or "where were we": `recall` rebuilds the state from git and these files.
- Something broken and the cause unknown: `debug-protocol`. Need the system explained plainly, not
  changed: `explain`.
- `onboard-system` builds the rest of the set (architecture, history) in one pass, in the order that
  makes each one true.
