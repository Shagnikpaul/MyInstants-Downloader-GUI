import os
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QScrollArea, QFrame, QMessageBox, QMenu, QApplication, QInputDialog,
    QStackedWidget, QProgressBar, QCompleter, QMenuBar
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, QStringListModel, QTimer

from .theme import get_icon, apply_dark_theme, apply_light_theme
from .widgets import SoundItemWidget
from .dialogs import BatchDownloadDialog, SettingsDialog, InventoryDialog, FavoritesDialog, AboutDialog, AutoNextPageDialog
from ..constants import APP_TITLE, DEFAULT_REGION, DEFAULT_BASE_URL
from ..settings import load_settings, save_settings
from ..utils import ensure_directory, target_path_for, sanitize_title, friendly_error_message
from ..workers.scrape_worker import ScrapeWorker
from ..workers.download_worker import DownloadWorker
from ..workers.playback_worker import PlaybackWorker, analyze_peak_db

class MainWindow(QMainWindow):
    LOUD_SOUND_THRESHOLD_DB = -1.0

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.download_dir = Path(self.settings["download_dir"]).expanduser().resolve()
        self.settings["download_dir"] = str(self.download_dir)
        ensure_directory(self.download_dir)
        
        self.current_page = 1
        self.current_items = []
        self.current_mode = "page"
        self.active_workers = []
        self.active_playback_workers = []
        self.selected_widget = None
        self.auto_next_page_dialog = None
        self.is_auto_downloading = False
        self.favorite_records = self._normalize_favorites(self.settings.get("favorites", []))
        self.settings["favorites"] = self.favorite_records
        
        self.setup_ui()
        self.setup_menu()
        self.apply_settings()
        self.load_page(1)

    def setup_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)
        self.setWindowIcon(get_icon("main.ico"))
        
        is_dark = self.settings.get("appearance_mode", "Dark") in ["Dark", "System"]
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QVBoxLayout(central_widget)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        # Toolbar
        self.toolbar = QFrame()
        self.toolbar.setFrameShape(QFrame.NoFrame)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        
        self.btn_download_all = QPushButton(" Download All")
        self.btn_download_all.setStyleSheet("padding: 4px 8px;")
        self.btn_download_all.clicked.connect(self.download_all)
        
        self.btn_inventory = QPushButton(" Inventory")
        self.btn_inventory.setStyleSheet("padding: 4px 8px;")
        self.btn_inventory.clicked.connect(self.open_inventory)

        self.btn_favourites = QPushButton(" Favourites")
        self.btn_favourites.setStyleSheet("padding: 4px 8px;")
        self.btn_favourites.clicked.connect(self.open_favourites)
        
        self.toolbar_layout.addWidget(self.btn_download_all)
        self.toolbar_layout.addWidget(self.btn_inventory)
        self.toolbar_layout.addWidget(self.btn_favourites)
        
        self.nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton(" Prev")
        self.btn_prev.setStyleSheet("padding: 4px 8px;")
        self.btn_prev.clicked.connect(self.prev_page)
        self.page_label = QLabel("Page 1")
        self.btn_next = QPushButton(" Next")
        self.btn_next.setStyleSheet("padding: 4px 8px;")
        self.btn_next.clicked.connect(self.next_page)
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addWidget(self.page_label)
        self.nav_layout.addWidget(self.btn_next)
        self.toolbar_layout.addLayout(self.nav_layout)
        
        self.toolbar_layout.addStretch()
        
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search sounds...")
        search_icon = get_icon("search.png", color_invert=is_dark)
        self.search_entry.addAction(search_icon, QLineEdit.LeadingPosition)
        
        self.clear_action = QAction()
        self.clear_action.setIcon(get_icon("x-lg.png", color_invert=is_dark))
        self.clear_action.triggered.connect(self.clear_search)
        self._clear_action_visible = False
        self.search_entry.textChanged.connect(self.update_search_clear_button)
        
        # Autocomplete
        self.search_history = self.settings.get("search_history", [])
        self.completer = QCompleter()
        self.completer_model = QStringListModel(self.search_history)
        self.completer.setModel(self.completer_model)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.search_entry.setCompleter(self.completer)

        self.search_entry.returnPressed.connect(self.search)
        self.btn_search = QPushButton(" Search")
        self.btn_search.setStyleSheet("padding: 4px 8px;")
        self.btn_search.clicked.connect(self.search)
        
        self.toolbar_layout.addWidget(self.search_entry)
        self.toolbar_layout.addWidget(self.btn_search)
        self.update_search_clear_button(self.search_entry.text())
        
        self.layout.addWidget(self.toolbar)
        
        # Main List Area
        self.stacked_widget = QStackedWidget()
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.list_layout.setSpacing(5)
        self.scroll_area.setWidget(self.list_container)
        
        self.stacked_widget.addWidget(self.scroll_area)
        
        # Loading View
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignCenter)
        
        self.loading_label = QLabel("Loading...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size: 16px; color: #888;")
        
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0) # Indeterminate
        self.loading_progress.setFixedWidth(200)
        
        loading_layout.addWidget(self.loading_label)
        loading_layout.addWidget(self.loading_progress)
        
        self.stacked_widget.addWidget(self.loading_widget)
        
        self.layout.addWidget(self.stacked_widget)
        
        # Status bar
        self.statusBar().showMessage("Ready")

    def setup_menu(self):
        menubar = QMenuBar(self)
        menubar.setNativeMenuBar(False)
        self.setMenuBar(menubar)
        is_dark = self.settings.get("appearance_mode", "Dark") in ["Dark", "System"]
        
        file_menu = menubar.addMenu("&File")
        act_download_all = file_menu.addAction("Download All Current")
        act_download_all.setIcon(get_icon("download.png", color_invert=is_dark))
        act_download_all.triggered.connect(self.download_all)
        
        act_inventory = file_menu.addAction("Inventory")
        act_inventory.setIcon(get_icon("box2-fill.png", color_invert=is_dark))
        act_inventory.triggered.connect(self.open_inventory)

        act_favourites = file_menu.addAction("Favourites")
        act_favourites.setIcon(get_icon("heart-fill.png", color_invert=is_dark))
        act_favourites.triggered.connect(self.open_favourites)
        
        act_settings = file_menu.addAction("Settings")
        act_settings.setIcon(get_icon("gear-fill.png", color_invert=is_dark))
        act_settings.triggered.connect(self.open_settings)
        
        file_menu.addSeparator()
        act_exit = file_menu.addAction("Exit")
        act_exit.setIcon(get_icon("x-lg.png", color_invert=is_dark))
        act_exit.triggered.connect(self.close)

        navigate_menu = menubar.addMenu("&Navigate")
        act_trending = navigate_menu.addAction("Back To Trending")
        act_trending.setIcon(get_icon("house-door.png", color_invert=is_dark))
        act_trending.triggered.connect(lambda: self.load_page(1))
        
        navigate_menu.addSeparator()
        act_prev = navigate_menu.addAction("Previous Page")
        act_prev.setIcon(get_icon("arrow-left.png", color_invert=is_dark))
        act_prev.triggered.connect(self.prev_page)
        
        act_next = navigate_menu.addAction("Next Page")
        act_next.setIcon(get_icon("arrow-right.png", color_invert=is_dark))
        act_next.triggered.connect(self.next_page)
        
        navigate_menu.addSeparator()
        act_reload = navigate_menu.addAction("Reload Current View")
        act_reload.setIcon(get_icon("arrow-counterclockwise.png", color_invert=is_dark))
        act_reload.triggered.connect(self.reload_current_view)

        view_menu = menubar.addMenu("&View")
        act_dark = view_menu.addAction("Dark Theme")
        act_dark.setIcon(get_icon("moon.png", color_invert=is_dark))
        act_dark.triggered.connect(lambda: self.set_theme("Dark"))
        act_light = view_menu.addAction("Light Theme")
        act_light.setIcon(get_icon("sun.png", color_invert=is_dark))
        act_light.triggered.connect(lambda: self.set_theme("Light"))
        act_system = view_menu.addAction("System Theme")
        act_system.setIcon(get_icon("circle-half.png", color_invert=is_dark))
        act_system.triggered.connect(lambda: self.set_theme("System"))

        help_menu = menubar.addMenu("&Help")
        act_about = help_menu.addAction("About")
        act_about.setIcon(get_icon("question-circle.png", color_invert=is_dark))
        act_about.triggered.connect(self.open_about)

    def apply_settings(self):
        self.download_dir = Path(self.settings["download_dir"]).expanduser().resolve()
        self.settings["download_dir"] = str(self.download_dir)
        ensure_directory(self.download_dir)
        self.set_theme(self.settings.get("appearance_mode", "Dark"), persist=False)

    def set_theme(self, mode, persist=True):
        self.settings["appearance_mode"] = mode
        if persist:
            save_settings(self.settings)
        
        is_dark = mode == "Dark"
        if mode == "System":
            # Just a simplification, could use a library to detect system theme
            is_dark = True 
            
        if is_dark:
            apply_dark_theme(QApplication.instance())
        else:
            apply_light_theme(QApplication.instance())
            
        self.update_icons(is_dark)
        self.render_items(self.current_items)
        
        # Refresh menu icons
        self.setup_menu()

    def update_icons(self, is_dark):
        self.setWindowIcon(get_icon("main.ico"))
        self.btn_download_all.setIcon(get_icon("download.png", color_invert=is_dark))
        self.btn_inventory.setIcon(get_icon("box2-fill.png", color_invert=is_dark))
        self.btn_favourites.setIcon(get_icon("heart-fill.png", color_invert=is_dark))
        self.btn_prev.setIcon(get_icon("arrow-left.png", color_invert=is_dark))
        self.btn_next.setIcon(get_icon("arrow-right.png", color_invert=is_dark))
        self.btn_search.setIcon(get_icon("search.png", color_invert=is_dark))
        if hasattr(self, "clear_action"):
            self.clear_action.setIcon(get_icon("x-lg.png", color_invert=is_dark))
            self.update_search_clear_button(self.search_entry.text())

    def update_search_clear_button(self, text):
        if not hasattr(self, "clear_action"):
            return
        has_text = bool(text)
        if has_text and not self._clear_action_visible:
            self.search_entry.addAction(self.clear_action, QLineEdit.TrailingPosition)
            self._clear_action_visible = True
        elif not has_text and self._clear_action_visible:
            self.search_entry.removeAction(self.clear_action)
            self._clear_action_visible = False

    def clear_search(self):
        self.search_entry.clear()
        self.load_page(self.current_page)

    def load_page(self, page_number):
        self.current_mode = "page"
        self.loading_label.setText("Loading...")
        self.statusBar().showMessage(f"Loading page {page_number}...")
        self.current_page = page_number
        self.page_label.setText(f"Page {page_number}")
        
        self.stacked_widget.setCurrentWidget(self.loading_widget)
        
        worker = ScrapeWorker('page', str(page_number), 
                              region=self.settings.get("server_region", DEFAULT_REGION),
                              base_url=self.settings.get("server_base_url", DEFAULT_BASE_URL))
        worker.signals.finished.connect(self.on_items_loaded)
        worker.signals.error.connect(self.on_error)
        worker.start()
        self.active_workers.append(worker)

    def search(self):
        query = self.search_entry.text().strip()
        if not query: return
        self.current_mode = "search"
        
        # Update history
        if query in self.search_history:
            self.search_history.remove(query)
        self.search_history.insert(0, query)
        self.search_history = self.search_history[:50] # Limit to 50 items
        self.completer_model.setStringList(self.search_history)
        
        self.settings["search_history"] = self.search_history
        save_settings(self.settings)

        self.loading_label.setText("Loading...")
        self.statusBar().showMessage(f"Searching for '{query}'...")
        self.stacked_widget.setCurrentWidget(self.loading_widget)
        
        worker = ScrapeWorker('search', query,
                              base_url=self.settings.get("server_base_url", DEFAULT_BASE_URL))
        worker.signals.finished.connect(self.on_items_loaded)
        worker.signals.error.connect(self.on_error)
        worker.start()
        self.active_workers.append(worker)

    def on_items_loaded(self, items):
        self.current_items = items
        self.selected_widget = None
        self.loading_label.setText("Loading...")
        self.statusBar().showMessage(f"Loaded {len(items)} sounds.")
        self.render_items(items)
        self.stacked_widget.setCurrentWidget(self.scroll_area)
        
        if getattr(self, "is_auto_downloading", False):
            if self.get_downloadable_items():
                QTimer.singleShot(500, self.download_all)
            elif items:
                self.statusBar().showMessage(
                    f"All sounds on page {self.current_page} are already downloaded. Loading next page..."
                )
                QTimer.singleShot(500, self.next_page)
            else:
                self.is_auto_downloading = False
                self.statusBar().showMessage("Auto-download finished (no more items).")

    def on_error(self, error_msg):
        message = friendly_error_message(error_msg, context="Load failed")
        self.statusBar().showMessage(message)
        self.stacked_widget.setCurrentWidget(self.scroll_area)
        self.is_auto_downloading = False
        QMessageBox.critical(self, "Error", message)

    def render_items(self, items):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        
        hide_downloaded = self.settings.get("hide_downloaded", True)
        shown_count = 0
        
        for i, item in enumerate(items):
            is_downloaded = target_path_for(self.download_dir, item["title"]).exists()
            is_favorited = self.is_favorite_item(item)
            if hide_downloaded and is_downloaded:
                continue
            widget = SoundItemWidget(
                item,
                is_downloaded,
                is_favorited,
                parent_app=self,
                is_even=(shown_count % 2 == 0),
            )
            widget.play_requested.connect(self.play_sound)
            widget.download_requested.connect(self.download_item)
            widget.favorite_requested.connect(self.toggle_favorite)
            self.list_layout.addWidget(widget)
            shown_count += 1

        if shown_count == 0:
            current_mode = getattr(self, "current_mode", "page")
            if (
                current_mode == "page"
                and items
                and hide_downloaded
                and self.settings.get("autoskip_downloaded_pages", True)
            ):
                next_page = self.current_page + 1
                self.statusBar().showMessage(
                    f"All sounds on page {self.current_page} are already downloaded. Loading page {next_page}..."
                )
                QTimer.singleShot(0, lambda page=next_page: self.load_page(page))
                return

            is_dark = self.settings.get("appearance_mode", "Dark") in ["Dark", "System"]
            
            empty_container = QWidget()
            empty_layout = QVBoxLayout(empty_container)
            empty_layout.setAlignment(Qt.AlignCenter)
            empty_layout.setSpacing(20)
            empty_layout.setContentsMargins(0, 100, 0, 0)
            
            info_icon = QLabel()
            info_icon.setPixmap(get_icon("info-circle-fill.png", color_invert=is_dark).pixmap(64, 64))
            info_icon.setAlignment(Qt.AlignCenter)
            
            if current_mode == "page" and items and hide_downloaded:
                empty_text = f"All sounds on page {self.current_page} are already downloaded."
            elif current_mode == "search":
                empty_text = "No items found matching your search."
            elif hide_downloaded and items:
                empty_text = "All sounds in this view are already downloaded."
            else:
                empty_text = "No items found matching your search."

            empty_label = QLabel(empty_text)
            empty_label.setStyleSheet("font-size: 18px; color: #888; font-weight: bold;")
            empty_label.setAlignment(Qt.AlignCenter)
            
            empty_layout.addWidget(info_icon)
            empty_layout.addWidget(empty_label)
            self.list_layout.addWidget(empty_container)

    def select_item(self, widget):
        if self.selected_widget:
            self.selected_widget.is_selected = False
            self.selected_widget.update_style()
        
        self.selected_widget = widget
        if self.selected_widget:
            self.selected_widget.is_selected = True
            self.selected_widget.update_style()
            self.scroll_area.ensureWidgetVisible(self.selected_widget)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            widgets = []
            for i in range(self.list_layout.count()):
                w = self.list_layout.itemAt(i).widget()
                if isinstance(w, SoundItemWidget):
                    widgets.append(w)
            
            if not widgets:
                return super().keyPressEvent(event)
            
            if self.selected_widget is None:
                self.select_item(widgets[0])
            else:
                try:
                    current_idx = widgets.index(self.selected_widget)
                    if event.key() == Qt.Key_Up:
                        new_idx = max(0, current_idx - 1)
                    else:
                        new_idx = min(len(widgets) - 1, current_idx + 1)
                    self.select_item(widgets[new_idx])
                except ValueError:
                    self.select_item(widgets[0])
            return
            
        super().keyPressEvent(event)

    def play_sound(self, item):
        peak_db = analyze_peak_db(item["url"])
        if peak_db is not None and peak_db > self.LOUD_SOUND_THRESHOLD_DB:
            choice = QMessageBox.warning(
                self,
                "Loud Sound",
                (
                    f"Peak audio level detected at {peak_db:.1f} dB.\n\n"
                    "This sound may be very loud. Turn down your volume before continuing?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if choice != QMessageBox.Yes:
                return
        if not self.set_item_playing(item, True):
            return
        self.statusBar().showMessage(f"Playing: {item['title']}")

        worker = PlaybackWorker(item["url"])
        worker.signals.finished.connect(lambda current=item, w=worker: self.on_playback_finished(current, w))
        worker.signals.error.connect(lambda error, current=item, w=worker: self.on_playback_failed(current, error, w))
        worker.start()
        self.active_playback_workers.append(worker)

    def set_item_playing(self, item, playing: bool):
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, SoundItemWidget) and widget.item["url"] == item["url"]:
                widget.set_playing(playing)
                return True
        return False

    def on_playback_finished(self, item, worker):
        if worker in self.active_playback_workers:
            self.active_playback_workers.remove(worker)
        self.set_item_playing(item, False)
        self.statusBar().showMessage(f"Finished playing: {item['title']}")

    def on_playback_failed(self, item, error_msg, worker):
        if worker in self.active_playback_workers:
            self.active_playback_workers.remove(worker)
        self.set_item_playing(item, False)
        self.statusBar().showMessage(friendly_error_message(error_msg, context="Play failed"))

    def download_item(self, item):
        self.statusBar().showMessage(f"Downloading: {item['title']}...")
        worker = DownloadWorker(item, self.download_dir)
        worker.signals.progress.connect(
            lambda data, current=item: self.update_download_progress(current, data)
        )
        worker.signals.finished.connect(
            lambda msg, current=item, w=worker: self.on_download_finished(current, msg, w)
        )
        worker.signals.error.connect(
            lambda err, current=item, w=worker: self.on_download_failed(current, err, w)
        )
        self.set_item_downloading(item, True, 0)
        worker.start()
        self.active_workers.append(worker)

    def set_item_downloading(self, item, downloading: bool, percent: int = 0):
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, SoundItemWidget) and widget.item["url"] == item["url"]:
                widget.set_downloading(downloading, percent)
                return True
        return False

    def set_item_favorited(self, item, favorited: bool):
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, SoundItemWidget) and widget.item["url"] == item["url"]:
                widget.set_favorited(favorited)
                return True
        return False

    def update_download_progress(self, item, data):
        self.set_item_downloading(item, True, int(data.get("percent", 0) * 100))

    def on_download_finished(self, item, msg, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        self.set_item_downloading(item, False, 100)
        self.statusBar().showMessage(msg)
        self.refresh_item_states()

    def on_download_failed(self, item, err, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        self.set_item_downloading(item, False, 0)
        message = friendly_error_message(err, context=f"Download failed: {item['title']}")
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Download Failed", message)

    def download_all(self):
        if not self.current_items:
            self.is_auto_downloading = False
            return

        items_to_download = self.get_downloadable_items()

        if not items_to_download:
            self.is_auto_downloading = False
            if self.current_mode == "page" and self.current_items:
                next_page = self.current_page + 1
                choice = QMessageBox.question(
                    self,
                    "All Downloaded",
                    f"All sounds on page {self.current_page} are already downloaded.\n\n"
                    f"Do you want to find and download the next page with undownloaded sounds starting from page {next_page}?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if choice == QMessageBox.Yes:
                    self.is_auto_downloading = True
                    self.statusBar().showMessage(f"Searching for undownloaded sounds from page {next_page}...")
                    self.next_page()
            return

        dialog = BatchDownloadDialog(self, items_to_download, self.download_dir)
        dialog.exec()
        self.refresh_item_states()

        if self.settings.get("auto_download_next_page", False) and not dialog.is_cancelled:
            self.is_auto_downloading = True
            import random
            delay = random.randint(5000, 10000)
            self.statusBar().showMessage(f"Auto-downloading next page in {delay//1000} seconds...")
            if self.auto_next_page_dialog is not None:
                self.auto_next_page_dialog.close()
                self.auto_next_page_dialog = None

            countdown_triggered = False

            def start_next_page():
                nonlocal countdown_triggered
                countdown_triggered = True
                self.auto_next_page_dialog = None
                self.next_page()

            def clear_auto_next_page_dialog(_result):
                self.auto_next_page_dialog = None
                if countdown_triggered or not getattr(self, "is_auto_downloading", False):
                    return
                self.is_auto_downloading = False
                self.statusBar().showMessage("Auto-download cancelled.")

            self.auto_next_page_dialog = AutoNextPageDialog(self, delay, start_next_page)
            self.auto_next_page_dialog.finished.connect(clear_auto_next_page_dialog)
            self.auto_next_page_dialog.show()
            self.auto_next_page_dialog.raise_()
            self.auto_next_page_dialog.activateWindow()
        else:
            self.is_auto_downloading = False

    def get_downloadable_items(self):
        selected_items = []
        all_shown_items = []
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, SoundItemWidget) and widget.btn_download.isEnabled():
                all_shown_items.append(widget.item)
                if widget.is_selected:
                    selected_items.append(widget.item)
        return selected_items if selected_items else all_shown_items

    def _normalize_favorites(self, favorites):
        normalized = []
        seen = set()
        for entry in favorites or []:
            if isinstance(entry, dict):
                title = str(entry.get("title", "")).strip()
                url = str(entry.get("url", "")).strip()
            else:
                title = str(entry).strip()
                url = ""
            key = url or title
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append({"title": title, "url": url})
        return normalized

    def save_favorites(self):
        self.settings["favorites"] = self.favorite_records
        save_settings(self.settings)

    def remap_favorite_titles(self, title_map):
        changed = False
        for record in self.favorite_records:
            if record.get("url"):
                continue
            old_title = record.get("title", "")
            new_title = title_map.get(old_title)
            if new_title and new_title != old_title:
                record["title"] = new_title
                changed = True
        if changed:
            self.save_favorites()

    def get_favorite_items(self):
        return list(self.favorite_records)

    def is_favorite_item(self, item):
        item_url = item.get("url", "")
        item_title = item.get("title", "")
        return any(
            record.get("url") == item_url
            or (not record.get("url") and record.get("title") == item_title)
            for record in self.favorite_records
        )

    def is_favorite_title(self, title):
        title = str(title).strip()
        return any(record.get("title") == title for record in self.favorite_records)

    def toggle_favorite(self, item):
        if isinstance(item, str):
            title = item.strip()
            url = ""
        else:
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()

        if not title and not url:
            return

        existing_index = None
        for index, record in enumerate(self.favorite_records):
            if url and record.get("url") == url:
                existing_index = index
                break
            if not url and record.get("title") == title:
                existing_index = index
                break

        if existing_index is None:
            self.favorite_records.append({"title": title, "url": url})
            favorited = True
        else:
            self.favorite_records.pop(existing_index)
            favorited = False

        self.save_favorites()
        if not self.set_item_favorited({"url": url, "title": title}, favorited):
            self.refresh_item_states()

    def open_inventory(self):
        dialog = InventoryDialog(self)
        dialog.exec()
        self.refresh_item_states()

    def open_favourites(self):
        dialog = FavoritesDialog(self)
        dialog.exec()
        self.refresh_item_states()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.apply_settings()

    def open_about(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def reload_current_view(self):
        self.load_page(self.current_page)

    def refresh_item_states(self):
        if self.settings.get("hide_downloaded", True):
            self.render_items(self.current_items)
        else:
            for i in range(self.list_layout.count()):
                widget = self.list_layout.itemAt(i).widget()
                if isinstance(widget, SoundItemWidget):
                    is_downloaded = target_path_for(self.download_dir, widget.item["title"]).exists()
                    widget.set_downloaded(is_downloaded)
                    widget.set_favorited(self.is_favorite_item(widget.item))

    def rename_downloaded_item(self, file_path):
        try:
            file_path = Path(file_path).expanduser().resolve()
            if not file_path.exists():
                raise FileNotFoundError(file_path)
            new_name, ok = QInputDialog.getText(self, "Rename", "Enter new name:", QLineEdit.Normal, file_path.stem)
            if ok and new_name:
                new_path = file_path.with_name(f"{sanitize_title(new_name)}.mp3")
                if not new_path.exists():
                    file_path.rename(new_path)
                    self.refresh_item_states()
                else:
                    QMessageBox.warning(self, "Rename", "File already exists.")
        except FileNotFoundError:
            QMessageBox.warning(self, "Rename", "The file could not be found. It may have been moved or deleted.")
            self.refresh_item_states()
        except OSError as exc:
            QMessageBox.warning(self, "Rename", friendly_error_message(exc, context="Rename failed"))

    def delete_downloaded_item(self, file_path):
        try:
            file_path = Path(file_path).expanduser().resolve()
            if not file_path.exists():
                raise FileNotFoundError(file_path)
            if QMessageBox.question(self, "Delete", f"Delete {file_path.name}?") == QMessageBox.Yes:
                file_path.unlink()
                self.refresh_item_states()
        except FileNotFoundError:
            QMessageBox.warning(self, "Delete", "The file could not be found. It may have been moved or deleted.")
            self.refresh_item_states()
        except OSError as exc:
            QMessageBox.warning(self, "Delete", friendly_error_message(exc, context="Delete failed"))

    def next_page(self):
        self.load_page(self.current_page + 1)

    def prev_page(self):
        if self.current_page > 1:
            self.load_page(self.current_page - 1)
