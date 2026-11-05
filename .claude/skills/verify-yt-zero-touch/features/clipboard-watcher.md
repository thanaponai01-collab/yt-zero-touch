# Clipboard watcher

While the `Clipboard Watcher` pill is ON, any link copied anywhere in Windows lands in the URL box within about 1 s, without duplicates.

## Sub-features

- `clip-on` turns the watcher on, flips the pill to `● Clipboard Watcher: ON` and logs the ON message.
- `clip-insert` adds a newly copied link to the box.

## How to get to it (user POV)

- Click `○ Clipboard Watcher: OFF` at the top right of the TARGET LINKS card, then copy a link in any app.

## Driving it with drive.py

Preconditions:

- No other run or person is using the clipboard. The scenario saves the clipboard and restores it afterward.

- **Watch.** Run `drive.py run clipboard`. It clicks `Clipboard Watcher`, puts `https://clip-test.com/v3` on the system clipboard, and pumps the mainloop until the 1 s poll fires.
- **Proof.** The URL box contains the link, and `01-after-copy.png` shows it with the pill ON.

## Gotchas

- The clipboard is shared system-wide. Never run this alongside another run, or while the user is copying.
- Whatever was on the clipboard when the watcher was switched on is ignored. Only a *change* is inserted.
