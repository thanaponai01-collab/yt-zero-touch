# CLI watcher

`python watcher.py` watches a `urls.txt`. Each time the file is saved with a new link, the watcher queues that link, downloads it as a Premiere-ready H.264/AAC MP4, and records it in the history file, so it's skipped next time. By default the history is the repo-root `processed_urls.json` that the GUI also uses.

## Sub-features

- `watch-detect` makes a newly saved link print `Queued (known): <url>`.
- `watch-download` writes the media file and prints `Done: <url>`.
- `watch-history` records the finished URL in the history file.
- `watch-history-flag` lets `--history <file>` keep a separate history and leave the shared one alone.

## How to get to it (user POV)

- Run `python watcher.py` (optionally with `-f <urls file> -o <output dir>`), then paste a link into the file and save.

## Driving it with drive.py

Preconditions:

- `doctor` passes and the network is up.

- **Watch and download.** Run `drive.py run watcher`. It starts `watcher.py -f <instance>/urls.txt -o <instance>/downloads --history <instance>/processed_urls.json --max-workers 1` as a subprocess and waits for the banner. Then it appends the default URL to `urls.txt`, the way a user saves the file, and waits until the URL appears in the private history.
- **Proof.** `result.json` passes `URL queued`, `history records URL`, `transcript says Done`, `media file written`, `video codec h264`, `has audio stream` and `repo-root processed_urls.json untouched`. `watcher-stdout.txt` is the full transcript, `watcher-cmd.txt` is the exact command, and `ffprobe.json` lists the streams.

## Gotchas

- The watcher's clean exit is Ctrl+C, which a detached child process can't receive on Windows, so the scenario stops it with `taskkill /T /F`. History is saved as each URL finishes, so nothing is lost, but the shutdown summary (`Session stats`) never prints. Don't assert on it.
- Without `--history`, a real run writes the user's repo-root `processed_urls.json`. Every scripted run must pass `--history`.
- If the URL is already in the history file, the watcher prints `Skipped (already done)` and downloads nothing. A fresh instance always starts empty.
