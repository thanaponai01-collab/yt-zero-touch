# YT-DLP Zero-Touch

A Windows desktop app that downloads video from YouTube and 1000+ other sites,
plus photos and carousels from Instagram, Twitter/X, Reddit and more.  
Paste a URL, pick a quality, get a Premiere-ready MP4 (or a folder of images) —
no terminal needed.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

---

## Features

- Paste one or multiple URLs — concurrent downloads (up to 3 at once)
- Quality selector: Best, 4K, 1080p, 720p, 480p, Audio only
- **Photos mode** — download images & carousels via gallery-dl (Instagram, Twitter/X,
  Reddit, Pinterest, Imgur, Tumblr, …); image links also fall back to it automatically
- H.264 / AAC output — drops straight into Premiere Pro
- Unknown sites: headless-browser stream interception (scans network requests **and**
  response bodies, dismisses consent walls, triggers lazy players)
- Subtitle download (English, Thai)
- Cookie support (file or extract live from Chrome/Firefox/Edge/Brave)
- Auto-retry on transient failures with backoff
- Skips already-downloaded URLs (history tracked locally)
- Desktop notification when done
- One-click updater for **yt-dlp + gallery-dl** — also runs quietly in the background
  once a week so extractors stay fresh

---

## Requirements

| Requirement | Notes |
|---|---|
| **Python 3.10+** | [python.org/downloads](https://www.python.org/downloads/) — check "Add to PATH" |
| **FFmpeg** | Required for merging video + audio |
| Internet connection | For package install |

---

## Install (new PC)

```
1. Install Python 3.10+ (check "Add Python to PATH")
2. Install FFmpeg (see below)
3. Clone or download this repo
4. Double-click  install.bat
5. Double-click  run.bat
```

### FFmpeg — pick one method

```bat
# Option A — winget (built into Windows 10/11)
winget install --id Gyan.FFmpeg -s winget

# Option B — Chocolatey
choco install ffmpeg

# Option C — Manual
# Download from https://ffmpeg.org/download.html
# Extract and add the bin/ folder to your system PATH
```

After installing FFmpeg, re-run `install.bat` to verify it is detected.

---

## Running

```bat
run.bat
```

Or directly:

```bat
python app.py
```

---

## Usage

1. Paste one or more video URLs into the text box (one per line)
2. Choose quality from the dropdown
3. Optionally set an output folder, cookies, or subtitles
4. Click **DOWNLOAD** (or press `Ctrl+Enter`)

Downloads are saved to a `downloads/` folder next to the app by default.

### Downloading photos (Instagram, Twitter/X, Reddit, …)

Pick **Photos** in the Quality dropdown, paste the post / profile URL, and click
**DOWNLOAD**. This routes every URL to gallery-dl, which pulls single images,
multi-image carousels, and the videos inside those posts. Private or
login-walled accounts need cookies — supply a `cookies.txt` or pick your browser
in the cookie dropdown, same as for video.

Even in normal video mode, a link on a photo-first host that yt-dlp can't turn
into a video automatically falls back to gallery-dl, so a stray Instagram photo
link still downloads.

The CLI watcher has the same capability via `python watcher.py --photos`.

---

## File structure

```
yt-zero-touch/
├── app.py            # Tkinter GUI (thin — collects inputs, renders callbacks)
├── orchestrator.py   # UI-free batch runner: resolve, concurrency, retry, history
├── ytdlp_skill.py    # Generic, reusable yt-dlp download engine
├── resolver.py       # Site-specific URL resolution (F1/Brightcove/headless browser)
├── watcher.py        # Alternative CLI front-end: watch urls.txt
├── tests/            # Unit tests for the orchestrator logic
├── requirements.txt  # Python dependencies
├── install.bat       # First-time setup
├── run.bat           # Launch the app
└── urls.txt          # Optional URL list
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `FFmpeg not found` | Install FFmpeg and ensure it is on your PATH |
| `No module named yt_dlp` | Run `install.bat` |
| yt-dlp/gallery-dl fails on a site | Click **Update tools** inside the app |
| `WinError 32` on update | Close the app, run `pip install -U yt-dlp gallery-dl` in a terminal, reopen |
| Login-required video/photo | Supply a `cookies.txt` or pick your browser in the cookie dropdown |
| Photos mode does nothing | Install gallery-dl: `pip install gallery-dl` (or **Update tools**) |
