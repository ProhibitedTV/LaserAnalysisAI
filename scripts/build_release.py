"""Build and verify a native LaserLab release archive for the current host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
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
from laserlab.fixtures import FIXTURE_CATALOG, validate_fixture_catalog  # noqa: E402

BUNDLED_METADATA = ("fixture_manifest.json", "ATTRIBUTION.md", "optical_benchmark_reference.json",
                    "optical_benchmark_observations.json")


def _git(*arguments: str, allow_missing: bool = False) -> str:
    try:
        result = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        if allow_missing and isinstance(exc, subprocess.CalledProcessError) and exc.returncode == 1:
            return ""
        raise RuntimeError("Release qualification requires a Git checkout with available source history.") from exc
    return result.stdout.strip()


def _source_state() -> dict[str, str]:
    if Path(_git("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise RuntimeError("Git source history does not belong to this checkout root.")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("Release qualification requires a clean checkout. Commit or preserve source changes first.")
    return {"source_revision": _git("rev-parse", "HEAD"), "source_tree": _git("rev-parse", "HEAD^{tree}")}


def _release_context(release_tag: str | None = None) -> dict[str, object]:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]*", __version__):
        raise ValueError("The application version is not a supported archive identifier.")
    ref = os.environ.get("GITHUB_REF", "")
    workflow_tag = ref[len("refs/tags/"):] if ref.startswith("refs/tags/") else None
    if workflow_tag and release_tag and workflow_tag != release_tag:
        raise ValueError("The release tag must match the workflow tag.")
    tag = workflow_tag or release_tag
    if tag and tag != f"v{__version__}":
        raise ValueError("The release tag must exactly match the application version.")
    source = _source_state()
    if tag and _git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}") != source["source_revision"]:
        raise ValueError("The release tag does not identify the checked-out source revision.")
    channel = ("release" if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", __version__) else "prerelease") if tag else "candidate"
    return {"version": __version__, **source, "source_dirty": False, "build_channel": channel, "release_tag": tag}


def _assert_source_unchanged(context: dict[str, object]) -> None:
    current = _source_state()
    if any(current[key] != context[key] for key in current):
        raise RuntimeError("Source changed during packaging. The candidate cannot be qualified.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_resources(build_root: Path) -> Path:
    destination = build_root / "resources" / "sample_media"
    destination.mkdir(parents=True)
    names = set(BUNDLED_METADATA) | {str(item["filename"]) for item in FIXTURE_CATALOG if item.get("redistributable")}
    media_root = ROOT / "sample_media"
    for name in sorted(names):
        source = media_root / name
        if Path(name).name != name or source.is_symlink() or not source.resolve().is_relative_to(media_root):
            raise ValueError("A bundled resource is not a managed fixture file.")
        shutil.copy2(source, destination / name)
    if validate_fixture_catalog(destination, require_bundled_files=True):
        raise ValueError("Bundled fixture validation failed. No release archive was created.")
    return destination


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
    *,
    media_dir: Path | None = None,
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
        f"{media_dir or ROOT / 'sample_media'}{os.pathsep}sample_media",
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
    with tempfile.TemporaryDirectory(prefix="laserlab-release-smoke-") as temporary:
        unrelated_cwd = Path(temporary)
        subprocess.run([str(gui_executable), "--smoke"], cwd=unrelated_cwd, check=True, timeout=60)
        subprocess.run([str(gui_executable), "--smoke-resources"], cwd=unrelated_cwd, check=True, timeout=60)
        subprocess.run([str(gui_executable), "--smoke-demo"], cwd=unrelated_cwd, check=True, timeout=120)
        subprocess.run([str(cli_product), "--help"], cwd=unrelated_cwd, check=True, timeout=60)
        diagnostics = subprocess.run(
            [str(cli_product), "diagnostics", "--format", "json"],
            cwd=unrelated_cwd,
            check=True,
            timeout=60,
            capture_output=True,
            text=True,
        )
        record = json.loads(diagnostics.stdout)
        fixtures = record.get("fixtures", {})
        if not fixtures.get("catalog_valid") or fixtures.get("bundled_file_count") != fixtures.get("redistributable_count"):
            raise RuntimeError("Packaged diagnostics did not find every bundled fixture")
        pack = unrelated_cwd / "synthetic-probes"
        report_path = unrelated_cwd / "benchmark.json"
        subprocess.run([str(cli_product), "benchmark", "generate", "--output", str(pack)], cwd=unrelated_cwd, check=True, timeout=60)
        subprocess.run([str(cli_product), "benchmark", "run", "--pack", str(pack), "--output", str(report_path)],
                       cwd=unrelated_cwd, check=True, timeout=60)
        benchmark = json.loads(report_path.read_text(encoding="utf-8"))
        if benchmark.get("case_count") != 10 or benchmark.get("probe_count") != 40 or benchmark.get("empirical_capture_count") != 0:
            raise RuntimeError("Packaged synthetic benchmark did not preserve its scope")


def _write_archive(bundle_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_dir.parent))


def build_release(output_dir: Path, target: str, *, release_tag: str | None = None) -> Path:
    if target not in VALID_TARGETS:
        raise ValueError(f"Unsupported release target: {target}")
    if target != default_target():
        raise ValueError("The native target must match the build host's operating system and architecture.")
    context = _release_context(release_tag)
    identity = f"v{__version__}"
    if context["build_channel"] == "candidate":
        identity += f"-candidate-{str(context['source_revision'])[:12]}"
    bundle_name = f"LaserLab-{identity}-{target}"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_relative_to(ROOT) and _git("check-ignore", "--", str(output_dir), allow_missing=True) == "":
        raise ValueError("Choose an ignored output directory such as dist, or a directory outside the checkout.")
    bundle_dir = output_dir / bundle_name
    archive_path = output_dir / f"{bundle_name}.zip"
    checksum_path = output_dir / f"{archive_path.name}.sha256"
    if any(path.exists() for path in (bundle_dir, archive_path, checksum_path)):
        raise FileExistsError("Release outputs already exist. Choose a fresh output directory; existing outputs are preserved.")
    build_parent = ROOT / "build"
    if build_parent.resolve() != ROOT / "build":
        raise ValueError("The release build directory must remain inside the checkout.")
    build_parent.mkdir(exist_ok=True)
    build_root = Path(tempfile.mkdtemp(prefix=f"release-{target}-", dir=build_parent))
    dist_dir = build_root / "pyinstaller"
    work_dir = build_root / "work"
    spec_dir = build_root / "spec"
    dist_dir.mkdir(parents=True)
    work_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    media_dir = _stage_resources(build_root)

    _run(_pyinstaller_command("laserlab_launcher.py", "LaserLab", dist_dir, work_dir / "gui", spec_dir, True, media_dir=media_dir))
    _run(_pyinstaller_command("laserlab_cli_launcher.py", "LaserLabCLI", dist_dir, work_dir / "cli", spec_dir, False, media_dir=media_dir))

    gui_product = _gui_product(dist_dir)
    cli_product = dist_dir / executable_name("LaserLabCLI")
    for product in (gui_product, cli_product):
        if not product.exists():
            raise FileNotFoundError(f"PyInstaller product missing: {product}")
    _smoke(gui_product, cli_product)
    _assert_source_unchanged(context)

    bundle_dir.mkdir()
    _copy_product(gui_product, bundle_dir / gui_product.name)
    _copy_product(cli_product, bundle_dir / cli_product.name)
    shutil.copy2(ROOT / "README.md", bundle_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", bundle_dir / "LICENSE")
    shutil.copytree(media_dir, bundle_dir / "sample_media")
    (bundle_dir / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                **context,
                "target": target,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "built_at_utc": datetime.now(timezone.utc).isoformat(),
                "checksums_file": "SHA256SUMS",
                "qualification": "headless startup/resources/demo/diagnostics/benchmark; native UI acceptance is separate",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with (bundle_dir / "SHA256SUMS").open("x", encoding="utf-8", newline="\n") as handle:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file() and path != bundle_dir / "SHA256SUMS":
                handle.write(f"{_sha256(path)}  {path.relative_to(bundle_dir).as_posix()}\n")
    _assert_source_unchanged(context)
    _write_archive(bundle_dir, archive_path)
    _assert_source_unchanged(context)
    with checksum_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{_sha256(archive_path)}  {archive_path.name}\n")
    print(f"Built and verified {archive_path}")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--target", choices=sorted(VALID_TARGETS), default=default_target())
    parser.add_argument("--release-tag", help="Optional matching v<version> tag at this exact commit; untagged builds are candidates.")
    args = parser.parse_args()
    archive = build_release(args.output_dir, args.target, release_tag=args.release_tag)
    if os.environ.get("GITHUB_OUTPUT"):
        info = json.loads((archive.with_suffix("") / "BUILD-INFO.json").read_text(encoding="utf-8"))
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"prerelease={str(info['build_channel'] != 'release').lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
