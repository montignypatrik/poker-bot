from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    separator = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed", "--name", "Poker Bot",
        "--distpath", ROOT,
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        "--add-data", f"{os.path.join(ROOT, 'study_app')}{separator}study_app",
        "--add-data", f"{os.path.join(ROOT, 'pokerlab', 'flopcache', 'data', 'flop_table.json.gz')}{separator}pokerlab/flopcache/data",
        "--collect-all", "webview",
        os.path.join(ROOT, "study_launcher.py"),
    ]
    print("building:", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
