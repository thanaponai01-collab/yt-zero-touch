"""Replay every environment script through the REAL download_with_retry and
compare with RetryLoop.tla.  Exit 0 = the code behaves as the model says.

Every call to a download_fn (main, login fallback, client fallback) takes the next
outcome from a script; all scripts of length RetryMax+3 over the five outcomes
are tried.  The expected call trace comes from `model()`, a line-by-line
transcription of the TLA+ actions.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_zero_touch.services.orchestrator import download_with_retry  # noqa: E402

RETRY_MAX = 2
OUTCOMES = ("ok", "login", "client", "perm", "none")
ERROR_TEXT = {
    "login": "ERROR: Sign in to confirm you're not a bot",
    "client": "ERROR: ffmpeg exited with code 4294967295",
    "perm": "ERROR: Video unavailable",
    "none": "ERROR: boom",
}
PERMANENT = {"login", "perm"}


def model(script):
    """RetryLoop.tla, executed.  Returns (call trace, ok, reason)."""
    it = iter(script)
    trace, attempt, login_fb, client_fb, alt = [], 1, True, True, False
    while True:
        trace.append("client" if alt else "main")
        c = next(it)
        if c == "ok":
            return trace, True, "ok"
        if c == "login" and login_fb:
            login_fb = False
            trace.append("login")
            c = next(it)
            if c == "ok":
                return trace, True, "ok"
        elif c == "client" and client_fb:
            client_fb = False
            trace.append("client")
            c = next(it)
            if c == "ok":
                return trace, True, "ok"
            alt = True
        if c in PERMANENT:
            return trace, False, "permanent"
        if attempt <= RETRY_MAX:
            attempt += 1
            continue
        return trace, False, "exhausted"


def run_real(script):
    it = iter(script)
    trace, logs = [], []

    def make(kind):
        def fn(log, hook):
            trace.append(kind)
            outcome = next(it)
            if outcome == "ok":
                return True
            log(ERROR_TEXT[outcome], "error")
            return False
        return fn

    try:
        outcome = download_with_retry(
            make("main"), retry_max=RETRY_MAX, retry_delays=(0,) * RETRY_MAX,
            url="https://example.com/v", log=lambda m, tag="info": logs.append(m),
            sleep=lambda _s: None,
            login_wall_fallback_fn=make("login"), client_retry_fallback_fn=make("client"))
    except StopIteration:
        # The code made more download calls than the model allows for any script.
        return trace, False, "made more calls than the model allows"
    # The reported FailureClass is classified on the whole last buffer and may say
    # "login" even after retries ran out, so read the stop reason from the log.
    if outcome.ok:
        reason = "ok"
    elif any("not retrying" in m for m in logs):
        reason = "permanent"
    elif any("attempts failed" in m for m in logs):
        reason = "exhausted"
    else:
        reason = "unknown"
    return trace, outcome.ok, reason


def main() -> int:
    bad, n = [], 0
    for script in itertools.product(OUTCOMES, repeat=RETRY_MAX + 3):
        n += 1
        want = model(script)
        got = run_real(script)
        # run_real may be asked for more outcomes than the model used; both stop early.
        if want != got:
            bad.append((script, want, got))
    print(f"retry_loop conformance: {n} scripts, {len(bad)} mismatches")
    for script, want, got in bad[:3]:
        print(f"  script={script}\n    model={want}\n    code ={got}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
