---
name: verify-transcode-gate
description: Check a change to the software-transcode gate and merge session (_TRANSCODE_GATE, _MergeSession, merge_started/merge_finished/output_landed/verify, container commitment) in core/transcode.py against a TLA+ model and a replay on the real lock. Use before changing or reviewing that file, the yt-dlp postprocessor hooks that call it, or ADR-0002/0003 behaviour.
---

# Verify the transcode gate

**Property.** At most one software (libx264 or ProRes) encode runs at a time, the gate is always freed when a merge ends, is replaced, or the session exits (including on an exception), and every file under a committed container (`mp4`, `mov`) is probed before the download is called good.
**Harm if broken.** Two 4K encodes at once run the machine out of memory and crash the batch, a leaked gate freezes every later download behind it forever, and an unprobed VP9 file lands in a folder as "Premiere-ready".

## Covered code (last confirmed at commit `4a6988e034617513b94cbe8a55f80ee0fe0733c0`)

| Code | Model |
|---|---|
| `_TRANSCODE_GATE`, `_MergeSession._take_gate`, `_free_gate`, `merge_started`, `merge_finished`, `__exit__` in `src/yt_zero_touch/core/transcode.py` | `tools/formal/transcode_gate/MergeGate.tla` (actions StartMerge, Decide, Acquire, Finish, Exit) |
| `_MergeSession.output_landed`, `verify` (prefers `_outputs`, falls back to `_finished`) and `_CONTAINER_COMMITMENTS` in the same file | not in TLA+; checked by `check_verification()` in `conformance.py` |

A model step is one public method of `_MergeSession`, split where another thread can run in between (`merge_started` is two steps: free the old gate, then take the new one). Not modelled: ffmpeg itself, `plan_transcode` (which codec needs the gate; the model picks `needs_gate` freely), and NVENC/QSV/AMF probing (those plans have `needs_gate = False`, which the model covers as "no gate").

## Is my change in scope?

Run `git diff 4a6988e034617513b94cbe8a55f80ee0fe0733c0 -- src/yt_zero_touch/core/transcode.py src/yt_zero_touch/engines/ytdlp_engine.py`. If it touches the gate, `_MergeSession`, `plan_transcode().needs_gate`, `_CONTAINER_COMMITMENTS`, or the postprocessor hook that calls `merge_started` / `merge_finished` / `output_landed` / `verify`, run the checks.

## Run (about 40 s)

```bash
python tools/formal/tlc.py tools/formal/transcode_gate/MergeGate.tla
python tools/formal/transcode_gate/conformance.py
```

Needs Java 11+ and `tools/formal/.cache/tla2tools.jar` (pinned by SHA-256 in `tools/formal/tlc.py`).

1. `tlc.py`: 2 workers, up to 2 merges each, 357 states, five invariants plus the `EveryoneFinishes` liveness property.
2. `conformance.py`: replays about 300,000 interleavings of two real `_MergeSession`s on the real `threading.Lock`, checks the same rules on the real flag and lock, then checks `verify()` for every combination of finished/landed files and committed/uncommitted containers.

Read any TLC failure with the pstack `/statechart` skill: it shows the shortest path to the broken rule in plain words.

## Telling a bug from a modelling error

- Conformance prints `two sessions hold the gate`, `gate still locked after every session exited` or similar: the code leaks or double-takes the gate. Fix the code.
- `verification mismatch`: a file that should have been probed was not (or the reverse). Fix the code, or if the signal order changed on purpose, update `verify()`'s documented preference and `check_verification()` together.
- TLC fails but conformance passes: the model allows an order the harness did not try. Add that order to `worker_programs()` and see if the real code breaks.
- Conformance skips a step that would block in `_take_gate` (it cannot block a single thread); the model's `Acquire` guard `gate = "none"` is the same rule.

## Updating after an intended change

Edit `MergeGate.tla` and `conformance.py` together, keep every rule, rerun both commands, then move the commit above to the new `git rev-parse HEAD` after you confirm the table still describes the code.

## Known findings

None. 2 workers x 2 merges; a third worker adds no new behaviour for a single lock.
