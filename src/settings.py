import json
from .constants import APP_SETTINGS_FILE, DEFAULT_DOWNLOAD_DIR, DEFAULT_REGION, DEFAULT_BASE_URL

def load_settings() -> dict:
    default_settings = {
        "download_dir": str(DEFAULT_DOWNLOAD_DIR),
        "appearance_mode": "Dark",
        "hide_downloaded": True,
        "autoskip_downloaded_pages": True,
        "server_region": DEFAULT_REGION,
        "server_base_url": DEFAULT_BASE_URL,
        "auto_download_next_page": False,
        "concurrent_downloads": 5,
        "search_history": [],
        "favorites": [],
    }
    if not APP_SETTINGS_FILE.exists():
        return default_settings
    try:
        loaded = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings
    return {**default_settings, **loaded}

def save_settings(settings: dict):
    APP_SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
