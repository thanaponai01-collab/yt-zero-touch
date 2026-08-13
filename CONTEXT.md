# Context

What this project is, and the words it uses for its own parts. Seeded lazily —
terms land here when a piece of work actually resolves them, not upfront.

## What this is

A zero-touch downloader for a single video editor on a single Windows machine.
Paste links, get files that open in Premiere Pro without further handling. It
wraps yt-dlp (tracked on nightly), gallery-dl for image hosts, and Playwright
for resolving stream URLs on unknown sites.

Because it is one editor on one machine, several things that would normally be
settings are module-level constants — marked `ponytail:` in the source where
that choice was deliberate.

## Glossary

**Merge step** — the ffmpeg pass where yt-dlp muxes the separately-downloaded
video and audio streams into one file. Everything this project does to make a
file Premiere-safe happens here: container, codec, faststart.

**Merge session** (`transcode_plan._MergeSession`) — the owner of one
download's merge lifecycle. Holds the transcode gate, the merged files, and
their verification. Scoped to the *download*, not to one merge, because yt-dlp
reports a merge starting and finishing through two separate callbacks and one
download call can serve many merges. See ADR-0001.

**Container commitment** — the choice of output container, forced before any
codec is known because `YoutubeDL()` reads `merge_output_format` at
construction. When `TRANSCODE_TO_H264` is on this commits to mp4 on the
*promise* that a transcode will make it legal. The merge session collects on
that promise. See ADR-0003.

**Transcode gate** — a process-wide, non-reentrant lock permitting one heavy
software encode at a time. Concurrent 4K libx264 encodes stack multi-GB
allocations and can OOM the machine. NVENC buffers on the GPU and is not
gated. Only the merge session may touch it.

**Encoder** (`transcode_plan.Encoder`) — the H.264 encoder a transcode will
run, in the two vocabularies that must agree about it. Its **kind** (`nvenc`,
`libx264`) is for *branching* — it answers "does this need the transcode
gate". Its **name** (`h264_nvenc`, `libx264`) is the ffmpeg encoder, for
humans and for `ffmpeg -h encoder=…`. They coincide on the software path,
which is a trap rather than a convenience: code that logs the kind reads
correctly there and names a non-existent encoder on the GPU path. `name` is
derived from the args for that reason, never stored.

**Codec case** — which of three things `plan_transcode` found: a known H.264
codec, a known non-H.264 codec, or one it could not read at all. The third is
its own case because it leads to the same ffmpeg args as the second but must
not lead to the same log line. See ADR-0002.

**Batch policy** (`orchestrator.BatchPolicy`) — everything a run of URLs shares:
output dir, format, cookies, worker count, retry budget.

**Failure class** (`orchestrator.FailureClass`) — a classified download failure
carrying a human label, an actionable remedy, and whether retrying could ever
help. An unclassified failure is treated as transient and retried.

## Decisions

See `docs/adr/`.
