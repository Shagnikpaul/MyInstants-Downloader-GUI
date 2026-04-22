from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from PySide6.QtCore import QThread, QObject, Signal


class PlaybackSignals(QObject):
    finished = Signal()
    error = Signal(str)


class PlaybackWorker(QThread):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.signals = PlaybackSignals()

    def run(self):
        try:
            from playsound import playsound

            playsound(self.url)
            self.signals.finished.emit()
        except Exception as exc:
            self.signals.error.emit(str(exc))


def analyze_peak_db(source: str) -> Optional[float]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                source,
                "-af",
                "volumedetect",
                "-f",
                "null",
                os.devnull,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    output = (result.stderr or "") + "\n" + (result.stdout or "")
    match = re.search(r"max_volume:\s*([+-]?(?:\d+(?:\.\d+)?|inf))\s*dB", output)
    if not match:
        return None

    value = match.group(1).strip().lower()
    if value == "inf" or value == "+inf":
        return None
    if value == "-inf":
        return float("-inf")
    try:
        return float(value)
    except ValueError:
        return None
