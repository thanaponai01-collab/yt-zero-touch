---- MODULE BatchFlow ----
\* User-flow version of tools/formal/batch_history/BatchPipeline.tla: the editor
\* pastes a page link "A" (it holds two videos) and a single link "B", runs the
\* batch on an empty history, and, if something failed, runs the same batch again.
EXTENDS Naturals

CONSTANT MaxWorkers

Items == {"i1", "i2", "i3"}
Urls  == {"a", "b"}
UrlOf == [i \in Items |-> IF i = "i3" THEN "b" ELSE "a"]

VARIABLES hist0, hist, st, got, runs
vars == <<hist0, hist, st, got, runs>>
Terminal == {"skipped", "done", "failed"}

Init == /\ hist0 = {} /\ hist = {} /\ st = [i \in Items |-> "pending"]
        /\ got = [i \in Items |-> FALSE] /\ runs = 1

Resolve(i) ==
  /\ st[i] = "pending"
  /\ st' = [st EXCEPT ![i] = IF UrlOf[i] \in hist0 THEN "skipped" ELSE "queued"]
  /\ UNCHANGED <<hist0, hist, got, runs>>

Busy == (IF st["i1"] = "downloading" THEN 1 ELSE 0) + (IF st["i2"] = "downloading" THEN 1 ELSE 0)
       + (IF st["i3"] = "downloading" THEN 1 ELSE 0)

AllResolved == \A i \in Items : st[i] # "pending"

Start(i) ==
  /\ AllResolved /\ st[i] = "queued"
  /\ Busy < MaxWorkers
  /\ st' = [st EXCEPT ![i] = "downloading"]
  /\ UNCHANGED <<hist0, hist, got, runs>>

Succeed(i) ==
  /\ st[i] = "downloading"
  /\ st' = [st EXCEPT ![i] = "done"]
  /\ got' = [got EXCEPT ![i] = TRUE]
  /\ hist' = hist \cup {UrlOf[i]}
  /\ UNCHANGED <<hist0, runs>>

Fail(i) ==
  /\ st[i] = "downloading"
  /\ st' = [st EXCEPT ![i] = "failed"]
  /\ UNCHANGED <<hist0, hist, got, runs>>

\* The editor sees a failure and runs the same batch again (once).
RunAgain ==
  /\ runs < 2 /\ (\A i \in Items : st[i] \in Terminal) /\ (\E i \in Items : st[i] = "failed")
  /\ runs' = runs + 1 /\ hist0' = hist
  /\ st' = [i \in Items |-> "pending"]
  /\ UNCHANGED <<hist, got>>

Finished == (\A i \in Items : st[i] \in Terminal) /\ (runs = 2 \/ \A i \in Items : st[i] # "failed")
            /\ UNCHANGED vars

Next == (\E i \in Items : Resolve(i) \/ Start(i) \/ Succeed(i) \/ Fail(i)) \/ RunAgain \/ Finished
Spec == Init /\ [][Next]_vars

\* What the editor relies on: "skipped as already downloaded" must be true.
NothingSkippedUnseen == \A i \in Items : st[i] = "skipped" => got[i]
====
