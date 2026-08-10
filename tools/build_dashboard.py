"""Assemble sb_energy_dashboard_modern.html from the sources in frontend/.

The dashboard is served as one self-contained file by two different consumers --
FastAPI (`FileResponse`) and the Vite build (`?raw` import) -- so the generated
file stays committed at the repository root. Edit `frontend/`, run this, commit
both.

    python tools/build_dashboard.py            # write the dashboard
    python tools/build_dashboard.py --check    # verify it matches, write nothing

Load order is the filename order, and it matters: `13-agent-drawer-base` must
precede `14-agent-drawer-redesign`, whose rules override it at equal specificity.
The JS partials are one classic script sharing globals, not modules, and several
carry immediate-execution wiring, so their order is load-bearing too.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT_ROOT / "frontend"
TEMPLATE = FRONTEND / "html" / "document.template.html"
OUTPUT = PROJECT_ROOT / "sb_energy_dashboard_modern.html"

SLOTS = (
    ("{{CSS}}", FRONTEND / "css", "*.css"),
    ("{{MARKUP}}", FRONTEND / "html", "[0-9]*.html"),
    ("{{JS}}", FRONTEND / "js", "*.js"),
)


def read_partials(directory: Path, pattern: str) -> str:
    paths = sorted(directory.glob(pattern))
    if not paths:
        raise SystemExit(f"no partials matched {directory / pattern}")
    # Each partial was written with a single trailing newline; drop it so the
    # join below reproduces the original line breaks exactly.
    return "\n".join(p.read_text(encoding="utf-8").removesuffix("\n") for p in paths)


def build() -> str:
    document = TEMPLATE.read_text(encoding="utf-8")
    for slot, directory, pattern in SLOTS:
        if slot not in document:
            raise SystemExit(f"template is missing the {slot} slot")
        document = document.replace(slot, read_partials(directory, pattern))
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed dashboard is stale; write nothing",
    )
    args = parser.parse_args()

    built = build()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
        if current == built:
            print(f"{OUTPUT.name} is up to date ({len(built):,} bytes)")
            return 0
        print(
            f"{OUTPUT.name} is STALE -- run `python tools/build_dashboard.py`",
            file=sys.stderr,
        )
        return 1

    OUTPUT.write_text(built, encoding="utf-8")
    print(f"wrote {OUTPUT.name} ({len(built):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
