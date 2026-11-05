# Settings memory

The quality, toggles, output folder, cookies and trim range an editor picks are restored the next time the app opens.

## Sub-features

- `settings-quality` restores the chosen preset after a relaunch.
- `settings-toggle` restores a toggled subtitle pill after a relaunch.

## How to get to it (user POV)

- Change settings, close the window with X, and open the app again. Nothing else to do.

## Driving it with drive.py

Preconditions:

- A fresh instance with no `settings.json`.

- **Change, close, reopen.** Run `drive.py run settings-restart`. It clicks `720p HD` and `Thai (th)`, closes through `App._on_close` (the X button path), and builds a new `App` on the same `base_dir`.
- **Proof.** After the relaunch, quality is `720p` and Thai subs are on. `01-relaunched.png` shows the `720p HD` chip active and `● Thai (th)`.

## Gotchas

- The relaunch runs in the same Python process with a second Tk root. If it ever flakes with `tk.tcl`, the launch retry covers it. Persistent failure is a real bug.
- The output folder, cookies and trim range aren't asserted yet.
