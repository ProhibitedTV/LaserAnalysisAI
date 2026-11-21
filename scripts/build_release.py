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
import tarfile
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
from laserlab.branding import BRAND_FONT_VARIANTS  # noqa: E402

BUNDLED_METADATA = ("fixture_manifest.json", "ATTRIBUTION.md", "optical_benchmark_reference.json",
                    "optical_benchmark_observations.json")
FONT_RIGHTS_NOTICE = "CODEOFREALITY-PERMISSION.txt"
VENDORED_FONT_ARCHIVE = Path("assets/codeofreality/CodeOfReality-authorized-fonts.tar.xz")
VENDORED_FONT_ARCHIVE_SHA256 = "ad07981b0bdf10d2d6c51a9a2cfe1f3ffc00bac1f7920a19fd491884d7b7a2a7"
VENDORED_FONT_ATTESTATION = Path("docs/CODEOFREALITY_DISTRIBUTION_ATTESTATION.md")


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


def _expected_font_hashes() -> dict[str, str]:
    """Verify the seven externally supplied font files against reviewed inputs."""
    manifest = ROOT / "docs" / "codeofreality_font_manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    records = data["filenames"]
    expected = {spec[1] for spec in BRAND_FONT_VARIANTS.values()}
    if set(records) != expected:
        raise ValueError("The CodeOfReality font manifest is incomplete or has unexpected entries")
    return {name: records[name]["sha256"] for name in sorted(expected)}


def _stage_vendored_codeofreality_fonts(build_root: Path) -> Path | None:
    """Stage the seven maintainer-authorized fonts from a pinned source archive.

    Inspect archive members and checksums before writing. Never use tarfile's
    extractall: only regular, exact-name, bounded members are permitted.
    """
    archive = ROOT / VENDORED_FONT_ARCHIVE
    if not archive.is_file():
        return None
    notice = ROOT / VENDORED_FONT_ATTESTATION
    if archive.is_symlink() or notice.is_symlink() or not notice.is_file():
        raise ValueError("Vendored CodeOfReality archive or authorization attestation is unsafe or missing")
    if not 1024 <= archive.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError("Vendored CodeOfReality archive size is outside expected limits")
    if _sha256(archive) != VENDORED_FONT_ARCHIVE_SHA256:
        raise ValueError("Vendored CodeOfReality archive fingerprint mismatch")
    notice_text = notice.read_text(encoding="utf-8")
    if "direct permission" not in notice_text or "Discord" not in notice_text:
        raise ValueError("Vendored CodeOfReality authorization attestation is incomplete")

    expected = _expected_font_hashes()
    destination = build_root / "resources" / "fonts"
    try:
        with tarfile.open(archive, "r:xz") as records:
            members = records.getmembers()
            named = {member.name: member for member in members}
            if len(named) != len(members) or set(named) != set(expected):
                raise ValueError("Vendored CodeOfReality archive does not contain exactly the seven reviewed fonts")
            for name, member in named.items():
                if not member.isfile() or not 1024 <= member.size <= 2 * 1024 * 1024:
                    raise ValueError(f"Unsafe font archive member: {name}")
            destination.mkdir(parents=True, exist_ok=False)
            for name in sorted(expected):
                source = records.extractfile(named[name])
                if source is None:
                    raise ValueError(f"Missing font bytes in archive: {name}")
                with source, (destination / name).open("xb") as output:
                    shutil.copyfileobj(source, output)
                if _sha256(destination / name) != expected[name]:
                    raise ValueError(f"Vendored font fingerprint mismatch: {name}")
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError("Vendored CodeOfReality archive cannot be decoded") from exc
    shutil.copy2(notice, destination / FONT_RIGHTS_NOTICE)
    return destination


def _stage_authorized_fonts(build_root: Path) -> Path | None:
    """Optional release-only font staging; never ingest arbitrary source files.

    Release operators must explicitly attest they hold distribution permission.
    Without both the local source directory and authorization flag, normal
    public builds remain free of third-party fonts.
    """
    source_value = os.environ.get("LASERLAB_RELEASE_FONTS_DIR", "").strip()
    if not source_value:
        return _stage_vendored_codeofreality_fonts(build_root)
    if os.environ.get("LASERLAB_FONT_REDISTRIBUTION_CONFIRMED") != "yes":
        raise ValueError("Set LASERLAB_FONT_REDISTRIBUTION_CONFIRMED=yes only with permission to redistribute all fonts")
    source_dir = Path(source_value).expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError("The authorized font source directory does not exist")
    notice_file = source_dir / FONT_RIGHTS_NOTICE
    if not notice_file.is_file() or notice_file.is_symlink():
        raise ValueError(f"Authorized font bundle must include {FONT_RIGHTS_NOTICE}")
    if not 40 <= notice_file.stat().st_size <= 64 * 1024:
        raise ValueError("The font rights notice is missing or outside expected text limits")
    try:
        notice_text = notice_file.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError("The font rights notice must be UTF-8 text") from exc
    if len(notice_text.strip()) < 40:
        raise ValueError("The font rights notice must identify relevant permission terms")
    destination = build_root / "resources" / "fonts"
    filenames = sorted({spec[1] for spec in BRAND_FONT_VARIANTS.values()})
    fingerprints = _expected_font_hashes()
    for name in filenames:
        source = source_dir / name
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(source_dir):
            raise ValueError(f"Required authorized font file missing or unsafe: {name}")
        if source.stat().st_size > 2 * 1024 * 1024 or source.stat().st_size < 1024:
            raise ValueError(f"Invalid or unexpected authorized font size: {name}")
        if _sha256(source) != fingerprints[name]:
            raise ValueError(f"Authorized font checksum mismatch: {name}")
    destination.mkdir(parents=True, exist_ok=False)
    for name in filenames:
        shutil.copy2(source_dir / name, destination / name)
    shutil.copy2(notice_file, destination / FONT_RIGHTS_NOTICE)
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
    fonts_dir: Path | None = None,
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
        "--collect-all",
        "PIL",
        "--add-data",
        f"{media_dir or ROOT / 'sample_media'}{os.pathsep}sample_media",
    ]
    if fonts_dir is not None:
        command.extend(["--add-data", f"{fonts_dir}{os.pathsep}fonts"])
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


def _assert_packaged_codeofreality_diagnostics(record: dict[str, object]) -> None:
    """Fail native qualification if bundled fonts are not visible to the OCR diagnostics."""
    ocr = record.get("ocr", {})
    if not isinstance(ocr, dict) or not isinstance(ocr.get("tesseract"), dict):
        raise RuntimeError("Packaged OCR diagnostics omitted independent Tesseract state")
    font = ocr.get("codeofreality", {})
    expected = set(BRAND_FONT_VARIANTS)
    if not isinstance(font, dict):
        raise RuntimeError("Packaged CodeOfReality OCR diagnostics are missing")
    statuses = font.get("variant_statuses")
    selected = font.get("selected_variants")
    if (
        font.get("selection") != "enabled"
        or font.get("reference_check") != "completed"
        or font.get("total_variants") != len(expected)
        or font.get("verified_variants") != len(expected)
        or not isinstance(selected, list)
        or len(selected) != len(expected)
        or set(selected) != expected
        or not isinstance(statuses, dict)
        or set(statuses) != expected
        or any(value != "verified" for value in statuses.values())
        or font.get("scientific_accuracy_validated") is not False
        or font.get("tesseract_language_model") is not False
    ):
        raise RuntimeError(
            "Packaged CodeOfReality OCR diagnostics did not confirm seven "
            "selected and verified independent reference templates"
        )


def _smoke(gui_product: Path, cli_product: Path, *, fonts_included: bool = False) -> None:
    gui_executable = gui_product
    if gui_product.suffix == ".app":
        gui_executable = gui_product / "Contents" / "MacOS" / "LaserLab"
    with tempfile.TemporaryDirectory(prefix="laserlab-release-smoke-") as temporary:
        unrelated_cwd = Path(temporary)
        subprocess.run([str(gui_executable), "--smoke"], cwd=unrelated_cwd, check=True, timeout=60)
        subprocess.run([str(gui_executable), "--smoke-resources"], cwd=unrelated_cwd, check=True, timeout=60)
        subprocess.run([str(gui_executable), "--smoke-demo"], cwd=unrelated_cwd, check=True, timeout=120)
        subprocess.run([str(cli_product), "--help"], cwd=unrelated_cwd, check=True, timeout=60)
        if fonts_included:
            font_smoke_env = os.environ.copy()
            font_smoke_env["QT_QPA_PLATFORM"] = "offscreen"
            font_result = subprocess.run(
                [str(gui_executable), "--smoke-fonts"],
                cwd=unrelated_cwd, env=font_smoke_env, check=False, timeout=120,
            )
            font_report_path = unrelated_cwd / "laserlab-font-smoke.json"
            if not font_report_path.is_file():
                raise RuntimeError(
                    f"Packaged GUI font smoke exited {font_result.returncode} without its diagnostic record"
                )
            font_report = json.loads(font_report_path.read_text(encoding="utf-8"))
            if font_result.returncode != 0 or font_report.get("status") != "passed":
                # The diagnostic has only variant names and Qt family values;
                # it contains no experiment media, recording paths or secrets.
                raise RuntimeError("Packaged GUI font smoke failed: " + json.dumps(font_report, sort_keys=True))
            checked = subprocess.run(
                [str(cli_product), "font-verify", "--require-all"],
                cwd=unrelated_cwd, check=True, timeout=120,
                capture_output=True, text=True,
            )
            qualification = json.loads(checked.stdout)
            if (
                qualification.get("total_variants") != len(BRAND_FONT_VARIANTS)
                or qualification.get("verified_variants") != len(BRAND_FONT_VARIANTS)
                or qualification.get("all_verified") is not True
                or qualification.get("scientific_accuracy_validated") is not False
            ):
                raise RuntimeError("Packaged CodeOfReality OCR reference qualification failed")
        # Exercise the opt-in packaged matcher status independently of the
        # optional Tesseract installation (which can be absent on clean hosts).
        diagnostic_env = os.environ.copy()
        if fonts_included:
            diagnostic_env["LASERLAB_FONT_OCR_VARIANTS"] = "all"
        diagnostics = subprocess.run(
            [str(cli_product), "diagnostics", "--format", "json"],
            cwd=unrelated_cwd,
            env=diagnostic_env,
            check=True,
            timeout=120 if fonts_included else 60,
            capture_output=True,
            text=True,
        )
        record = json.loads(diagnostics.stdout)
        if fonts_included:
            _assert_packaged_codeofreality_diagnostics(record)
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
    fonts_dir = _stage_authorized_fonts(build_root)

    _run(_pyinstaller_command("laserlab_launcher.py", "LaserLab", dist_dir, work_dir / "gui", spec_dir, True, media_dir=media_dir, fonts_dir=fonts_dir))
    _run(_pyinstaller_command("laserlab_cli_launcher.py", "LaserLabCLI", dist_dir, work_dir / "cli", spec_dir, False, media_dir=media_dir, fonts_dir=fonts_dir))

    gui_product = _gui_product(dist_dir)
    cli_product = dist_dir / executable_name("LaserLabCLI")
    for product in (gui_product, cli_product):
        if not product.exists():
            raise FileNotFoundError(f"PyInstaller product missing: {product}")
    _smoke(gui_product, cli_product, fonts_included=fonts_dir is not None)
    _assert_source_unchanged(context)

    bundle_dir.mkdir()
    _copy_product(gui_product, bundle_dir / gui_product.name)
    _copy_product(cli_product, bundle_dir / cli_product.name)
    shutil.copy2(ROOT / "README.md", bundle_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", bundle_dir / "LICENSE")
    shutil.copytree(media_dir, bundle_dir / "sample_media")
    if fonts_dir is not None:
        shutil.copytree(fonts_dir, bundle_dir / "fonts")
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
                "bundled_codeofreality_font_count": (len(BRAND_FONT_VARIANTS) if fonts_dir is not None else 0),
                "font_redistribution_attested_by_release_builder": fonts_dir is not None,
                "codeofreality_distribution_record": (
                    str(VENDORED_FONT_ATTESTATION)
                    if fonts_dir is not None and not os.environ.get("LASERLAB_RELEASE_FONTS_DIR", "").strip()
                    else None
                ),
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
