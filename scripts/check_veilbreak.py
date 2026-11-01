"""Opt-in live compatibility probe; saves only sanitized transport/schema facts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from laserlab.veilbreak_bridge import VeilbreakError, check_public_compatibility


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly contact Veilbreak's public, keyless read-only MCP service.")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Pass --live to opt into public network reads. No local experiment data is sent.")
    try:
        summary = check_public_compatibility()
    except VeilbreakError as exc:
        print(json.dumps({"compatible": False, "error": str(exc)}))
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
