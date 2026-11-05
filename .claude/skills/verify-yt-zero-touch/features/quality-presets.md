# Quality presets and toggles

The ENCODING PRESET & QUALITY chips choose the download quality. The pill toggles choose ProRes 422 Proxy output, English or Thai subtitles, and whether history is skipped. The Profile summary line updates as you change them, and every change is saved to `settings.json` straight away.

## Sub-features

- `preset-select` makes the chip that's clicked the active quality.
- `toggle-prores` switches ProRes 422 Proxy on and flips the pill to ●.
- `toggle-persist` saves every chip or toggle click to `settings.json`.

## How to get to it (user POV)

- Click a chip: `Best`, `4K / 2160p`, `1440p QHD`, `1080p FHD`, `720p HD`, `Audio Only` or `Photos / dl`.
- Click a pill: `○ ProRes 422 Proxy [MOV]`, `○ English (en)`, `○ Thai (th)` or `○ Skip History`.

## Driving it with drive.py

Preconditions:

- A fresh instance, where quality defaults to `Best` and every toggle is off.

- **Chips.** Run `drive.py run preset`. It clicks `720p HD`, `Audio Only` and `Photos / dl` in turn and checks that quality becomes `720p`, `Audio only` and then `Photos`, with a screenshot after each.
- **ProRes.** The same run clicks `ProRes 422 Proxy` and checks `prores_proxy` is true.
- **Proof.** The instance's `settings.json` has `"prores_proxy": true` and `"quality": "Photos"`. Each `.state.json` `summary` field shows the matching Profile text.

## Gotchas

- The chip label and the stored quality value are different strings: `720p HD` is stored as `720p`, and `Audio Only` as `Audio only`. Assert on the stored value.
- To prove a preset changes the *file* rather than just the setting, use `download --preset ...` and check `ffprobe.json`.
- The English, Thai and Skip History pills aren't scripted here. Only Thai is covered, by settings-restart.
