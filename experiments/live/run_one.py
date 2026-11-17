#!/usr/bin/env python3
"""CLI entrypoint for one dry-run or live InvenioRDM drift run."""

import sys

try:
    from .harness import main
except ImportError:
    from harness import main  # type: ignore[no-redef]  # direct script execution


if __name__ == "__main__":
    sys.exit(main())
