"""
UI Theme & Visual Styles for YT-DLP Zero-Touch (Modernized).
============================================================
Windows 11 Fluent dark palette, status badges, and typography tokens.
"""

COLORS = {
    "bg":            "#0f111a",  # Deep dark backdrop
    "card":          "#161824",  # Elevated cards & panels
    "card_alt":      "#181b2e",  # Subtle contrast panels
    "border":        "#26293d",  # Card & divider borders
    "border_focus":  "#e94560",  # Focus borders
    "input_bg":      "#0e101a",  # Textarea & entry fields
    "accent":        "#e94560",  # Vibrant zero-touch rose/red
    "accent_hover":  "#ff5975",  # Button hover
    "accent_subtle": "#0f3460",  # Header & tag subtle blue
    "text":          "#eaeaea",  # Primary readable text
    "text_bright":   "#ffffff",  # Bold headings
    "muted":         "#8a91a8",  # Secondary muted labels
    "success":       "#27c93f",  # Done / Verified green
    "info":          "#3b82f6",  # Downloading blue
    "warning":       "#ffbd2e",  # Merging / Retrying amber
    "error":         "#ff5f56",  # Failed red
    "purple":        "#a855f7",  # Photos / gallery-dl purple
    "amber":         "#d97706",  # ProRes MOV amber
    "amber_border":  "#f59e0b",
    "cyan":          "#0284c7",  # Subtitles cyan
    "cyan_border":   "#38bdf8",
    "pill_off":      "#121522",  # Interactive pill off state
}

STATUS_STYLE = {
    "resolving":   ("Resolving…",       COLORS["muted"]),
    "queued":      ("Queued",           COLORS["muted"]),
    "skipped":     ("Skipped",          COLORS["muted"]),
    "downloading": ("Downloading",      COLORS["info"]),
    "merging":     ("Merging / Gate",   COLORS["warning"]),
    "retrying":    ("Retrying…",        COLORS["warning"]),
    "done":        ("Done",             COLORS["success"]),
    "failed":      ("Failed",           COLORS["error"]),
}
