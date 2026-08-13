# ADR-0001: The merge decision is split across two entry points, and that is forced

- **Status:** Accepted
- **Date:** 2026-08-13
- **Context:** `transcode_plan.py`, `ytdlp_skill._download_api`

## Context

Deciding what happens to a downloaded file needs the codecs yt-dlp actually
selected. Choosing the output container does not — but yt-dlp reads
`merge_output_format` inside `YoutubeDL(...)`, at construction, long before any
format is picked. The merge step's ffmpeg args, by contrast, are read live from
`postprocessor_args["merger"]` immediately before the merger runs, once the real
codecs are known.

So one decision has to be made in two places at two times:

    container_for(audio_only)        early, building ydl_opts
    plan_transcode(vcodec, acodec)   late, once codecs are known

This reads like an accident and has been mistaken for one. It is not.

Worse, the early call has to *predict* the late one: `container_for` returns
`"mp4"` on the assumption that `plan_transcode` will later choose a transcode
that makes mp4 legal.

## Decision

Keep the split. Do not attempt to unify the two entry points, defer the
container choice, or reconstruct `YoutubeDL` once codecs are known.

Instead, make the coupling explicit and check it: the container commitment is
passed to the merge session, which verifies after the download that the
promise was kept (ADR-0003).

## Consequences

- The module docstring and both functions state the ordering constraint, so a
  reader does not have to discover that one predicts the other.
- A future contributor who "tidies" this into one call will break the
  container for every VP9 source. This ADR exists to be found first.
- The prediction can be wrong. That is why ADR-0003 measures the outcome
  rather than trusting it.

## Alternatives rejected

**Defer the container by rebuilding YoutubeDL.** Would mean extracting info,
tearing down, and reconstructing with the real codecs known — two network
round-trips per download and a second code path for the section-trim and
playlist cases.

**Always use mkv.** Legal for every codec, and sidesteps the prediction
entirely. Rejected because the editor's requirement is Premiere-first, and mkv
is the container Premiere handles worst.
