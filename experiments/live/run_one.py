#!/usr/bin/env python3
"""CLI entrypoint for one dry-run or live InvenioRDM drift run."""

import sys

if __package__:
    from .harness import main
else:  # direct script execution
    from harness import main  # type: ignore[no-redef]


if __name__ == "__main__":
    sys.exit(main())
