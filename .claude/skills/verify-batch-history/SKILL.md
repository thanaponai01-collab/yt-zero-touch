---
name: verify-batch-history
description: Check a change to run_batch's resolve-then-download pipeline and its history writes (skip already-downloaded, force, fan-out of one page into several videos, worker limit, history.add after success) in services/orchestrator.py and core/history.py against a TLA+ model and a replay on the real run_batch. Use before changing or reviewing that pipeline, or when a user reports a video that was never downloaded though its URL was in the batch.
---

# Verify the batch pipeline and history

**Property.** A batch only skips URLs already in history (unless forced), never runs more than `max_workers` downloads, records only successes, and a URL recorded as downloaded by this batch had **every** one of its videos downloaded.
**Harm if broken.** A video silently never downloads: the editor re-runs the batch, the URL is "already downloaded", and the missing clip is only noticed in Premiere.

## Covered code (last confirmed at commit `4a6988e034617513b94cbe8a55f80ee0fe0733c0`)

| Code | Model |
|---|---|
| `run_batch` in `src/yt_zero_touch/services/orchestrator.py`: the `url in history_set and not policy.force` skip, the fan-out `for resolved in resolved_list`, `ThreadPoolExecutor(max_workers=...)`, the `outcome.ok` history write | `tools/formal/batch_history/BatchPipeline.tla` (actions Resolve, Start, Succeed, Fail) |
| `HistoryStore.add`, `.urls` in `src/yt_zero_touch/core/history.py` | the `hist` variable (a set that only grows) |

Model: three work items; `i1` and `i2` share URL `a` (a page with two videos, or `a` pasted twice), `i3` is URL `b`; history starts as any subset of `{a, b}` and `force` is free. Resolve finishes for every URL before any download starts. Not modelled: retry/backoff (see `verify-retry-loop`), resolver internals, the legacy `set` + `history_lock` form of `history`, disk write errors that `HistoryStore.add` swallows.

## Is my change in scope?

Run `git diff 4a6988e034617513b94cbe8a55f80ee0fe0733c0 -- src/yt_zero_touch/services/orchestrator.py src/yt_zero_touch/core/history.py`. If it touches `run_batch`, the skip test, the fan-out loop, the history write, or `HistoryStore.add`, run the checks.

## Run (about 10 s)

```bash
python tools/formal/tlc.py tools/formal/batch_history/BatchPipeline.tla --expect NoVideoLeftBehind
python tools/formal/batch_history/conformance.py
```

Needs Java 11+ and `tools/formal/.cache/tla2tools.jar` (pinned by SHA-256 in `tools/formal/tlc.py`).

1. `tlc.py`: 83 states. `--expect NoVideoLeftBehind` marks the known finding below: the command exits 0 only if exactly that rule breaks and every other rule holds.
2. `conformance.py`: runs the real `run_batch` with a fake downloader for every history/force/outcome combination (48 runs) and compares the history and counters with the model; it also confirms the known finding on the real code (16 scenarios).

Read any TLC failure with the pstack `/statechart` skill: it shows the shortest path to the broken rule in plain words.

## Known finding KF-1: `NoVideoLeftBehind` (reported, not fixed)

Path in the code's terms: batch = `[A]`, where `A` resolves to two videos `A/1` and `A/2` (`resolve_fn` returns a list of 2). `A/1` downloads fine, so `history.add("A")` runs. `A/2` fails. The batch reports 1 succeeded, 1 failed, but `A` is now in history. Next run, `url in history_set` skips `A` and `A/2` is never retried. The same happens when the same URL is pasted twice and only one copy succeeds. Cause: history is keyed by the page URL (`url`), but written per resolved video (`outcome.ok` inside the per-item loop).

If someone fixes this (for example by recording `url` only after all its items succeeded), `tlc.py --expect NoVideoLeftBehind` will report "Known finding no longer breaks": update the model, drop `--expect`, delete this section, and rerun.

## Telling a bug from a modelling error

- Conformance reports a mismatch: real history or counters differ from the model on a given scenario. Read the printed scenario, decide whether the change is intended, and update the model and `model()` in `conformance.py` together if so.
- TLC reports an unexpected rule: the model allows a path that breaks it; replay that path in `conformance.real(...)`.

## Updating after an intended change

Edit `BatchPipeline.tla` and `conformance.py` together, never weaken a rule to make it pass, rerun both commands, then move the commit above to the new `git rev-parse HEAD` after you confirm the table still describes the code.
