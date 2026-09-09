# ADR-0005: ProRes 422 Proxy is an opt-in second merge target, not a replacement

- **Status:** Accepted
- **Date:** 2026-09-07
- **Context:** `transcode_plan.py`, `ytdlp_skill._download_api`, `app.py`

## Context

H.264 is small and Premiere-native, but it's long-GOP — most frames are
deltas, not full images — which makes it worse for hard editing (scrubbing,
multicam) than an intra-only codec, and it loses a little quality on every
re-encode. ProRes 422 Proxy fixes both: every frame is a full image, and its
bitrate ceiling is high enough that a YouTube-sourced download (already
lossy, already 8-bit 4:2:0) shows no visible penalty versus higher ProRes
tiers. The cost is size — a Proxy file still runs several times larger than
the equivalent H.264 — and the loss of the stream-copy fast path: unlike a
VP9/AV1 source under `TRANSCODE_TO_H264`, an H.264 source can never be
copied into a ProRes-legal file, so a ProRes merge always re-encodes.

That size/speed cost is exactly why this isn't a default. Most downloads
don't get a hard edit; they get watched once or lightly cut. Forcing every
download to pay a full re-encode and several times the disk space for that
common case would be the wrong trade for the common case, made to serve the
uncommon one.

## Decision

Add ProRes 422 Proxy as a second `target_codec`, selected per download (the
"ProRes Proxy" checkbox next to Quality in `app.py`, or `--prores` on the
watcher CLI) — not a module-level constant like `TRANSCODE_TO_H264`, because
the right choice genuinely varies by *what this particular download is for*,
not by the machine it runs on.

H.264 stays the shipped default. `target_codec` defaults to `"h264"`
everywhere it's threaded through (`download()`, `BatchPolicy`, `watch()`),
so a caller that doesn't know about the new parameter gets the exact
behaviour this repo shipped with before this ADR.

The container commitment (ADR-0001/0003) generalises rather than duplicates:
`container_for()` now also forces `"mov"` for `target_codec="prores"`, on
the same promise-then-verify pattern mp4 already uses, and
`_MergeSession` derives which codec was promised from the container itself
(`_CONTAINER_COMMITMENTS = {"mp4": "h264", "mov": "prores"}`) rather than
taking a second parameter that could disagree with it.

## Consequences

- A ProRes merge always takes the transcode gate (`needs_gate` is now
  `will_transcode and encoder.kind != "nvenc"` rather than naming `libx264`
  specifically) — `prores_ks` is a software encoder with no GPU path wired
  up here, so concurrent ProRes encodes are exactly as RAM/CPU-risky as
  concurrent libx264 ones.
- `verify_h264_output` split into `_verify_output_codec(path, log,
  want_codec, want_label)` plus two one-line wrappers, so ProRes verification
  (`codec_name == "prores"`) reuses the same ffprobe-and-compare logic
  instead of a second copy of it.
- A user who wants ProRes for *every* download still has to tick the box
  every time — there is no ProRes equivalent of `TRANSCODE_TO_H264` to flip
  once. That's deliberate: making it sticky would reintroduce the
  wrong-default risk this ADR exists to avoid, and the checkbox state is
  already persisted in `settings.json` across app restarts.

## Alternatives rejected

**Make ProRes the default, keep H.264 as the opt-out.** Rejected directly by
the user this pipeline serves: most downloads aren't headed for a hard edit,
and defaulting to a several-times-larger, always-re-encoded output would tax
the common case to serve the uncommon one.

**A module-level switch, `MERGE_TARGET_CODEC`, like `TRANSCODE_TO_H264`.**
`TRANSCODE_TO_H264` is a machine-wide fact (does this Premiere version decode
VP9/AV1 natively) that's true or false for as long as the editor uses that
Premiere version. Which merge target a *download* wants isn't a machine
fact — it varies clip to clip — so it belongs on the call, not the module.
