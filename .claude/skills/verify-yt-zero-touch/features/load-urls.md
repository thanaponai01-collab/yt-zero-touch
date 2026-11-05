# Load urls.txt

`Load urls.txt` reads the `urls.txt` next to the app, appends any links not already in the URL box, and updates the link counter.

## Sub-features

- `load-append` appends new links from the file.
- `load-dedupe` skips links that are already in the box.
- `load-missing` logs `urls.txt does not exist yet.` when there's no file.

## How to get to it (user POV)

- Click `📂 Load urls.txt` under the URL box.

## Driving it with drive.py

Preconditions:

- The scenario writes `urls.txt` into the instance dir with `https://a.com/v1`, `https://b.com/v2` and `https://c.example/v3`, standing in for the user saving the file.

- **Load.** Run `drive.py run load-urls`. It types `https://a.com/v1` into the box, then clicks `Load urls.txt`.
- **Proof.** `a.com/v1` appears exactly once, `b.com/v2` and `c.example/v3` have been appended, and the counter reads `3 links ready`. `01-after-load.png` shows all three lines.

## Gotchas

- The `c.example` link guards the long-TLD fix in `URL_RE`. If only it goes missing and the counter reads `2 links ready`, the regex has regressed to its old 6-character TLD cap.
- `load-missing` has no scenario yet.
