"""Drive the REAL _MergeSession / _TRANSCODE_GATE through every interleaving that
MergeGate.tla allows (2 workers, <= 2 merges each) and check the model's rules
on the real lock.  Also checks the container-commitment rule: every file the
session was told landed (or finished merging) is probed before verify() says OK.
Exit 0 = the code behaves as the model says.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from yt_zero_touch.core import transcode  # noqa: E402
from yt_zero_touch.core.transcode import TranscodePlan, merge_session  # noqa: E402

PLANS = {
    True: TranscodePlan(["x"], True, "non_h264", None),
    False: TranscodePlan(["x"], False, "h264", None),
}
MAX_MERGES = 2


def steps_for(needs_seq):
    """One worker's program: merge(needs) then end it by finish or by 'crash'
    (no merge_finished; the next merge_started or __exit__ must free the gate)."""
    prog = []
    for needs in needs_seq:
        prog += [("start", needs), ("end", None)]
    return prog


def worker_programs():
    for n in range(0, MAX_MERGES + 1):
        for needs_seq in itertools.product((True, False), repeat=n):
            for ends in itertools.product(("finish", "crash"), repeat=n):
                prog = []
                for needs, end in zip(needs_seq, ends):
                    prog += [("start", needs), (end, None)]
                yield prog


def run(progs, schedule):
    """Interleave non-blocking worker steps per `schedule` (list of worker idx).
    Returns None if the real gate ever breaks a model rule, else a description."""
    transcode._TRANSCODE_GATE = type(transcode._TRANSCODE_GATE)()  # fresh lock
    sessions = [merge_session(lambda *_: None, "mp4") for _ in progs]
    pcs = [0] * len(progs)
    needs_now = [False] * len(progs)
    exited = [False] * len(progs)

    def holders():
        return [i for i, s in enumerate(sessions) if s._holding_gate]

    for w in schedule:
        if exited[w]:
            continue
        if pcs[w] >= len(progs[w]):
            sessions[w].__exit__(None, None, None)
            exited[w] = True
        else:
            kind, needs = progs[w][pcs[w]]
            if kind == "start":
                # would block in _take_gate if another holds the real lock: skip the step
                other = [h for h in holders() if h != w]
                if needs and other and not sessions[w]._holding_gate:
                    continue
                if needs and other and sessions[w]._holding_gate:
                    continue
                sessions[w].merge_started(PLANS[needs], None)
                needs_now[w] = needs
            elif kind == "finish":
                sessions[w].merge_finished(None)
            pcs[w] += 1
        h = holders()
        if len(h) > 1:
            return f"two sessions hold the gate: {h}"
        for i in range(len(progs)):
            if sessions[i]._holding_gate != (transcode._TRANSCODE_GATE.locked() and h == [i]):
                return "session flag and real lock disagree"
            if sessions[i]._holding_gate and not needs_now[i]:
                return "a plan that does not need the gate holds it"
            if exited[i] and sessions[i]._holding_gate:
                return "exited session still holds the gate"
    for w in range(len(progs)):
        if not exited[w]:
            sessions[w].__exit__(None, None, None)
    if transcode._TRANSCODE_GATE.locked():
        return "gate still locked after every session exited"
    return None


def check_gate() -> int:
    programs = list(worker_programs())
    bad = n = 0
    for p1, p2 in itertools.product(programs, repeat=2):
        length = len(p1) + len(p2) + 2
        for schedule in itertools.product((0, 1), repeat=min(length, 10)):
            n += 1
            problem = run([p1, p2], schedule + (0,) * 12 + (1,) * 12)
            if problem:
                bad += 1
                if bad <= 3:
                    print(f"  gate violation: {problem}\n    programs={p1} | {p2}\n    schedule={schedule}")
    print(f"transcode_gate conformance (gate): {n} schedules, {bad} violations")
    return bad


def check_verification() -> int:
    """Container commitment: a file in `_outputs` (else `_finished`) must be probed."""
    probed, bad = [], 0
    real = transcode.verify_h264_output
    transcode.verify_h264_output = lambda p, log: (probed.append(p), p != "bad.mp4")[1]
    exists = Path.exists
    Path.exists = lambda self: True
    try:
        for finished, landed, container in itertools.product(
                ([], ["a.mp4"], ["bad.mp4"]), ([], ["a.mp4"], ["bad.mp4"]), ("mp4", "mkv")):
            probed.clear()
            s = merge_session(lambda *_: None, container)
            for f in finished:
                s.merge_started(PLANS[False], f)
                s.merge_finished(f)
            for f in landed:
                s.output_landed(f)
            ok = s.verify()
            expected_files = landed or finished
            if container == "mp4":
                want_ok = "bad.mp4" not in expected_files
                if sorted(probed) != sorted(expected_files) or ok != want_ok:
                    bad += 1
                    print(f"  verification mismatch: finished={finished} landed={landed} "
                          f"probed={probed} ok={ok}")
            elif probed or not ok:
                bad += 1
                print(f"  uncommitted container was probed or failed: {container} {probed} {ok}")
    finally:
        transcode.verify_h264_output = real
        Path.exists = exists
    print(f"transcode_gate conformance (verification): {bad} violations")
    return bad


if __name__ == "__main__":
    sys.exit(1 if (check_gate() + check_verification()) else 0)
