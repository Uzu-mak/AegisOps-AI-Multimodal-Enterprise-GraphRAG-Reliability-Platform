"""Stamp the web console's assets with content hashes so browsers never run stale code.

The console is plain ES modules served by FastAPI's StaticFiles, which sends no
Cache-Control header, so browsers may keep an old module after a rebuild. This
script writes an import map into index.html that gives every module a
"?v=<hash>" URL, and versions console.css and console.js the same way. The
module files themselves are untouched.

    python scripts/stamp_console.py           # rewrite index.html
    python scripts/stamp_console.py --check   # exit 1 if index.html is stale

Hashes ignore line endings, so a Windows (CRLF) and a Linux (LF) checkout agree.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "console" / "static"
START, END = "<!-- assets:start (scripts/stamp_console.py) -->", "<!-- assets:end -->"


def digest(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:10]


def modules() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*.js") if "samples" not in p.parts)


def render(html: str) -> str:
    imports = {f"./{p.relative_to(STATIC).as_posix()}": f"./{p.relative_to(STATIC).as_posix()}?v={digest(p)}" for p in modules()}
    newline = "\r\n" if "\r\n" in html else "\n"
    block = newline.join([
        START,
        '  <script type="importmap">',
        "  " + json.dumps({"imports": imports}, indent=2).replace("\n", newline + "  "),
        "  </script>",
        f'  <script type="module" src="{imports["./console.js"]}"></script>',
        "  " + END,
    ])
    if START in html:
        html = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, html, flags=re.S)
    else:
        html = html.replace('<script type="module" src="console.js"></script>', block)
    return re.sub(r'href="console\.css(\?v=[0-9a-f]+)?"', f'href="console.css?v={digest(STATIC / "console.css")}"', html)


def main(argv: list[str]) -> int:
    index = STATIC / "index.html"
    raw = index.read_bytes().decode("utf-8")
    stamped = render(raw)
    if "--check" in argv:
        if stamped != raw:
            print("index.html is stale: run python scripts/stamp_console.py", file=sys.stderr)
            return 1
        return 0
    index.write_bytes(stamped.encode("utf-8"))
    print(f"stamped {len(modules())} modules and console.css")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
