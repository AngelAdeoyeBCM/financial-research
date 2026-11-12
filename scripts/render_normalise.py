"""Render a Stage 1 normalise run (its sample + ``edits.jsonl``) as text.

Views: ``marks`` (``{{original => text}}``), ``brackets`` (resolved, insertions in ``[ ]``), ``plain`` (resolved) and
``sentences`` (``[E001] ...`` per tagged sentence, bracketed). Prints to stdout unless ``--out`` is given.

Usage::

    python scripts/render_normalise.py outputs/normalise_v20/opus
    python scripts/render_normalise.py outputs/normalise_v20/opus --view marks
    python scripts/render_normalise.py outputs/normalise_v20/opus --view sentences --out sentences.txt
"""

import argparse
import sys
from pathlib import Path

from incolor.propositions.edits import VIEWS, load_run, render


def main() -> int:
    """Print or write the requested view."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", type=Path, help="normalise run folder")
    parser.add_argument("--view", choices=VIEWS, default="brackets")
    parser.add_argument("--out", type=Path, help="write to this file instead of stdout")
    args = parser.parse_args()

    text = render(load_run(args.run)[2], args.view) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
