# ADR-0004: A leftover `.part` is not evidence — the partial-file guard is gone

- **Status:** Accepted
- **Date:** 2026-08-13
- **Context:** `watcher._harvest_completed` (was `watcher.watch`), former
  `ytdlp_skill.has_partial_files`
- **Supersedes:** nothing; **relies on** ADR-0003

## Read this before adding a `.part` check back

The watcher used to re-judge a finished download by looking at the output
directory: if any `*.part` file was there, the download was reported failed and
kept out of history, so it was downloaded again next pass. It looks like a
cheap safety net. It is not a net; it is a false-positive machine, and it costs
a full re-download of a file that was already correct.

## Context

Observed live, in one output directory:

```
24,989,658  3 - AUM 10 ล้าน … - [33MyN1azEss].f315.webm.part
876,753,595 3 - AUM 10 ล้าน … - [33MyN1azEss].mp4      <- complete, correct
```

The `.part` is an abandoned format-315 attempt. The `.mp4` is the same
download's finished, merged, ffprobed output. The guard saw the first and threw
away the second.

Two things make the check unsound, and the second is the one that kills every
narrower version of it:

**1. The check is directory-scoped, the question is download-scoped.** The
watcher runs a `ThreadPoolExecutor`; any other worker's in-flight `.part` marks
*this* finished download partial. Stale debris from an earlier run does the same
to every download in that directory until someone deletes it by hand.

**2. A successful download cannot leave its own `.part` behind.** Verified
against the installed yt-dlp (2026.07.23.234303): `.part` is only ever a temp
name, renamed to the final name on success (`downloader/http.py`,
`downloader/fragment.py` — `try_rename`), and any error, including one swallowed
by `ignoreerrors`, sets `_download_retcode = 1` (`YoutubeDL.py`), which
`download()` returns and `_download_api` turns into `False`. So whenever the
guard fires on a *successful* download, what it found belongs to some other
attempt by construction.

That is why scoping the glob to the video id — the obvious repair — does not
work: in the case above both files carry `[33MyN1azEss]`, so an id-scoped guard
fails the same download. Nor can the guard be scoped to "the files this download
produced": after a successful merge the component streams are deleted, so there
is nothing left to assert on, while the debris from a failed earlier attempt
shares the same stem. There is no version of this check that fires on a real
failure and stays quiet on this one.

## Decision

**Delete the guard, and the helper behind it.** A truthy `DownloadOutcome` is
recorded as done.

**What covers the failure it was aimed at.** A download reports success only
when yt-dlp returned 0 *and* every merged file passed its `ffprobe`
(ADR-0003) — a truncated or corrupt output is unreadable and fails there. The
guard predates that verification and was never re-examined against it.

**Leftover `.part` files are left alone.** They are yt-dlp's resume state:
byte-accurate, and reused if the same format is selected again. Deleting them
to keep the directory tidy would make every retry pay from zero.

## Consequences

- A download whose earlier attempt abandoned a format is now recorded as done
  and never re-downloaded. That is the whole point.
- Debris accumulates: a `.part` for a format that is never selected again is
  never cleaned up by anything. Disk cost only — nothing reads it, nothing is
  judged by it. If that ever becomes a real problem it is a housekeeping job
  (age-based sweep) and not a correctness one.
- Audio-only and gallery-dl downloads still have no post-download verification
  of their own — `_MergeSession.verify` passes trivially when the container was
  never committed to mp4. The removed guard did not cover them either
  (yt-dlp's return code does), so this is a pre-existing gap, not a new one.
