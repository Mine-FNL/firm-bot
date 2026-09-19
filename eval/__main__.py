"""Allow ``python -m eval.bench`` to run the latency benchmark."""

from __future__ import annotations

from .bench import main

if __name__ == "__main__":
    raise SystemExit(main())
