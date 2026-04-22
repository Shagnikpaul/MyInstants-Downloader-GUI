from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
RESOURCES_DIR = PROJECT_DIR / "resources"
MAIN_PY = PROJECT_DIR / "main.py"
DIST_DIR = SCRIPT_DIR / "dist"
BUILD_DIR = SCRIPT_DIR / "build"
SPEC_DIR = SCRIPT_DIR


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build_command() -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--optimize=2",
        "--name=MyInstantsDownloader",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={SPEC_DIR}",
        f"--add-data={RESOURCES_DIR}{os_pathsep()}resources",
    ]

    if platform.system() == "Windows":
        icon_path = RESOURCES_DIR / "main.ico"
        if icon_path.exists():
            command.append(f"--icon={icon_path}")

    command.append(str(MAIN_PY))
    return command


def os_pathsep() -> str:
    return ";" if platform.system() == "Windows" else ":"


def main() -> int:
    if not MAIN_PY.exists():
        print(f"Missing entrypoint: {MAIN_PY}")
        return 1

    ensure_pyinstaller()

    command = build_command()
    print("Building executable...")
    print(" ".join(f'"{part}"' if " " in part else part for part in command))
    result = subprocess.run(command, cwd=str(PROJECT_DIR))
    if result.returncode != 0:
        print("Build failed.")
        return result.returncode

    print(f"Build complete. Output is in {DIST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
