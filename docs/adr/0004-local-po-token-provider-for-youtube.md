# ADR-0004: A local PO Token generator, not cookies, clears YouTube's anti-bot check

- **Status:** Accepted
- **Date:** 2026-08-23
- **Context:** `install.bat` (PO Token provider setup), `orchestrator.LOGIN_WALL_FALLBACK_CLIENT`

## Context

YouTube's anti-bot check increasingly demands a GVS ("Google Video Server") PO
Token before it will serve format URLs to the https protocol, not just the
signature-cipher JS challenge yt-dlp already solves with deno (see the
`remote_components`/`js_runtimes` comment in `ytdlp_skill.py`). Without a valid
PO Token, a format either gets silently skipped ("require a GVS PO Token which
was not provided") or, worse, starts downloading and then 403s mid-stream —
which is what a plain browser-cookie session was standing in for: cookies
carry an implicit, YouTube-trusted PO Token for a subset of clients.

The symptom this fixes: `download_with_retry`'s login-wall fallback
(`LOGIN_WALL_FALLBACK_CLIENT = "tv_simply,android_vr,tv,web"`, orchestrator.py)
already existed and was already correct — but with no PO Token source, every
client in that list either got skipped for lacking one or 403'd anyway, so the
fallback always failed too. The user's only lever was re-exporting
`cookies.txt` from a logged-in browser, repeatedly, because cookies happened to
smuggle in a token good for a little while.

## Decision

**Install `bgutil-ytdlp-pot-provider`** (a yt-dlp plugin) and build its Node.js
token-generator script once, at the exact path
(`%USERPROFILE%\bgutil-ytdlp-pot-provider\server\build\generate_once.js`) the
plugin already auto-detects with zero configuration. `install.bat` step 5
clones the server source, `npm install`s it, and compiles it with the
`typescript` devDependency it already ships (`npx tsc` — no global installs).

**No code change to the download/retry path.** `getpot_bgutil_script.py`
(part of the pip package) hooks into yt-dlp's own PO Token provider framework
and is picked up automatically the moment the script exists on disk — the
existing `player_client` fallback list, `download_with_retry`, and
`classify_failure` logic in `orchestrator.py` needed no changes. Verified by
reproducing the exact failing case (`rXhGajRFLlY`, format `299+140`,
`tv_simply,android_vr,tv,web`) end-to-end: it now downloads a full 1080p50 file
with no cookies at all.

**Optional, not required.** `install.bat` checks for `git` and `node` on PATH
and skips this step with a warning (not an error) if either is missing —
matching the existing pattern for the Playwright Chromium install. A machine
without Node.js keeps working exactly as before (cookies still work as a
fallback); it just keeps hitting the login wall this ADR exists to remove.

**Rejected: running the PO Token provider as an HTTP server.** The plugin also
supports a long-lived `bgutil-ytdlp-pot-provider` server (Docker or `npm run
serve`) that yt-dlp talks to over `localhost:4416`. Rejected for a single-user
zero-touch app: it's a process to keep alive and restart across reboots for no
benefit over the `script-node` mode, which spawns node once per token request
(~1s) and needs nothing running in the background.

## Consequences

- New third-party dependency: `bgutil-ytdlp-pot-provider` (Python, in
  `requirements.txt`) plus its Node.js server source (not vendored — cloned by
  `install.bat`, like Playwright's browser binary).
- A machine setting this up for the first time needs Git and Node.js
  installed; both are checked for and the step degrades gracefully without
  them.
- YouTube's PO Token requirements will keep shifting (as they already have
  three times per `logs.md`); this ADR only claims the *mechanism* — a locally
  generated token beats a manually refreshed cookie — not that today's client
  list (`tv_simply,android_vr,tv,web`) stays correct forever.
