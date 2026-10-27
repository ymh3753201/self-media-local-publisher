#!/usr/bin/env python3
"""Source-checkout entrypoint; installed users can run `publisherctl`."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from self_media_publisher.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
