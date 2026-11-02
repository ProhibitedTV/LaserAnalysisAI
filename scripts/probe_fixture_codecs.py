"""Read one frame from each bundled public fixture without running an analysis."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from laserlab.fixtures import FIXTURE_CATALOG  # noqa: E402


def main() -> int:
    import cv2

    print(json.dumps({"opencv_version": cv2.__version__}), flush=True)
    for line in cv2.getBuildInformation().splitlines():
        if any(name in line for name in ("FFMPEG:", "avcodec:", "avformat:", "GStreamer:")):
            print(line.strip(), flush=True)
    failed = False
    for fixture in FIXTURE_CATALOG:
        if not fixture.get("redistributable"):
            continue
        capture = cv2.VideoCapture(str(ROOT / "sample_media" / fixture["filename"]))
        try:
            opened = capture.isOpened()
            backend = capture.getBackendName() if opened else None
            ok, frame = capture.read() if opened else (False, None)
            decoded = bool(ok and frame is not None and frame.size)
            failed |= not decoded
            print(json.dumps({"fixture": fixture["id"], "opened": opened,
                              "backend": backend, "decoded": decoded}), flush=True)
        finally:
            capture.release()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
