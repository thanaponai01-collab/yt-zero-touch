# ADR-0002: An undeterminable codec transcodes rather than copies

- **Status:** Accepted
- **Date:** 2026-08-13
- **Context:** `transcode_plan.plan_transcode`

## Context

`plan_transcode` reads the source codecs out of yt-dlp's postprocessor callback
payload. yt-dlp is tracked on **nightly**, so that payload's shape can change
without a release. When it does, the codec arrives as an empty string.

The original two-way prefix test treated an empty string as "not H.264". That
produced defensible behaviour — it transcoded — reached by indefensible
reasoning, and the log said so out loud: *"source is non-H.264"*, asserted as
fact about a source that was very often H.264. An editor chasing an
unexplained sixteen-minute encode on a 1080p download was told to look for a
VP9 source that never existed.

Two things were tangled: what to *do*, and what to *say*.

## Decision

Separate them.

**Do:** transcode. The container is already committed to mp4 (ADR-0001), so
stream-copying an unidentified video risks writing VP9-into-mp4 — the exact
artifact this module exists to prevent. A transcode is always container-legal
and always Premiere-safe.

**Say:** that codec detection failed, at `warn`. Not that the source was
non-H.264.

Carry the distinction on `TranscodePlan.codec_case` (`"h264"` / `"non_h264"` /
`"unknown"`) rather than leaving it inside a function body.

An unrecognised-but-present codec — a future `vvc1` — is **not** unknown. It is
a codec we can name, it is genuinely not H.264, and the existing handling is
already correct and already honest.

## Consequences

- We accept a possibly-needless encode over a possibly-broken file. For this
  user that is the right way round: a slow batch is an annoyance, a file that
  fails at edit time is lost work.
- The day yt-dlp's payload changes, downloads get slow and loud rather than
  failing. Every download failing would be a worse outcome than every download
  being slow.
- The `warn` is the early-warning signal for that upstream change. It is the
  reason the case is tested rather than left as a fallback that happens to
  work today.
