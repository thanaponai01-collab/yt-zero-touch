---- MODULE RetryLoop ----
\* Model of services/orchestrator.py: download_with_retry (one URL, one worker).
\* One loop iteration = one pass of `for attempt in range(1, retry_max + 2)`.
\* "calls" counts every invocation of any download_fn (main, login fallback,
\* client fallback).  The outcome of each call is chosen by the environment.
EXTENDS Naturals

CONSTANT RetryMax            \* policy.retry_max

VARIABLES phase,      \* start | running | classify | fallback | decide | ok | failed
          attempt,    \* loop counter, 1 .. RetryMax + 1
          calls,      \* total download_fn invocations
          cls,        \* classify_failure() of the slice that matters now
          fbKind,     \* which fallback is in flight
          loginFb,    \* login_wall_fallback_fn still set (not yet consumed)
          clientFb,   \* client_retry_fallback_fn still set
          fnAlt,      \* download_fn was replaced by the client fallback
          loginRuns, clientRuns,
          reason      \* none | ok | permanent | exhausted

vars == <<phase, attempt, calls, cls, fbKind, loginFb, clientFb, fnAlt,
          loginRuns, clientRuns, reason>>

Classes == {"none", "login", "client", "perm"}   \* none = unclassified (transient)
Permanent(c) == c \in {"login", "perm"}          \* FailureClass.permanent

Init == /\ phase = "start" /\ attempt = 1 /\ calls = 0 /\ cls = "none"
        /\ fbKind = "none" /\ loginFb = TRUE /\ clientFb = TRUE /\ fnAlt = FALSE
        /\ loginRuns = 0 /\ clientRuns = 0 /\ reason = "none"

Begin == /\ phase = "start" /\ phase' = "running"
         /\ UNCHANGED <<attempt, calls, cls, fbKind, loginFb, clientFb, fnAlt,
                        loginRuns, clientRuns, reason>>

\* `if download_fn(...)` : success returns ok, failure is classified.
CallMain ==
  /\ phase = "running" /\ calls' = calls + 1
  /\ \/ phase' = "ok" /\ reason' = "ok" /\ cls' = cls
     \/ \E c \in Classes : phase' = "classify" /\ cls' = c /\ UNCHANGED reason
  /\ UNCHANGED <<attempt, fbKind, loginFb, clientFb, fnAlt, loginRuns, clientRuns>>

TakeLoginFallback ==
  /\ phase = "classify" /\ cls = "login" /\ loginFb
  /\ loginFb' = FALSE /\ loginRuns' = loginRuns + 1
  /\ fbKind' = "login" /\ phase' = "fallback"
  /\ UNCHANGED <<attempt, calls, cls, clientFb, fnAlt, clientRuns, reason>>

TakeClientFallback ==
  /\ phase = "classify" /\ cls = "client" /\ clientFb
  /\ clientFb' = FALSE /\ clientRuns' = clientRuns + 1
  /\ fbKind' = "client" /\ phase' = "fallback"
  /\ UNCHANGED <<attempt, calls, cls, loginFb, fnAlt, loginRuns, reason>>

NoFallbackTaken ==
  /\ phase = "classify"
  /\ ~(cls = "login" /\ loginFb) /\ ~(cls = "client" /\ clientFb)
  /\ phase' = "decide"
  /\ UNCHANGED <<attempt, calls, cls, fbKind, loginFb, clientFb, fnAlt,
                 loginRuns, clientRuns, reason>>

\* fallback_fn(...) : success returns ok; failure re-classifies on its OWN slice.
CallFallback ==
  /\ phase = "fallback" /\ calls' = calls + 1
  /\ \/ phase' = "ok" /\ reason' = "ok" /\ UNCHANGED <<cls, fnAlt>>
     \/ \E c \in Classes :
          /\ phase' = "decide" /\ cls' = c /\ UNCHANGED reason
          /\ fnAlt' = IF fbKind = "client" THEN TRUE ELSE fnAlt
  /\ UNCHANGED <<attempt, fbKind, loginFb, clientFb, loginRuns, clientRuns>>

Decide ==
  /\ phase = "decide"
  /\ IF Permanent(cls)
        THEN /\ phase' = "failed" /\ reason' = "permanent" /\ UNCHANGED attempt
        ELSE IF attempt <= RetryMax
               THEN /\ attempt' = attempt + 1 /\ phase' = "running" /\ UNCHANGED reason
               ELSE /\ phase' = "failed" /\ reason' = "exhausted" /\ UNCHANGED attempt
  /\ UNCHANGED <<calls, cls, fbKind, loginFb, clientFb, fnAlt, loginRuns, clientRuns>>

Finished == /\ phase \in {"ok", "failed"} /\ UNCHANGED vars

Next == Begin \/ CallMain \/ TakeLoginFallback \/ TakeClientFallback
        \/ NoFallbackTaken \/ CallFallback \/ Decide \/ Finished

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

\* ---- rules ----
\* Each fallback runs at most once per URL, outside the retry_max budget.
FallbackAtMostOnce == loginRuns <= 1 /\ clientRuns <= 1
\* Total work is bounded: retry_max + 1 attempts plus the two one-shot fallbacks.
CallsBounded == calls <= RetryMax + 3
\* A permanent verdict is only ever given for a permanent class.
PermanentMeansPermanent == reason = "permanent" => Permanent(cls)
\* "Exhausted" is only reported after every attempt was used, never on a permanent class.
ExhaustedMeansAllTried == reason = "exhausted" => (attempt = RetryMax + 1 /\ ~Permanent(cls))
\* Switching to the alternate client only ever follows the client-retry fallback.
AltOnlyAfterClientFallback == fnAlt => clientRuns = 1
\* Once the default client is known broken we never go back to it.
AltIsSticky == [][fnAlt => fnAlt']_vars
\* Every run ends: ok or failed.
Terminates == <>(phase \in {"ok", "failed"})
====
