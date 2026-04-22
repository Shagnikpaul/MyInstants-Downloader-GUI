from PySide6.QtCore import QThread, QObject, Signal
from .scraper import getPage, searchq
from ..constants import DEFAULT_REGION, DEFAULT_BASE_URL

class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(dict)

class ScrapeWorker(QThread):
    def __init__(self, mode, data=None, region=DEFAULT_REGION, base_url=DEFAULT_BASE_URL):
        super().__init__()
        self.mode = mode # 'page' or 'search'
        self.data = data # page number or search query
        self.region = region
        self.base_url = base_url
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.mode == 'page':
                items = getPage(self.data, region=self.region, base_url=self.base_url)
            else:
                items = searchq(self.data, base_url=self.base_url)
            self.signals.finished.emit(items)
        except Exception as e:
            self.signals.error.emit(str(e))
