"""Build and verify a native LaserLab release archive for the current host."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_TARGETS = {
    "windows-x86_64",
    "linux-x86_64",
    "macos-x86_64",
    "macos-arm64",
}
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from laserlab import __version__  # noqa: E402


def default_target() -> str:
    system = {
        "Windows": "windows",
        "Darwin": "macos",
        "Linux": "linux",
    }.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
    return f"{system}-{architecture}"


def executable_name(name: str) -> str:
    return f"{name}.exe" if platform.system() == "Windows" else name


def _run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _pyinstaller_command(
    launcher: str,
    name: str,
    dist_dir: Path,
    work_dir: Path,
    spec_dir: Path,
    windowed: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--collect-all",
        "cv2",
        "--collect-all",
        "pytesseract",
        "--add-data",
        f"{ROOT / 'sample_media'}{os.pathsep}sample_media",
    ]
    if windowed:
        command.append("--windowed")
    command.append(str(ROOT / launcher))
    return command


def _copy_product(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _gui_product(dist_dir: Path) -> Path:
    app_bundle = dist_dir / "LaserLab.app"
    if app_bundle.exists():
        return app_bundle
    return dist_dir / executable_name("LaserLab")


def _smoke(gui_product: Path, cli_product: Path) -> None:
    gui_executable = gui_product
    if gui_product.suffix == ".app":
        gui_executable = gui_product / "Contents" / "MacOS" / "LaserLab"
    subprocess.run([str(gui_executable), "--smoke"], cwd=ROOT, check=True, timeout=60)
    subprocess.run([str(cli_product), "--help"], cwd=ROOT, check=True, timeout=60)


def _write_archive(bundle_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_dir.parent))


def build_release(output_dir: Path, target: str) -> Path:
    if target not in VALID_TARGETS:
        raise ValueError(f"Unsupported release target: {target}")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_root = (ROOT / "build" / f"release-{target}").resolve()
    if build_root.exists():
        shutil.rmtree(build_root)
    dist_dir = build_root / "pyinstaller"
    work_dir = build_root / "work"
    spec_dir = build_root / "spec"
    dist_dir.mkdir(parents=True)
    work_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)

    _run(_pyinstaller_command("laserlab_launcher.py", "LaserLab", dist_dir, work_dir / "gui", spec_dir, True))
    _run(_pyinstaller_command("laserlab_cli_launcher.py", "LaserLabCLI", dist_dir, work_dir / "cli", spec_dir, False))

    gui_product = _gui_product(dist_dir)
    cli_product = dist_dir / executable_name("LaserLabCLI")
    for product in (gui_product, cli_product):
        if not product.exists():
            raise FileNotFoundError(f"PyInstaller product missing: {product}")
    _smoke(gui_product, cli_product)

    bundle_name = f"LaserLab-v{__version__}-{target}"
    bundle_dir = output_dir / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir()
    _copy_product(gui_product, bundle_dir / gui_product.name)
    _copy_product(cli_product, bundle_dir / cli_product.name)
    shutil.copy2(ROOT / "README.md", bundle_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", bundle_dir / "LICENSE")
    shutil.copytree(ROOT / "sample_media", bundle_dir / "sample_media")
    (bundle_dir / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                "version": __version__,
                "target": target,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    archive_path = output_dir / f"{bundle_name}.zip"
    archive_path.unlink(missing_ok=True)
    _write_archive(bundle_dir, archive_path)
    print(f"Built and verified {archive_path}")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--target", choices=sorted(VALID_TARGETS), default=default_target())
    args = parser.parse_args()
    build_release(args.output_dir, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
