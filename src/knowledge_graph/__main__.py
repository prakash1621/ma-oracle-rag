"""Module entrypoint for: python -m src.knowledge_graph ..."""

from __future__ import annotations

import sys

from src.knowledge_graph.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

