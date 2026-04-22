import requests
from time import perf_counter
from PySide6.QtCore import QThread
from .scrape_worker import WorkerSignals
from ..constants import DOWNLOAD_CHUNK_SIZE
from ..utils import target_path_for

class DownloadWorker(QThread):
    def __init__(self, item, download_dir):
        super().__init__()
        self.item = item
        self.download_dir = download_dir
        self.signals = WorkerSignals()
        self.is_cancelled = False

    def run(self):
        try:
            target_path = target_path_for(self.download_dir, self.item["title"])
            if target_path.exists():
                self.signals.finished.emit(f"Skipped existing: {target_path.name}")
                return

            downloaded = 0
            started = perf_counter()
            with requests.get(self.item["url"], stream=True, timeout=30) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", "0") or 0)
                
                with open(target_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if self.is_cancelled:
                            f.close()
                            target_path.unlink(missing_ok=True)
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            elapsed = max(perf_counter() - started, 0.001)
                            speed = downloaded / elapsed
                            self.signals.progress.emit({
                                "downloaded": downloaded,
                                "total": total_size,
                                "speed": speed,
                                "percent": (downloaded / total_size) if total_size else 0
                            })
            self.signals.finished.emit(f"Downloaded: {target_path.name}")
        except Exception as e:
            self.signals.error.emit(str(e))
