"""Run the REAL run_batch on every scenario BatchPipeline.tla explores and
compare the history it leaves with the model.  Also reproduces the known
finding NoVideoLeftBehind on real code.

Exit 0 = the code matches the model AND the known finding still reproduces
(exactly the scenarios the model predicts).  Exit 1 otherwise.
"""
from __future__ import annotations

import itertools
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_zero_touch.core.history import HistoryStore  # noqa: E402
from yt_zero_touch.core.models import BatchPolicy  # noqa: E402
from yt_zero_touch.services.orchestrator import run_batch  # noqa: E402

BATCH = ["a", "b"]                       # urls pasted, in order
FANOUT = {"a": ["a/1", "a/2"], "b": ["b/1"]}   # what resolve returns
URL_OF = {"a/1": "a", "a/2": "a", "b/1": "b"}


class FakeDownloader:
    def __init__(self, ok_items):
        self.ok_items = ok_items

    def download(self, resolved, **_kw):
        return resolved in self.ok_items


def real(hist0, force, ok_items):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "history.json"
        store = HistoryStore(path)
        for u in hist0:
            store.add(u)
        res = run_batch(
            BATCH, BatchPolicy(out_dir=Path(d) / "out", force=force, max_workers=2,
                               retry_max=0, retry_delays=()),
            FakeDownloader(ok_items), history=store, log=lambda *_: None,
            resolve_fn=lambda url, **_kw: FANOUT[url], playwright_ok=False)
        return set(store.urls), res


def model(hist0, force, ok_items):
    skipped = {u for u in BATCH if u in hist0 and not force}
    items = [i for i in URL_OF if URL_OF[i] not in skipped]
    done = {i for i in items if i in ok_items}
    return hist0 | {URL_OF[i] for i in done}, len(items), len(done)


def main() -> int:
    mismatches, findings = [], []
    for hist0 in map(set, itertools.chain.from_iterable(
            itertools.combinations(BATCH, r) for r in range(3))):
        for force in (False, True):
            for ok in map(set, itertools.chain.from_iterable(
                    itertools.combinations(URL_OF, r) for r in range(4))):
                got_hist, res = real(hist0, force, ok)
                want_hist, total, succeeded = model(hist0, force, ok)
                if (got_hist, res.total, res.succeeded, res.failed) != (
                        want_hist, total, succeeded, total - succeeded):
                    mismatches.append((hist0, force, ok, got_hist, res))
                for u in got_hist - hist0:
                    siblings = [i for i in URL_OF if URL_OF[i] == u]
                    if any(i not in ok for i in siblings):
                        findings.append((tuple(sorted(hist0)), force, tuple(sorted(ok)), u))
    print(f"batch_history conformance: {len(mismatches)} mismatches with the model")
    for m in mismatches[:3]:
        print("  ", m)
    # The model says NoVideoLeftBehind breaks exactly when some url has a done and a
    # not-done sibling (and is not skipped by history).  Real code must agree.
    expected = {
        (tuple(sorted(h)), f, tuple(sorted(o)), "a")
        for h in map(set, ([], ["b"])) for f in (False, True)
        for o in map(set, itertools.chain.from_iterable(
            itertools.combinations(URL_OF, r) for r in range(4)))
        if len({"a/1", "a/2"} & o) == 1
    }
    got = {x for x in findings if x[3] == "a"}
    print(f"known finding NoVideoLeftBehind reproduces in {len(got)} real scenarios "
          f"(model predicts {len(expected)})")
    ok = not mismatches and got == expected and len(got) > 0
    if got != expected:
        print("  real-code finding set differs from the model's prediction")
        print("  only real:", sorted(got - expected)[:3], " only model:", sorted(expected - got)[:3])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
