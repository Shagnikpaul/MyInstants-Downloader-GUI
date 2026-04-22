from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QTextEdit, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFileDialog, QScrollArea, QWidget, QSpinBox,
    QMessageBox, QFormLayout,
    QStackedWidget
)
from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal
from uuid import uuid4
from time import perf_counter
from .theme import get_icon
from .widgets import InventoryItemWidget, SoundItemWidget
from ..workers.download_worker import DownloadWorker
from ..workers.playback_worker import PlaybackWorker
from ..utils import format_speed, target_path_for, ensure_directory, sanitize_title, friendly_error_message
from ..settings import save_settings
from ..constants import DEFAULT_REGION, DEFAULT_BASE_URL

class BatchDownloadDialog(QDialog):
    def __init__(self, parent, items, download_dir):
        super().__init__(parent)
        self.parent_app = parent
        self.items = items
        self.download_dir = download_dir
        self.is_cancelled = False
        self.active_workers = []
        
        # Concurrency setting
        self.max_concurrent = self._get_max_concurrent()
        self.use_concurrent = self.max_concurrent > 1
        
        self.worker_progress_map = {} # worker -> progress_bar
        
        self.total_items = len(self.items)
        self.completed_items = 0
        self.batch_start_time = perf_counter()
        
        self.setWindowTitle("Batch Download")
        self.resize(600, 500 if self.use_concurrent else 400)
        self.setup_ui()
        
        QTimer.singleShot(100, self.start_next)

    def _get_max_concurrent(self):
        raw_value = self.parent_app.settings.get("concurrent_downloads", 5)
        if isinstance(raw_value, bool):
            raw_value = 5 if raw_value else 1
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 5
        return max(1, min(5, value))

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.label_overall = QLabel(f"Preparing to download {self.total_items} files...")
        layout.addWidget(self.label_overall)
        
        self.progress_overall = QProgressBar()
        self.progress_overall.setMaximum(self.total_items)
        layout.addWidget(self.progress_overall)
        
        self.label_status = QLabel("Active downloads: 0")
        layout.addWidget(self.label_status)

        # Individual progress bars
        self.sub_progress_container = QWidget()
        self.sub_progress_layout = QVBoxLayout(self.sub_progress_container)
        self.sub_progress_layout.setContentsMargins(0, 0, 0, 0)
        self.sub_progress_layout.setSpacing(2)
        
        self.sub_bars = []
        num_bars = self.max_concurrent
        for i in range(num_bars):
            bar_widget = QWidget()
            bar_layout = QVBoxLayout(bar_widget)
            bar_layout.setContentsMargins(0, 2, 0, 2)
            bar_layout.setSpacing(0)
            
            label = QLabel("Idle")
            label.setStyleSheet("font-size: 11px; color: #888;")
            bar = QProgressBar()
            bar.setFixedHeight(12 if self.use_concurrent else 18)
            bar.setTextVisible(False)
            
            bar_layout.addWidget(label)
            bar_layout.addWidget(bar)
            
            self.sub_progress_layout.addWidget(bar_widget)
            self.sub_bars.append({"widget": bar_widget, "label": label, "bar": bar, "in_use": False})
            
        layout.addWidget(self.sub_progress_container)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(150)
        layout.addWidget(self.log_view)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel)
        layout.addWidget(self.btn_cancel)

    def start_next(self):
        if self.is_cancelled:
            return

        while len(self.active_workers) < self.max_concurrent and self.items:
            # Find an available bar
            available_bar = None
            for b in self.sub_bars:
                if not b["in_use"]:
                    available_bar = b
                    break
            
            if not available_bar:
                break
                
            item = self.items.pop(0)
            self.log_view.append(f"Starting: {item['title']}")
            
            available_bar["in_use"] = True
            available_bar["label"].setText(f"Downloading: {item['title']}")
            available_bar["bar"].setValue(0)
            
            worker = DownloadWorker(item, self.download_dir)
            self.active_workers.append(worker)
            self.worker_progress_map[worker] = available_bar
            
            worker.signals.progress.connect(lambda data, w=worker: self.update_sub_progress(data, w))
            worker.signals.finished.connect(lambda msg, w=worker: self.on_finished(msg, w))
            worker.signals.error.connect(lambda err, w=worker: self.on_error(err, w))
            worker.start()

        self.update_status_label()

        if not self.items and not self.active_workers:
            self.label_overall.setText(f"Batch download complete ({self.completed_items}/{self.total_items}).")
            self.btn_cancel.setText("Close")
            if self.parent_app.settings.get("auto_download_next_page", False) and not self.is_cancelled:
                self.accept()

    def update_sub_progress(self, data, worker):
        if worker in self.worker_progress_map:
            bar_info = self.worker_progress_map[worker]
            bar_info["bar"].setValue(int(data['percent'] * 100))
            bar_info["label"].setText(f"Downloading: {worker.item['title']} ({format_speed(data['speed'])})")

    def update_status_label(self):
        self.label_status.setText(f"Active downloads: {len(self.active_workers)} | Remaining in queue: {len(self.items)}")

    def update_overall_label(self):
        elapsed = max(perf_counter() - self.batch_start_time, 0.001)
        speed = self.completed_items / elapsed
        self.label_overall.setText(f"Downloaded {self.completed_items} of {self.total_items} files ({speed:.1f} items/sec)")

    def on_finished(self, msg, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        
        if worker in self.worker_progress_map:
            bar_info = self.worker_progress_map.pop(worker)
            bar_info["in_use"] = False
            bar_info["label"].setText("Idle")
            bar_info["bar"].setValue(0)
            
        self.log_view.append(msg)
        self.completed_items += 1
        self.progress_overall.setValue(self.completed_items)
        self.update_overall_label()
        self.start_next()

    def on_error(self, err, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
            
        if worker in self.worker_progress_map:
            bar_info = self.worker_progress_map.pop(worker)
            bar_info["in_use"] = False
            bar_info["label"].setText("Idle")
            bar_info["bar"].setValue(0)
            
        self.log_view.append(f"Error: {err}")
        self.completed_items += 1
        self.progress_overall.setValue(self.completed_items)
        self.update_overall_label()
        self.start_next()

    def cancel(self):
        self.is_cancelled = True
        for worker in self.active_workers:
            worker.is_cancelled = True
        self.accept()

class AutoNextPageDialog(QDialog):
    def __init__(self, parent, delay_ms, on_timeout):
        super().__init__(parent)
        self.setWindowTitle("Auto-Download Next Page")
        self.setModal(False)
        self.delay_ms = max(0, int(delay_ms))
        self.remaining_ms = self.delay_ms
        self.on_timeout = on_timeout
        self.has_triggered = False

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

        self._setup_ui()
        self._update_label()
        self.timer.start()

    def _setup_ui(self):
        self.resize(520, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(self.label)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(self.btn_cancel, alignment=Qt.AlignCenter)

    def _seconds_remaining(self):
        return max(0, (self.remaining_ms + 999) // 1000)

    def _update_label(self):
        seconds = self._seconds_remaining()
        self.label.setText(f"Downloading next page in {seconds} seconds...")

    def _tick(self):
        self.remaining_ms = max(0, self.remaining_ms - self.timer.interval())
        self._update_label()
        if self.remaining_ms <= 0:
            self._trigger_timeout()

    def _trigger_timeout(self):
        if self.has_triggered:
            return
        self.has_triggered = True
        self.timer.stop()
        self.hide()
        if self.on_timeout:
            self.on_timeout()
        self.accept()

    def reject(self):
        self.timer.stop()
        super().reject()

class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Settings")
        self.resize(500, 400)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Download Directory
        layout.addWidget(QLabel("Download Directory:"))
        h_layout = QHBoxLayout()
        self.edit_dir = QLineEdit(self.parent_app.settings["download_dir"])
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_dir)
        h_layout.addWidget(self.edit_dir)
        h_layout.addWidget(btn_browse)
        layout.addLayout(h_layout)
        
        # Theme
        layout.addWidget(QLabel("Appearance Mode:"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItem(get_icon("moon.png", color_invert=False), "Dark")
        self.combo_theme.addItem(get_icon("sun.png", color_invert=False), "Light")
        self.combo_theme.addItem(get_icon("circle-half.png", color_invert=False), "System")
        self.combo_theme.setCurrentText(self.parent_app.settings.get("appearance_mode", "Dark"))
        layout.addWidget(self.combo_theme)
        
        # Region
        layout.addWidget(QLabel("Server Region:"))
        self.edit_region = QLineEdit(self.parent_app.settings.get("server_region", DEFAULT_REGION))
        layout.addWidget(self.edit_region)
        
        # Base URL
        layout.addWidget(QLabel("Server Base URL:"))
        self.edit_url = QLineEdit(self.parent_app.settings.get("server_base_url", DEFAULT_BASE_URL))
        layout.addWidget(self.edit_url)
        
        # Hide Downloaded
        self.check_hide = QCheckBox("Hide Downloaded Sounds")
        self.check_hide.setChecked(self.parent_app.settings.get("hide_downloaded", True))
        layout.addWidget(self.check_hide)

        # Auto-skip downloaded pages
        self.check_autoskip_pages = QCheckBox("Autoskip Already Downloaded Pages")
        self.check_autoskip_pages.setChecked(
            self.parent_app.settings.get("autoskip_downloaded_pages", True)
        )
        layout.addWidget(self.check_autoskip_pages)

        # Auto Download Next Page
        self.check_auto_download = QCheckBox("Auto-Download Next Page (after Batch Download)")
        self.check_auto_download.setChecked(self.parent_app.settings.get("auto_download_next_page", False))
        layout.addWidget(self.check_auto_download)

        # Concurrent Downloads
        current_concurrent = self.parent_app.settings.get("concurrent_downloads", 5)
        if isinstance(current_concurrent, bool):
            current_concurrent = 5 if current_concurrent else 0
        try:
            current_concurrent = int(current_concurrent)
        except (TypeError, ValueError):
            current_concurrent = 5
        current_concurrent = max(0, min(5, current_concurrent))

        self.check_concurrent = QCheckBox("Enable Concurrent Downloads")
        self.check_concurrent.setChecked(current_concurrent > 0)
        layout.addWidget(self.check_concurrent)

        concurrent_row = QHBoxLayout()
        self.label_concurrent = QLabel("Workers:")
        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(0, 5)
        self.spin_concurrent.setValue(current_concurrent or 5)
        self.spin_concurrent.setEnabled(self.check_concurrent.isChecked())
        concurrent_row.addWidget(self.label_concurrent)
        concurrent_row.addWidget(self.spin_concurrent)
        concurrent_row.addStretch()
        layout.addLayout(concurrent_row)
        self.check_concurrent.toggled.connect(self._toggle_concurrent_controls)
        self._toggle_concurrent_controls(self.check_concurrent.isChecked())
        
        layout.addStretch()
        
        btns = QHBoxLayout()
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.edit_dir.text())
        if path:
            self.edit_dir.setText(path)

    def _toggle_concurrent_controls(self, enabled):
        self.label_concurrent.setVisible(enabled)
        self.spin_concurrent.setVisible(enabled)
        self.spin_concurrent.setEnabled(enabled)

    def save(self):
        self.parent_app.settings["download_dir"] = str(Path(self.edit_dir.text()).expanduser().resolve())
        self.parent_app.settings["appearance_mode"] = self.combo_theme.currentText()
        self.parent_app.settings["server_region"] = self.edit_region.text()
        self.parent_app.settings["server_base_url"] = self.edit_url.text()
        self.parent_app.settings["hide_downloaded"] = self.check_hide.isChecked()
        self.parent_app.settings["autoskip_downloaded_pages"] = self.check_autoskip_pages.isChecked()
        self.parent_app.settings["auto_download_next_page"] = self.check_auto_download.isChecked()
        self.parent_app.settings["concurrent_downloads"] = (
            self.spin_concurrent.value() if self.check_concurrent.isChecked() else 0
        )
        
        save_settings(self.parent_app.settings)
        self.parent_app.apply_settings()
        self.accept()

class InventoryLoadWorker(QObject):
    finished = Signal(int, list)
    error = Signal(int, str)

    def __init__(self, token, download_dir):
        super().__init__()
        self.token = token
        self.download_dir = download_dir

    def run(self):
        try:
            files = sorted(self.download_dir.glob("*.mp3"), key=lambda path: path.name.lower())
            self.finished.emit(self.token, [str(path) for path in files])
        except Exception as exc:
            self.error.emit(self.token, str(exc))

class MultiRenameDialog(QDialog):
    def __init__(self, parent, widgets):
        super().__init__(parent)
        self.widgets = list(widgets)
        self.setWindowTitle("Multi Rename")
        self.resize(720, 520)
        self._plan = []
        self.setup_ui()
        self.refresh_preview()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()

        self.edit_pattern = QLineEdit("{n:02d} - {name}")
        self.edit_pattern.setPlaceholderText("{n:02d} - {name}")
        self.edit_prefix = QLineEdit()
        self.edit_suffix = QLineEdit()
        self.edit_find = QLineEdit()
        self.edit_replace = QLineEdit()
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, 999999)
        self.spin_start.setValue(1)
        self.spin_step = QSpinBox()
        self.spin_step.setRange(1, 999999)
        self.spin_step.setValue(1)
        self.combo_case = QComboBox()
        self.combo_case.addItems(["None", "UPPERCASE", "lowercase", "Title Case"])

        form.addRow("Pattern", self.edit_pattern)
        form.addRow("Prefix", self.edit_prefix)
        form.addRow("Suffix", self.edit_suffix)
        form.addRow("Find", self.edit_find)
        form.addRow("Replace", self.edit_replace)
        form.addRow("Start Number", self.spin_start)
        form.addRow("Step", self.spin_step)
        form.addRow("Case", self.combo_case)
        layout.addLayout(form)

        help_label = QLabel("Tokens: {name}, {original}, {n}, {i}")
        help_label.setStyleSheet("color: #888;")
        layout.addWidget(help_label)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #cc5555; font-weight: bold;")
        layout.addWidget(self.error_label)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(220)
        layout.addWidget(self.preview)

        self.btn_preview = QPushButton("Preview")
        self.btn_preview.setFocusPolicy(Qt.NoFocus)
        self.btn_preview.setAutoDefault(False)
        self.btn_preview.setDefault(False)
        self.btn_preview.clicked.connect(self.refresh_preview)

        self.btn_rename = QPushButton("Rename")
        self.btn_rename.setFocusPolicy(Qt.NoFocus)
        self.btn_rename.setAutoDefault(False)
        self.btn_rename.setDefault(False)
        self.btn_rename.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFocusPolicy(Qt.NoFocus)
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setDefault(False)
        self.btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_preview)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_rename)
        layout.addLayout(btn_row)

        for widget in (
            self.edit_pattern,
            self.edit_prefix,
            self.edit_suffix,
            self.edit_find,
            self.edit_replace,
        ):
            widget.textChanged.connect(self.refresh_preview)
        self.spin_start.valueChanged.connect(self.refresh_preview)
        self.spin_step.valueChanged.connect(self.refresh_preview)
        self.combo_case.currentIndexChanged.connect(self.refresh_preview)

    def _build_new_stem(self, widget, index):
        source_stem = widget.file_path.stem
        name = source_stem
        find_text = self.edit_find.text()
        if find_text:
            name = name.replace(find_text, self.edit_replace.text())

        values = {
            "name": name,
            "original": source_stem,
            "n": self.spin_start.value() + (index * self.spin_step.value()),
            "i": index + 1,
        }

        try:
            result = self.edit_pattern.text().format(**values).strip()
        except Exception as exc:
            raise ValueError(f"Pattern error: {exc}") from exc

        prefix = self.edit_prefix.text()
        suffix = self.edit_suffix.text()
        result = f"{prefix}{result}{suffix}".strip()

        case_mode = self.combo_case.currentText()
        if case_mode == "UPPERCASE":
            result = result.upper()
        elif case_mode == "lowercase":
            result = result.lower()
        elif case_mode == "Title Case":
            result = result.title()

        result = sanitize_title(result)
        if not result:
            raise ValueError("Generated name is empty.")
        return result

    def build_plan(self):
        planned = []
        seen = set()
        existing_paths = {widget.file_path for widget in self.widgets}
        target_dir = self.widgets[0].file_path.parent if self.widgets else None
        for index, widget in enumerate(self.widgets):
            new_stem = self._build_new_stem(widget, index)
            new_path = widget.file_path.with_name(f"{new_stem}.mp3")
            if new_path == widget.file_path:
                continue
            key = new_path.name.lower()
            if key in seen:
                raise ValueError(f"Duplicate target name: {new_path.name}")
            seen.add(key)
            if new_path.exists() and new_path not in existing_paths:
                raise ValueError(f"Target already exists: {new_path.name}")
            if target_dir and new_path.parent != target_dir:
                raise ValueError("Invalid target directory.")
            planned.append((widget.file_path, new_path))
        if not planned:
            raise ValueError("Nothing to rename.")
        return planned

    def refresh_preview(self):
        try:
            plan = self.build_plan()
        except Exception as exc:
            self._plan = []
            self.error_label.setText(str(exc))
            self.preview.setPlainText("")
            self.btn_rename.setEnabled(False)
            return

        self._plan = plan
        self.error_label.setText("")
        self.btn_rename.setEnabled(True)
        lines = [f"{old.name} -> {new.name}" for old, new in plan]
        self.preview.setPlainText("\n".join(lines))

    def get_plan(self):
        return list(self._plan)

    def accept(self):
        self.refresh_preview()
        if not self._plan:
            return
        super().accept()

class InventoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Inventory")
        self.resize(800, 600)
        self.selected_widget = None
        self._suppress_selection_updates = False
        self._inventory_load_token = 0
        self._inventory_load_thread = None
        self._inventory_load_worker = None
        self._pending_inventory_files = []
        self._inventory_render_index = 0
        self._inventory_render_chunk = 1000
        self._inventory_render_timer = QTimer(self)
        self._inventory_render_timer.setInterval(0)
        self._inventory_render_timer.timeout.connect(self._render_inventory_chunk)
        self.active_playback_workers = []
        self.setup_ui()
        QTimer.singleShot(0, self.load_inventory)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Directory Controls
        from .theme import get_icon
        is_dark = self.parent_app.settings.get("appearance_mode", "Dark") in ["Dark", "System"]
        
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Save To:"))
        self.edit_dir = QLineEdit(str(self.parent_app.download_dir))
        self.edit_dir.setReadOnly(True)
        dir_layout.addWidget(self.edit_dir)
        
        btn_browse = QPushButton(" Browse")
        btn_browse.setIcon(get_icon("folder2-open.png", color_invert=is_dark))
        btn_browse.setStyleSheet("padding: 4px 8px;")
        btn_browse.setFocusPolicy(Qt.NoFocus)
        btn_browse.setAutoDefault(False)
        btn_browse.setDefault(False)
        btn_browse.clicked.connect(self.browse_dir)
        dir_layout.addWidget(btn_browse)
        
        btn_open = QPushButton(" Open Downloads")
        btn_open.setIcon(get_icon("folder2-open.png", color_invert=is_dark))
        btn_open.setStyleSheet("padding: 4px 8px;")
        btn_open.setFocusPolicy(Qt.NoFocus)
        btn_open.setAutoDefault(False)
        btn_open.setDefault(False)
        import os
        btn_open.clicked.connect(lambda: os.startfile(str(self.parent_app.download_dir)))
        dir_layout.addWidget(btn_open)
        
        layout.addLayout(dir_layout)

        self.select_toolbar = QWidget()
        select_layout = QHBoxLayout(self.select_toolbar)
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setSpacing(8)

        self.btn_select_all = QPushButton(" Select All")
        self.btn_select_all.setIcon(get_icon("check2-all.png", color_invert=is_dark))
        self.btn_select_all.setFocusPolicy(Qt.NoFocus)
        self.btn_select_all.setAutoDefault(False)
        self.btn_select_all.setDefault(False)
        self.btn_select_all.clicked.connect(self.select_all_items)

        self.btn_bulk_rename = QPushButton(" Rename")
        self.btn_bulk_rename.setIcon(get_icon("cursor-text.png", color_invert=is_dark))
        self.btn_bulk_rename.setFocusPolicy(Qt.NoFocus)
        self.btn_bulk_rename.setAutoDefault(False)
        self.btn_bulk_rename.setDefault(False)
        self.btn_bulk_rename.clicked.connect(self.rename_selected_items)

        self.btn_bulk_delete = QPushButton(" Delete")
        self.btn_bulk_delete.setIcon(get_icon("trash3.png", color_invert=is_dark))
        self.btn_bulk_delete.setFocusPolicy(Qt.NoFocus)
        self.btn_bulk_delete.setAutoDefault(False)
        self.btn_bulk_delete.setDefault(False)
        self.btn_bulk_delete.clicked.connect(self.delete_selected_items)

        select_layout.addWidget(self.btn_select_all)
        select_layout.addWidget(self.btn_bulk_rename)
        select_layout.addWidget(self.btn_bulk_delete)
        select_layout.addStretch()
        layout.addWidget(self.select_toolbar)
        self.select_toolbar.setVisible(False)
        
        self.stacked = QStackedWidget()

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignCenter)

        self.loading_label = QLabel("Loading inventory...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size: 16px; color: #888;")

        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setFixedWidth(200)

        loading_layout.addWidget(self.loading_label)
        loading_layout.addWidget(self.loading_progress)

        self.stacked.addWidget(self.loading_widget)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        self.stacked.addWidget(self.scroll)

        layout.addWidget(self.stacked)
        self.stacked.setCurrentWidget(self.loading_widget)
        self.update_selection_actions()

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.edit_dir.text())
        if path:
            self.edit_dir.setText(path)
            self.parent_app.settings["download_dir"] = path
            save_settings(self.parent_app.settings)
            self.parent_app.apply_settings()
            self.load_inventory()

    def load_inventory(self):
        self._inventory_load_token += 1
        self._pending_inventory_files = []
        self._inventory_render_index = 0
        self._inventory_render_timer.stop()
        self.select_toolbar.setVisible(False)
        self.stacked.setCurrentWidget(self.loading_widget)
        self.loading_label.setText("Loading inventory...")
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setVisible(True)
        self._start_inventory_load_worker(self._inventory_load_token)

    def _start_inventory_load_worker(self, token):
        thread = QThread(self)
        worker = InventoryLoadWorker(token, self.parent_app.download_dir)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_inventory_files_ready)
        worker.error.connect(self._on_inventory_load_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        self._inventory_load_thread = thread
        self._inventory_load_worker = worker
        thread.start()

    def _on_inventory_load_error(self, token, error):
        if token != self._inventory_load_token:
            return
        self.loading_label.setText(f"Failed to load inventory: {error}")
        self.loading_progress.setRange(0, 1)
        self.loading_progress.setValue(1)
        self.stacked.setCurrentWidget(self.loading_widget)

    def _on_inventory_files_ready(self, token, files):
        if token != self._inventory_load_token:
            return
        self._pending_inventory_files = [
            path if isinstance(path, Path) and path.is_absolute() else self.parent_app.download_dir / Path(path)
            for path in files
        ]
        self.selected_widget = None
        self._suppress_selection_updates = True
        self.stacked.setUpdatesEnabled(False)
        self.container.setUpdatesEnabled(False)
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._inventory_render_index = 0
        QTimer.singleShot(0, self._render_inventory_chunk)

    def _render_inventory_chunk(self):
        total = len(self._pending_inventory_files)
        if total == 0:
            self._inventory_render_timer.stop()
            self.stacked.setUpdatesEnabled(True)
            self.container.setUpdatesEnabled(True)
            self._suppress_selection_updates = False
            self._show_empty_inventory_state()
            self.update_selection_actions()
            self.stacked.setCurrentWidget(self.scroll)
            return

        start = self._inventory_render_index
        end = min(start + self._inventory_render_chunk, total)

        for i in range(start, end):
            f = self._pending_inventory_files[i]
            widget = InventoryItemWidget(f, self, is_even=(i % 2 == 0))
            widget.favorite_requested.connect(self.toggle_favorite)
            self.list_layout.addWidget(widget)

        self._inventory_render_index = end

        if self._inventory_render_index >= total:
            self._inventory_render_timer.stop()
            self.stacked.setUpdatesEnabled(True)
            self.container.setUpdatesEnabled(True)
            self._suppress_selection_updates = False
            self.select_toolbar.setVisible(total > 0)
            self.update_selection_actions()
            self.stacked.setCurrentWidget(self.scroll)
        else:
            QTimer.singleShot(0, self._render_inventory_chunk)

    def _show_empty_inventory_state(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        from .theme import get_icon
        is_dark = self.parent_app.settings.get("appearance_mode", "Dark") in ["Dark", "System"]

        empty_icon = QLabel()
        empty_icon.setPixmap(get_icon("box2-fill.png", color_invert=is_dark).pixmap(64, 64))
        empty_icon.setAlignment(Qt.AlignCenter)

        empty_label = QLabel("No items in inventory")
        empty_label.setStyleSheet("font-size: 16px; color: #888;")
        empty_label.setAlignment(Qt.AlignCenter)

        self.list_layout.addStretch()
        self.list_layout.addWidget(empty_icon)
        self.list_layout.addWidget(empty_label)
        self.list_layout.addStretch()
        self.select_toolbar.setVisible(False)

    def refresh(self):
        self.load_inventory()

    def play_file(self, file_path):
        if hasattr(file_path, "file_path"):
            widget = file_path
            file_path = widget.file_path
        else:
            widget = None

        if widget and getattr(widget, "playback_worker", None):
            self.stop_playback(widget)
            return

        try:
            resolved = Path(file_path).expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(resolved)
        except FileNotFoundError:
            self.parent_app.statusBar().showMessage("Play skipped: file not found. Inventory will refresh.")
            self.refresh()
            return
        except OSError as exc:
            self.parent_app.statusBar().showMessage(friendly_error_message(exc, context="Play failed"))
            return

        worker = PlaybackWorker(str(resolved))
        worker.signals.finished.connect(lambda w=worker, row=widget: self.on_playback_finished(w, row))
        worker.signals.error.connect(lambda err, w=worker, row=widget: self.on_playback_failed(err, w, row))
        worker.start()
        self.active_playback_workers.append(worker)
        if widget:
            widget.playback_worker = worker
            widget.set_playing(True)

    def stop_playback(self, widget):
        worker = getattr(widget, "playback_worker", None)
        if worker and worker in self.active_playback_workers:
            worker.terminate()
            worker.wait(1000)
            self.active_playback_workers.remove(worker)
        widget.playback_worker = None
        widget.set_playing(False)

    def on_playback_finished(self, worker, widget=None):
        if worker in self.active_playback_workers:
            self.active_playback_workers.remove(worker)
        if widget and getattr(widget, "playback_worker", None) is worker:
            widget.playback_worker = None
            widget.set_playing(False)

    def on_playback_failed(self, error_msg, worker, widget=None):
        if worker in self.active_playback_workers:
            self.active_playback_workers.remove(worker)
        if widget and getattr(widget, "playback_worker", None) is worker:
            widget.playback_worker = None
            widget.set_playing(False)
        self.parent_app.statusBar().showMessage(friendly_error_message(error_msg, context="Play failed"))

    def _inventory_widgets(self):
        widgets = []
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, InventoryItemWidget):
                widgets.append(widget)
        return widgets

    def update_selection_actions(self):
        if self._suppress_selection_updates:
            return
        selected_count = len(self.get_selected_inventory_widgets())
        self.btn_bulk_rename.setEnabled(selected_count >= 1)
        self.btn_bulk_delete.setEnabled(selected_count >= 1)

    def select_all_items(self):
        widgets = self._inventory_widgets()
        if not widgets:
            return
        all_checked = all(widget.is_checked() for widget in widgets)
        self._suppress_selection_updates = True
        try:
            for widget in widgets:
                widget.set_checked(not all_checked)
        finally:
            self._suppress_selection_updates = False
        self.update_selection_actions()

    def get_selected_inventory_widgets(self):
        return [widget for widget in self._inventory_widgets() if widget.is_checked()]

    def rename_selected_items(self):
        selected = self.get_selected_inventory_widgets()
        if not selected:
            return
        dialog = MultiRenameDialog(self, selected)
        if dialog.exec() != QDialog.Accepted:
            return
        plan = dialog.get_plan()
        if not plan:
            return
        try:
            self.apply_bulk_rename(plan)
        except FileNotFoundError:
            QMessageBox.warning(self, "Rename", "One or more files were missing. The inventory will be refreshed.")
            self.load_inventory()
        except OSError as exc:
            QMessageBox.warning(self, "Rename", friendly_error_message(exc, context="Rename failed"))

    def apply_bulk_rename(self, plan):
        temp_map = []
        try:
            for index, (source, target) in enumerate(plan):
                if not source.exists():
                    raise FileNotFoundError(source)
                temp_path = source.with_name(f".__rename_tmp__{uuid4().hex}_{index}.mp3")
                source.rename(temp_path)
                temp_map.append((temp_path, source, target))

            for temp_path, _source, target in temp_map:
                if not temp_path.exists():
                    raise FileNotFoundError(temp_path)
                temp_path.rename(target)
        except FileNotFoundError as exc:
            raise FileNotFoundError("One or more files were missing during rename.") from exc
        except Exception:
            for temp_path, original_path, _target in reversed(temp_map):
                try:
                    if temp_path.exists() and not original_path.exists():
                        temp_path.rename(original_path)
                except Exception:
                    pass
            raise

        if hasattr(self.parent_app, "remap_favorite_titles"):
            self.parent_app.remap_favorite_titles(
                {source.stem: target.stem for source, target in plan}
            )
        self.load_inventory()

    def delete_selected_items(self):
        selected = self.get_selected_inventory_widgets()
        if not selected:
            return
        preview = ", ".join(widget.file_path.name for widget in selected[:3])
        if len(selected) > 3:
            preview += f", and {len(selected) - 3} more"
        if QMessageBox.question(
            self,
            "Delete",
            f"Delete the selected item(s)?\n\n{preview}",
        ) != QMessageBox.Yes:
            return
        for widget in selected:
            try:
                if not widget.file_path.exists():
                    raise FileNotFoundError(widget.file_path)
                widget.file_path.unlink()
            except FileNotFoundError:
                QMessageBox.warning(self, "Delete", "The file could not be found. It may have been moved or deleted.")
            except OSError as exc:
                QMessageBox.warning(self, "Delete", friendly_error_message(exc, context="Delete failed"))
        self.load_inventory()

    def toggle_favorite(self, title):
        self.parent_app.toggle_favorite(title)
        self.load_inventory()

    def select_item(self, widget):
        if self.selected_widget:
            self.selected_widget.is_selected = False
            self.selected_widget.update_style()
        
        self.selected_widget = widget
        if self.selected_widget:
            self.selected_widget.is_selected = True
            self.selected_widget.update_style()
            self.scroll.ensureWidgetVisible(self.selected_widget)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            if self.selected_widget and isinstance(self.selected_widget, InventoryItemWidget):
                self.selected_widget.set_checked(not self.selected_widget.is_checked())
                return
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            widgets = []
            for i in range(self.list_layout.count()):
                w = self.list_layout.itemAt(i).widget()
                if isinstance(w, InventoryItemWidget):
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

class FavoritesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.settings = parent.settings
        self.download_dir = parent.download_dir
        self.setWindowTitle("Favourites")
        self.resize(800, 600)
        self.selected_widget = None
        self.setup_ui()
        QTimer.singleShot(0, self.load_favorites)

    def setup_ui(self):
        layout = QVBoxLayout(self)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Favourite Sounds"))
        title_row.addStretch()

        btn_refresh = QPushButton(" Refresh")
        btn_refresh.clicked.connect(self.load_favorites)
        btn_refresh.setFocusPolicy(Qt.NoFocus)
        btn_refresh.setAutoDefault(False)
        btn_refresh.setDefault(False)
        title_row.addWidget(btn_refresh)
        layout.addLayout(title_row)

        self.stacked = QStackedWidget()

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignCenter)

        self.loading_label = QLabel("Loading favourites...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size: 16px; color: #888;")

        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setFixedWidth(200)

        loading_layout.addWidget(self.loading_label)
        loading_layout.addWidget(self.loading_progress)
        self.stacked.addWidget(self.loading_widget)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        self.stacked.addWidget(self.scroll)

        layout.addWidget(self.stacked)
        self.stacked.setCurrentWidget(self.loading_widget)

    def load_favorites(self):
        self.stacked.setCurrentWidget(self.loading_widget)
        QTimer.singleShot(0, self._populate_favorites)

    def _populate_favorites(self):
        self.selected_widget = None
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        favorites = self.parent_app.get_favorite_items()
        if not favorites:
            empty_icon = QLabel()
            empty_icon.setPixmap(get_icon("heart.png", color_invert=self.is_dark_theme()).pixmap(64, 64))
            empty_icon.setAlignment(Qt.AlignCenter)

            empty_label = QLabel("No favourites yet")
            empty_label.setStyleSheet("font-size: 16px; color: #888;")
            empty_label.setAlignment(Qt.AlignCenter)

            self.list_layout.addStretch()
            self.list_layout.addWidget(empty_icon)
            self.list_layout.addWidget(empty_label)
            self.list_layout.addStretch()
        else:
            for i, item in enumerate(favorites):
                is_downloaded = target_path_for(self.download_dir, item["title"]).exists()
                widget = SoundItemWidget(
                    item,
                    is_downloaded,
                    True,
                    parent_app=self,
                    is_even=(i % 2 == 0),
                )
                widget.play_requested.connect(self.play_sound)
                widget.download_requested.connect(self.download_item)
                widget.favorite_requested.connect(self.toggle_favorite)
                self.list_layout.addWidget(widget)

        self.stacked.setCurrentWidget(self.scroll)

    def select_item(self, widget):
        if self.selected_widget:
            self.selected_widget.is_selected = False
            self.selected_widget.update_style()

        self.selected_widget = widget
        if self.selected_widget:
            self.selected_widget.is_selected = True
            self.selected_widget.update_style()
            self.scroll.ensureWidgetVisible(self.selected_widget)

    def play_sound(self, item):
        self.parent_app.play_sound(item)

    def download_item(self, item):
        try:
            self.parent_app.download_item(item)
        except FileNotFoundError:
            QMessageBox.warning(self, "Download", "The file could not be found. It may have been moved or deleted.")
            self.load_favorites()
        except OSError as exc:
            QMessageBox.warning(self, "Download", friendly_error_message(exc, context="Download failed"))

    def rename_downloaded_item(self, file_path):
        self.parent_app.rename_downloaded_item(file_path)

    def delete_downloaded_item(self, file_path):
        self.parent_app.delete_downloaded_item(file_path)

    def toggle_favorite(self, item):
        self.parent_app.toggle_favorite(item)
        self.load_favorites()

    def is_dark_theme(self):
        return self.settings.get("appearance_mode", "Dark") in ["Dark", "System"]

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

class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("About")
        self.resize(300, 200)
        self.setup_ui(parent)

    def setup_ui(self, parent):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(15)

        from .theme import get_icon
        is_dark = parent.settings.get("appearance_mode", "Dark") in ["Dark", "System"]

        icon_label = QLabel()
        icon_label.setPixmap(get_icon("flush.png", color_invert=is_dark).pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel("MyInstants Downloader")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        desc_label = QLabel(
            "A simple and clean downloader for MyInstants.\n"
            "Built with PySide6.\n\n"
            "Credits: RiffPointer and Shagnikpaul 2026\n"
            "https://github.com/Shagnikpaul/MyInstants-Downloader-GUI\n"
            "Licensed under the MIT License"
        )
        desc_label.setStyleSheet("font-size: 14px; color: #888;")
        desc_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc_label)

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
