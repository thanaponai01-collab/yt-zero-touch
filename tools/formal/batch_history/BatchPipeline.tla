---- MODULE BatchPipeline ----
\* Model of services/orchestrator.py: run_batch (resolve everything, then download
\* with a worker pool) and the history writes that follow each success.
\* Three work items; i1 and i2 come from ONE page url "a" (fan-out: one page that
\* embeds two videos, or the same url pasted twice), i3 comes from url "b".
EXTENDS Naturals, FiniteSets

CONSTANT MaxWorkers          \* policy.max_workers

Items == {"i1", "i2", "i3"}
Urls  == {"a", "b"}
UrlOf == [i \in Items |-> IF i = "i3" THEN "b" ELSE "a"]

VARIABLES hist0,    \* history on disk when the batch started
          force,    \* policy.force
          hist,     \* history now
          st        \* item status: pending | skipped | queued | downloading | done | failed

vars == <<hist0, force, hist, st>>
Terminal == {"skipped", "done", "failed"}

Init == /\ hist0 \in SUBSET Urls /\ force \in BOOLEAN /\ hist = hist0
        /\ st = [i \in Items |-> "pending"]

\* Phase 1: `if url in history_set and not policy.force` -> skipped, else queued.
Resolve(i) ==
  /\ st[i] = "pending"
  /\ st' = [st EXCEPT ![i] = IF UrlOf[i] \in hist0 /\ ~force THEN "skipped" ELSE "queued"]
  /\ UNCHANGED <<hist0, force, hist>>

AllResolved == \A i \in Items : st[i] # "pending"

\* Phase 2 starts only after every url is resolved; at most max_workers run at once.
Start(i) ==
  /\ AllResolved /\ st[i] = "queued"
  /\ Cardinality({j \in Items : st[j] = "downloading"}) < MaxWorkers
  /\ st' = [st EXCEPT ![i] = "downloading"]
  /\ UNCHANGED <<hist0, force, hist>>

\* outcome.ok -> history.add(url) immediately, per item.
Succeed(i) ==
  /\ st[i] = "downloading"
  /\ st' = [st EXCEPT ![i] = "done"]
  /\ hist' = hist \cup {UrlOf[i]}
  /\ UNCHANGED <<hist0, force>>

Fail(i) ==
  /\ st[i] = "downloading"
  /\ st' = [st EXCEPT ![i] = "failed"]
  /\ UNCHANGED <<hist0, force, hist>>

Finished == (\A i \in Items : st[i] \in Terminal) /\ UNCHANGED vars

Next == (\E i \in Items : Resolve(i) \/ Start(i) \/ Succeed(i) \/ Fail(i)) \/ Finished
Spec == Init /\ [][Next]_vars

\* ---- rules ----
ConcurrencyBounded == Cardinality({j \in Items : st[j] = "downloading"}) <= MaxWorkers
\* Only urls already in history (and not forced) are skipped.
SkipOnlyKnown == \A i \in Items : st[i] = "skipped" => (UrlOf[i] \in hist0 /\ ~force)
\* A finished item is recorded.
DoneIsRecorded == \A i \in Items : st[i] = "done" => UrlOf[i] \in hist
\* History only grows from successes.
HistoryOnlyFromSuccess ==
  \A u \in hist \ hist0 : \E i \in Items : UrlOf[i] = u /\ st[i] = "done"
\* The promise a user relies on: a url recorded as downloaded by THIS batch had
\* every one of its videos downloaded, so re-running the batch never silently
\* drops a video that failed.
NoVideoLeftBehind ==
  \A u \in hist \ hist0 : \A i \in Items : UrlOf[i] = u => st[i] = "done"
====
