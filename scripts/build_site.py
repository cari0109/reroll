"""Build the static GitHub Pages demo into site/.

The demo is the same web UI as `life serve`, plus browser.js, which runs the reroll wheel in
Pyodide instead of talking to a server. Usage: python scripts/build_site.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

PYODIDE = "314.0.7"
ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "reroll" / "web"
SITE = ROOT / "site"


def main() -> None:
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(WEB, SITE)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-q", "-w", str(SITE)], check=True
    )
    wheel = next(SITE.glob("reroll-*.whl")).name

    index = SITE / "index.html"
    html = index.read_text()
    loader = (
        f'<script src="https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/pyodide.js"></script>\n'
        f'  <script>window.REROLL_WHEEL = "{wheel}";</script>\n'
        '  <script src="browser.js"></script>\n'
        '  <script src="app.js"></script>'
    )
    assert html.count('<script src="app.js"></script>') == 1
    index.write_text(html.replace('<script src="app.js"></script>', loader))
    (SITE / ".nojekyll").touch()  # serve files as-is
    print(f"built {SITE.relative_to(ROOT)}/ with {wheel} (Pyodide {PYODIDE})")


if __name__ == "__main__":
    main()
