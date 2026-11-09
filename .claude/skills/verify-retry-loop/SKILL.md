---
name: verify-retry-loop
description: Check a change to download_with_retry (retry/backoff, the login-wall and client-retry one-shot fallbacks, permanent-vs-transient stop rules) in services/orchestrator.py or core/failures.py against a TLA+ model of the retry state machine. Use before changing or reviewing that loop, FailureClass.permanent, or the fallback client lists.
---

# Verify the retry loop

**Property.** One URL's download never retries a permanent failure, runs each fallback client at most once, never goes back to a client known to be broken, always ends, and never makes more than `retry_max + 3` calls.
**Harm if broken.** A login-walled or deleted video is retried for minutes, or a bot-checked video burns the same bad client again and again, so the batch stalls or fails for a reason the user can't fix.

## Covered code (last confirmed at commit `4a6988e034617513b94cbe8a55f80ee0fe0733c0`)

| Code | Model |
|---|---|
| `download_with_retry` in `src/yt_zero_touch/services/orchestrator.py` (the `for attempt` loop, the `failure is _LOGIN` / `failure is _CLIENT_RETRY` branches, `download_fn = fallback_fn`, the `failure.permanent` stop) | `tools/formal/retry_loop/RetryLoop.tla` (actions CallMain, TakeLoginFallback, TakeClientFallback, CallFallback, Decide) |
| `classify_failure`, `FailureClass.permanent` in `src/yt_zero_touch/core/failures.py` | the `Classes` set and `Permanent(c)` (login and perm stop; client and none retry) |

One model step is one line-group of the loop: a `download_fn` call, a classification, or the stop/retry decision. Not modelled: the wording of the regexes, the `retry_delays` sleeps, progress hooks, and what `download_fn` does inside yt-dlp.

## Is my change in scope?

Run `git diff 4a6988e034617513b94cbe8a55f80ee0fe0733c0 -- src/yt_zero_touch/services/orchestrator.py src/yt_zero_touch/core/failures.py`. If it touches `download_with_retry`, `_LOGIN`, `_CLIENT_RETRY`, `FailureClass`, or `LOGIN_WALL_FALLBACK_CLIENT` / `CLIENT_RETRY_FALLBACK_CLIENT`, run the checks. A change only to `run_batch`, log text or regexes in `_FAILURE_RULES` needs only the code check below.

## Run (about 15 s)

```bash
python tools/formal/tlc.py tools/formal/retry_loop/RetryLoop.tla
python tools/formal/retry_loop/conformance.py
```

Needs Java 11+ and `tools/formal/.cache/tla2tools.jar` (pinned by SHA-256 in `tools/formal/tlc.py`, which prints the download URL if it is missing).

1. `tlc.py` checks the model: 238 states, five invariants, two temporal properties (`AltIsSticky`, `Terminates`), `RetryMax = 3`.
2. `conformance.py` runs the real `download_with_retry` on all 3125 outcome scripts (5 outcomes per call, `retry_max = 2`) and compares each call trace and stop reason with a line-by-line Python copy of the model. This is the step that catches a break in the code.

Read any TLC failure with the pstack `/statechart` skill: it shows the shortest path to the broken rule in plain words.

## Telling a bug from a modelling error

- Conformance fails and the model run passes: the code changed behaviour. Read the first mismatch (script, model trace, code trace). If you meant the change, update the model and its Python copy together, then rerun both. If not, fix the code.
- TLC fails: the model now allows a path that breaks a rule. Replay the path against the real code by writing it as a script for `conformance.run_real`.
- The final `FailureClass` in `DownloadOutcome.failure` is classified on the whole last buffer, so it can say "login" even when the loop ran out of retries. That is by design (see the comment in `download_with_retry`) and is why conformance reads the stop reason from the log, not from `failure.permanent`.

## Updating after an intended change

Edit `RetryLoop.tla` and the `model()` function in `conformance.py` to match, keep every rule (never weaken one to make it pass), rerun both commands, and only then move the commit above to the new `git rev-parse HEAD` after you confirm the table above still describes the code.

## Known findings

None. All rules hold up to `RetryMax = 3` (conformance: `retry_max = 2`).
