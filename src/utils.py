import re
import sys
from pathlib import Path
from typing import Optional

def ensure_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def resource_path(name: str) -> Path:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_dir / "resources" / name

def sanitize_title(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", title).strip()
    return cleaned or "sound"

def target_path_for(download_dir: Path, title: str) -> Path:
    return download_dir / f"{sanitize_title(title)}.mp3"

def format_bytes(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes:.1f} B"

def format_speed(num_bytes: float) -> str:
    return f"{format_bytes(num_bytes)}/s"

def friendly_error_message(error: object, *, context: Optional[str] = None) -> str:
    message = str(error).strip() or "Unknown error"
    lower = message.lower()

    if isinstance(error, FileNotFoundError) or "no such file" in lower or "file not found" in lower:
        return f"{context + ': ' if context else ''}The file could not be found. It may have been moved or deleted."

    if isinstance(error, PermissionError) or "permission denied" in lower or "access is denied" in lower:
        return f"{context + ': ' if context else ''}Permission was denied."

    if "timed out" in lower or "timeout" in lower:
        return f"{context + ': ' if context else ''}The operation timed out."

    return f"{context + ': ' if context else ''}{message}"
