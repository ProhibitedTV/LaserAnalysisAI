"""PyInstaller-friendly CLI entrypoint for LaserLab."""

from laserlab.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
