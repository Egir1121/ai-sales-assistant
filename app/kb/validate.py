"""CLI проверки БЗ: `uv run python -m app.kb.validate [data/kb]`. Код выхода 1 — БЗ невалидна."""

import argparse
import sys
from pathlib import Path

from app.kb.loader import KBError, load_kb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.kb.validate", description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path("data/kb"))
    args = parser.parse_args(argv)

    try:
        kb = load_kb(args.path)
    except KBError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(
        f"OK: {args.path} — {len(kb.faq)} faq, {len(kb.products)} товаров, "
        f"{len(kb.policies)} политик, {len(kb.upsell_rules)} правил допродажи"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
