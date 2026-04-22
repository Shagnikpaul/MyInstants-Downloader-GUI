# MyInstants Downloader

![BADGE](https://badgen.net/github/release/Shagnikpaul/MyInstants-Downloader-GUI)
![B2](https://img.shields.io/github/downloads/riffpointer/MyInstants-Downloader-GUI/total)

A Qt-based GUI utility to play and download sounds from [myinstants.com](https://www.myinstants.com/en/index/in/).

## What's new in 3.0?
- Rebuilt the app around PySide6 with a cleaner toolbar and menu layout.
- Added batch download progress with skipping for already-downloaded files.
- Added next-page prompting when a page is fully downloaded.
- Added per-row playback state, download progress, and a cleaner inventory flow.
- Added settings for download folder, theme, and concurrent download count.
- Improved search behavior, empty states, and focus handling across dialogs.

## ⚠ IMPORTANT
> [!WARNING]
> It is recommended to turn down the volume of the application to somewhat low level because some sounds of myinstants.com are extremely loud and can literally kill you so consider lowering the volume first and then start using it 🤓

## Running it
For now, executable files are published for Windows only. But you can run it manually by cloning the repo, installing the dependencies from `requirements.txt`, and running the program manually with `py main.py`.

### Portable ZIP
Download the latest release ZIP, extract it, and run `MyInstantsDownloader.exe`.

### Installer
Download the latest installer from the Releases page and run it normally.

## Project Layout (for devs)
- `main.py` is the Qt entrypoint.
- `src/ui/` contains the main window and dialogs.
- `src/workers/` contains scraping, playback, and download workers.
- `resources/` contains bundled icons and audio assets.
- `scripts/build_exe.py` builds the packaged app.
- PyInstaller outputs are written to `scripts/build/` and `scripts/dist/`.

## Tips
- Downloaded files can be found in `downloads` folder present in the directory where files were extracted. (The one contaning the .exe file of this app.
- You can choose a custom download location either from settings or the inventory window.
- The inventory window shows saved files and supports rename/delete actions.
- It shows a warning before playing the sound if it is too loud (requires `ffmpeg` available, i.e to be in PATH).
- (Coming soon) You can drag and drop sound effects from within the inventory window.
- (Coming soon) Support for more services.

## Screenshot
Main screen (dark mode):
<img width="882" height="656" alt="image" src="https://github.com/user-attachments/assets/bbbf137a-d1cd-4f0d-87e7-fcfe2c13da19" />

Main screen (light mode. I know the search icon aint visible in light mode but i'll fix it later):
<img width="882" height="656" alt="image" src="https://github.com/user-attachments/assets/b4e7e3a8-49db-422a-bdf3-d272db2f8040" />

Inventory screen:
<img width="802" height="632" alt="image" src="https://github.com/user-attachments/assets/1f552102-14ae-4b97-9651-eeb32a96cbd2" />

Batch download:
<img width="602" height="532" alt="image" src="https://github.com/user-attachments/assets/441e154d-599e-4257-aedb-4695d9443bb2" />

## Libraries Used.
- `PySide6` for GUI
- Beautiful Soup for web scraping
- Python Requests for HTML extraction and file download.
- `playsound` library for playing sounds.

## License
Licensed under the MIT License.

## Contributors
- https://github.com/Shagnikpaul - Author
- https://github.com/riffpointer - PySide6 port
