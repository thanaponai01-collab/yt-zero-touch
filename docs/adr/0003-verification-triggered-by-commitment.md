# ADR-0003: Verification is triggered by the container commitment and arbitrated by ffprobe

- **Status:** Accepted
- **Date:** 2026-08-13
- **Context:** `transcode_plan._MergeSession.verify`, `verify_h264_output`

## Read this before removing the ffprobe

Every merged download runs one `ffprobe`, even the fast H.264 stream-copy path
that obviously did not transcode. That looks like waste. It is not, and
removing it silently restores a bug that shipped.

## Context

The H.264 check used to run only when a transcode had been *recorded*
(`did_transcode`). The recording happened in the same callback that applied the
transcode decision — so any path where that callback did not fire, or fired and
was abandoned, skipped both the transcode *and* the check that exists to catch
a skipped transcode. The guard was disarmed by precisely the failure it
guarded against.

The fix is not a better bookkeeping flag. Any flag has the same defect: it is
written by the code whose correctness is in question.

## Decision

**Trigger on the container commitment.** `container_for` forces mp4 before any
codec is known (ADR-0001). Whenever that commitment was made and a merge
actually ran, the output is probed.

**Let ffprobe arbitrate.** There is no separate "the commitment was not
honoured" rule. Reading the file answers the only question that matters:

| Situation | ffprobe reads | Outcome |
|---|---|---|
| H.264 source, stream copy | `h264` | passes |
| VP9 source, transcode ran | `h264` | passes |
| VP9 source, transcode skipped | `vp9` | **fails** |
| Corrupt / truncated output | unreadable | **fails** |

A bookkeeping rule written the obvious way — *"mp4 was committed but no
transcode was recorded, therefore fail"* — would fail row one, which is nearly
every download in an ordinary batch. The commitment is universal; a transcode
is not.

**Probe every merged file, after the download call.** One `ydl.download()` call
serves a whole playlist, so a single-slot record verified entry five and called
the playlist done. Paths are captured at the merge's `started` callback, where
`FFmpegMergerPP` has already resolved its output path — and, unlike the
`finished` payload, that survives a merge that crashes. Probing runs after the
download rather than at each `finished`, because `FFmpegMetadata` and
`EmbedThumbnail` rewrite the file after the merger.

**A failed probe is permanent.** `FailureClass("output_unverified",
permanent=True)`. Unclassified means transient, and a 4K source would pay for
four full sixteen-minute encodes to reach the same verdict.

## Consequences

- One ~50ms subprocess per merged download. Against a download measured in
  seconds-to-minutes, immaterial.
- Nothing the check consults is capable of lying, so it cannot be disarmed by
  the bug it detects.
- `did_transcode` lost its last consumer and was removed.
- If `ffprobe` is absent the check is skipped and says so once per process —
  a property of the machine, not of the download.
