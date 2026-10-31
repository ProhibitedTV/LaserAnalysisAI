"""PyInstaller-friendly CLI entrypoint for LaserLab."""

from laserlab.diagnostics import configure_logging

try:
    configure_logging()
except OSError:
    pass

from laserlab.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
