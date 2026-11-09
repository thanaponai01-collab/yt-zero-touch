---- MODULE MergeGate ----
\* Model of core/transcode.py: _MergeSession + the module-level _TRANSCODE_GATE lock.
\* Each worker owns one _MergeSession (one download) and may report several merges.
\* merge_started / merge_finished / __exit__ are the three places the gate is
\* released; _take_gate is the only place it is acquired.
EXTENDS Naturals

CONSTANTS Workers, MaxMerges

VARIABLES gate,      \* "none" or the worker holding _TRANSCODE_GATE
          pc,        \* idle | begun | wanting | merging | exited
          holding,   \* _MergeSession._holding_gate
          merges,    \* merges started so far by this session
          needs      \* current plan.needs_gate

vars == <<gate, pc, holding, merges, needs>>

Init == /\ gate = "none"
        /\ pc = [w \in Workers |-> "idle"]
        /\ holding = [w \in Workers |-> FALSE]
        /\ merges = [w \in Workers |-> 0]
        /\ needs = [w \in Workers |-> FALSE]

\* Release this worker's gate if it holds one (_free_gate).
Release(w) == /\ gate' = IF holding[w] THEN "none" ELSE gate
              /\ holding' = [holding EXCEPT ![w] = FALSE]

\* merge_started, first half: frees a gate left from a merge that never reported back.
\* From "merging" this is that unreported-end case; from "idle" it is the normal case.
StartMerge(w) ==
  /\ pc[w] \in {"idle", "merging"} /\ merges[w] < MaxMerges
  /\ merges' = [merges EXCEPT ![w] = @ + 1]
  /\ pc' = [pc EXCEPT ![w] = "begun"]
  /\ Release(w)
  /\ UNCHANGED needs

\* merge_started, second half: plan.needs_gate decides whether to queue for the gate.
Decide(w) ==
  /\ pc[w] = "begun"
  /\ \E n \in BOOLEAN :
       /\ needs' = [needs EXCEPT ![w] = n]
       /\ pc' = [pc EXCEPT ![w] = IF n THEN "wanting" ELSE "merging"]
  /\ UNCHANGED <<gate, holding, merges>>

\* _take_gate: blocks until the lock is free, then holds it.
Acquire(w) ==
  /\ pc[w] = "wanting" /\ gate = "none"
  /\ gate' = w
  /\ holding' = [holding EXCEPT ![w] = TRUE]
  /\ pc' = [pc EXCEPT ![w] = "merging"]
  /\ UNCHANGED <<merges, needs>>

\* merge_finished
Finish(w) ==
  /\ pc[w] = "merging"
  /\ pc' = [pc EXCEPT ![w] = "idle"]
  /\ Release(w)
  /\ UNCHANGED <<merges, needs>>

\* __exit__ : runs on success, failure and exceptions alike.
Exit(w) ==
  /\ pc[w] \in {"idle", "merging"}
  /\ pc' = [pc EXCEPT ![w] = "exited"]
  /\ Release(w)
  /\ UNCHANGED <<merges, needs>>

AllExited == \A w \in Workers : pc[w] = "exited"
Finished == AllExited /\ UNCHANGED vars

Next == \/ \E w \in Workers : StartMerge(w) \/ Decide(w) \/ Acquire(w) \/ Finish(w) \/ Exit(w)
        \/ Finished

Spec == Init /\ [][Next]_vars
        /\ \A w \in Workers : WF_vars(StartMerge(w)) /\ WF_vars(Decide(w))
                              /\ WF_vars(Finish(w)) /\ WF_vars(Exit(w)) /\ SF_vars(Acquire(w))

\* ---- rules ----
\* Two software encodes never run at once (OOM guard for 4K footage).
AtMostOneEncodes == \A a, b \in Workers : (holding[a] /\ holding[b]) => a = b
\* The session flag and the lock agree.
FlagMatchesLock == \A w \in Workers : holding[w] = (gate = w)
\* Only a plan that needs the gate (a software encode) ever holds it.
OnlyGatedPlansHold == \A w \in Workers : holding[w] => needs[w]
\* A finished session never keeps the lock.
ExitReleases == \A w \in Workers : pc[w] = "exited" => ~holding[w]
\* When every session is done the lock is free.
NoLeakWhenDone == AllExited => gate = "none"
\* Nobody waits forever: every session eventually ends (no deadlock, no leaked lock).
EveryoneFinishes == <>AllExited
====
