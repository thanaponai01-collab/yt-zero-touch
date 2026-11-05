# Download batch

An editor pastes one or more links, picks a quality, and starts the pipeline. The queue table tracks each item through to `Done`, and the output folder ends up holding a Premiere-safe H.264/AAC MP4 (or ProRes 422 Proxy MOV) that's recorded in history so it won't be downloaded twice.

## Sub-features

- `dl-start-button` starts the batch from the `START ZERO-TOUCH PIPELINE` button.
- `dl-start-shortcut` starts the batch with Ctrl+Enter in the URL box.
- `dl-output` writes a media file with h264 video and an audio stream.
- `dl-history` records the finished URL in `processed_urls.json`.
- `dl-guard` makes Start with no valid link log a warning and start nothing.

## How to get to it (user POV)

- Paste links into the TARGET LINKS box, then click `▶ START ZERO-TOUCH PIPELINE`.
- Paste links, then press Ctrl+Enter while the box has focus.

## Driving it with drive.py

Preconditions:

- `doctor` passes and the network is up.
- The instance's `downloads/` is empty, which is always true for a fresh run.

- **Button path.** Run `drive.py run download`. It clicks `720p HD`, types the default URL, and checks `1 link ready`. Then it clicks `START ZERO-TOUCH PIPELINE`, checks `downloading=True` and that the button shows `PIPELINE ACTIVE…`, and waits for the button to reset.
- **Shortcut path.** Run `drive.py run download --via shortcut`. It's the same journey, started by `<Control-Return>` on the URL box.
- **Other qualities.** Run `drive.py run download --preset "1080p FHD"`. For audio, use `--preset "Audio Only"`, which skips the video-codec checks.
- **Other URL.** Use `--url <link>`. Keep it short, because `--timeout` defaults to 300 s.
- **Proof.** `result.json` passes `queue row Done`, `media file written`, `video codec h264`, `has audio stream` and `history records URL`. The `03-finished.png` screenshot shows the row as `Done 100.0%` and the log ends with `Verified: output is clean H.264`. `ffprobe.json` lists the streams.

## Gotchas

- The default clip's MP4 also contains an embedded PNG thumbnail as a video stream. Assert that h264 is among the codecs, not that it's the only one.
- If the queue stays at `Queued` with `main thread is not in main loop` on stderr, someone replaced the mainloop pump with `update()`.
- `dl-guard` has no scenario yet. Only `tests/test_gui_smoke.py` covers it.
- YouTube can throttle or require login. If so, the row shows `Failed` and the log prints a remedy line. That's a failed run, so report the remedy rather than switching URLs until something passes.
