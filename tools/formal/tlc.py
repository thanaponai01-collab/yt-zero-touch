"""Run TLC (the TLA+ model checker) on one spec and report the verdict.

    python tools/formal/tlc.py SPEC.tla [--config SPEC.cfg] [--expect NAME ...]

Needs Java 11+ and tla2tools.jar.  The jar is looked up in $TLA2TOOLS, then in
tools/formal/.cache/tla2tools.jar, and its SHA-256 is checked against PINNED.
Exit 0: every rule held, or only the rules named with --expect (known findings)
broke.  Exit 1: an unexpected rule broke, an expected one held, or TLC errored.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINNED_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
JAR_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"


def find_jar() -> Path:
    jar = Path(os.environ.get("TLA2TOOLS") or HERE / ".cache" / "tla2tools.jar")
    if not jar.exists():
        sys.exit(f"tla2tools.jar not found at {jar}\n"
                 f"Download {JAR_URL} to tools/formal/.cache/tla2tools.jar "
                 f"(sha256 {PINNED_SHA256}) or set TLA2TOOLS.")
    got = hashlib.sha256(jar.read_bytes()).hexdigest()
    if got != PINNED_SHA256 and not os.environ.get("TLA2TOOLS"):
        sys.exit(f"tla2tools.jar sha256 {got} does not match the pinned {PINNED_SHA256}")
    return jar


def run_tlc(spec: Path, config: Path) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as meta:
        proc = subprocess.run(
            ["java", "-XX:+UseParallelGC", "-cp", str(find_jar()), "tlc2.TLC",
             "-workers", "1", "-metadir", meta,
             "-config", str(config), str(spec)],
            capture_output=True, text=True, cwd=spec.parent, timeout=600)
    return proc.returncode, proc.stdout + proc.stderr


def broken_rules(out: str) -> set[str]:
    rules = set(re.findall(r"Invariant (\w+) is violated", out))
    rules |= set(re.findall(r"Action property (\w+) is violated", out))
    if "Temporal properties were violated" in out:
        rules.add("TemporalProperty")
    return rules


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", type=Path)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--expect", nargs="*", default=[], help="known findings that must still break")
    ap.add_argument("--show", action="store_true", help="print the full TLC output")
    a = ap.parse_args()
    spec = a.spec.resolve()
    cfg = (a.config or spec.with_suffix(".cfg")).resolve()
    _code, out = run_tlc(spec, cfg)
    if a.show:
        print(out)
    broke = broken_rules(out)
    completed = "Model checking completed" in out
    states = re.search(r"(\d+) distinct states found", out)
    print(f"{spec.name}: {states.group(1) if states else '?'} distinct states; "
          f"broken rules: {sorted(broke) or 'none'}")
    if not completed and not broke:
        print(out[-2000:])
        print("TLC did not finish and reported no broken rule - treat as an error.")
        return 1
    unexpected = broke - set(a.expect)
    gone = set(a.expect) - broke
    if unexpected:
        print(f"UNEXPECTED break: {sorted(unexpected)}")
        if not a.show:
            print(out[-2500:])
        return 1
    if gone:
        print(f"Known finding no longer breaks: {sorted(gone)} - either the code was "
              "fixed (update the skill) or the model drifted from the code.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
