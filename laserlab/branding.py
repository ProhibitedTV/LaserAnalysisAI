"""CodeOfReality font inventory and safe local installation for LaserLab.

Reference fonts are used only for the wordmark and experimental glyph-template
OCR, never as ordinary scientific readout typography. Public source releases
do not contain font bytes; authorized native builds can bundle reviewed fonts
when their redistribution terms have been established.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import tarfile
from pathlib import Path

from .diagnostics import get_state_dir
from .runtime import resource_path


BRAND_WORDMARK = "laserlab"
BRAND_FONT_ENV = "LASERLAB_BRAND_FONT_PATH"

# (Display label, local filename, Qt family as reported by the font's name table)
# Family names were checked against the uploaded OTF and TTF files.
BRAND_FONT_VARIANTS: dict[str, tuple[str, str, str]] = {
    "classic": ("Classic OTF", "CodeOfRealityV1.otf", "CodeOfReality"),
    "classic-ttf": ("Classic TTF", "CodeOfReality.ttf", "CodeOfReality"),
    "circuit": ("Circuit", "CodeOfReality-Circuit.ttf", "Code of Reality Circuit"),
    "oracle": ("Oracle", "CodeOfReality-Oracle.ttf", "Code of Reality Oracle"),
    "symbols": ("Symbols", "CodeOfRealitySymbols 2.ttf", "Code of Reality Symbols"),
    "symbols-3d": ("Symbols 3D", "CodeOfRealitySymbols-3D.ttf", "Code of Reality Symbols 3D"),
    "symbols-outline": ("Symbols Outline", "CodeOfRealitySymbols-Outline.ttf", "Code of Reality Symbols Outline"),
}

BRAND_FONT_FILENAME = BRAND_FONT_VARIANTS["classic"][1]
BRAND_FONT_FAMILY = BRAND_FONT_VARIANTS["classic"][2]
ALLOWED_BRAND_FAMILIES = frozenset(item[2] for item in BRAND_FONT_VARIANTS.values())

# The supplied 3D/Outline files use OpenType typographic family (nameID 16)
# "Code of Reality Symbols" with styles (nameID 17) "3D" and "Outline".
# On Windows, Qt exposes the shared typographic family rather than nameID 1.
# Keep the original bytes unchanged; select the actual face through styleName.
BRAND_STYLED_VARIANTS = {
    "symbols-3d": ("Code of Reality Symbols", "3D"),
    "symbols-outline": ("Code of Reality Symbols", "Outline"),
}

# SHA-256 of the user's seven reviewed font uploads. These identify reference
# resources; they do not certify a redistribution license.
KNOWN_FONT_SHA256 = {
    "CodeOfRealityV1.otf": "d1f6a0ccb08c3863a0e05d07dc5efabd19b863f97b56f0646309088e116ae81a",
    "CodeOfReality.ttf": "290b37e8d3d35c9bdf7f06f8b3a8768ee53acba6c97c218dd8d572da5d6fa3cb",
    "CodeOfReality-Circuit.ttf": "2ea7c256eab5592180a73449bf4004bdd9881175bc4139eae83eb1dfb3f2c051",
    "CodeOfReality-Oracle.ttf": "ebdc5b562eeedda503288969535c64fe5e0d99ae77428ca5abd038eb5a100c5e",
    "CodeOfRealitySymbols 2.ttf": "9c79fa3c1c371f82c2946d30ad6a673d5a0724a158f441dc6d643501e57e5ef8",
    "CodeOfRealitySymbols-3D.ttf": "9d9ee8df3617ec701b160816cb5ff713bcfd43ba8c46f714654adcd6222f71a0",
    "CodeOfRealitySymbols-Outline.ttf": "39ebbd9aececa93566185758695b8200ff9ef7b554b5a3d6ba482dfe2eee1965",
}

# When files are exported from a chat upload, the first OTF may retain an
# attachment suffix. Still require its exact known SHA-256.
_FONT_UPLOAD_ALIASES = {
    "CodeOfRealityV1.otf": ("CodeOfRealityV1.otf_1", "CodeOfRealityV1(1).otf_1"),
}


def _font_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_local_fonts(source_dir: str | Path, *, destination_dir: Path | None = None) -> dict[str, int]:
    """Locally install the seven verified fonts without publishing them.

    First validate every input and existing destination. Never overwrite an
    unrecognized local font or silently accept a changed reference file.
    """
    source = Path(source_dir).expanduser()
    if not source.is_dir():
        raise ValueError("Source font directory does not exist")
    target_dir = destination_dir if destination_dir is not None else get_state_dir() / "fonts"
    inputs: dict[str, Path] = {}
    for name, expected in KNOWN_FONT_SHA256.items():
        choices = (name, *_FONT_UPLOAD_ALIASES.get(name, ()))
        match = next((source / candidate for candidate in choices if (source / candidate).is_file()), None)
        if match is None or match.is_symlink() or _font_sha256(match) != expected:
            raise ValueError(f"Missing or unexpected CodeOfReality font: {name}")
        inputs[name] = match

    # Abort before copying if any previously installed font has different bytes.
    present = 0
    for name, expected in KNOWN_FONT_SHA256.items():
        destination = target_dir / name
        if destination.is_symlink():
            raise ValueError(f"Refusing to replace linked font: {name}")
        if destination.exists():
            if not destination.is_file() or _font_sha256(destination) != expected:
                raise ValueError(f"Refusing to replace different installed font: {name}")
            present += 1

    target_dir.mkdir(parents=True, exist_ok=True)
    installed = 0
    for name, original in inputs.items():
        destination = target_dir / name
        if destination.exists():
            continue
        descriptor, temporary_name = tempfile.mkstemp(dir=target_dir, prefix=".codeofreality-", suffix=".tmp")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output, original.open("rb") as content:
                shutil.copyfileobj(content, output)
            if _font_sha256(temporary) != KNOWN_FONT_SHA256[name]:
                raise ValueError(f"CodeOfReality input changed during installation: {name}")
            os.replace(temporary, destination)
            installed += 1
        finally:
            temporary.unlink(missing_ok=True)
    return {"installed": installed, "already_present": present, "total": len(KNOWN_FONT_SHA256)}


VENDORED_FONT_ARCHIVE_SHA256 = "ad07981b0bdf10d2d6c51a9a2cfe1f3ffc00bac1f7920a19fd491884d7b7a2a7"


def install_font_archive(archive_path: str | Path, *, destination_dir: Path | None = None) -> dict[str, int]:
    """Install the exact creator-authorized seven-font archive locally.

    The package is available in public source checkouts. Native releases
    already contain the verified individual font resources and need no import.
    """
    archive = Path(archive_path).expanduser()
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("The CodeOfReality font archive is missing or unsafe")
    if not 1024 <= archive.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError("The CodeOfReality font archive has an invalid size")
    if _font_sha256(archive) != VENDORED_FONT_ARCHIVE_SHA256:
        raise ValueError("The CodeOfReality font archive has an unexpected fingerprint")
    try:
        with tempfile.TemporaryDirectory(prefix="laserlab-approved-fonts-") as temporary:
            stage = Path(temporary)
            with tarfile.open(archive, "r:xz") as data:
                entries = data.getmembers()
                names = {entry.name: entry for entry in entries}
                if len(names) != len(entries) or set(names) != set(KNOWN_FONT_SHA256):
                    raise ValueError("The CodeOfReality archive contains unexpected members")
                for name in sorted(names):
                    entry = names[name]
                    if not entry.isfile() or not 1024 <= entry.size <= 2 * 1024 * 1024:
                        raise ValueError(f"Unsafe CodeOfReality archive member: {name}")
                    handle = data.extractfile(entry)
                    if handle is None:
                        raise ValueError(f"Missing CodeOfReality bytes: {name}")
                    with handle, (stage / name).open("xb") as output:
                        shutil.copyfileobj(handle, output)
                    if _font_sha256(stage / name) != KNOWN_FONT_SHA256[name]:
                        raise ValueError(f"CodeOfReality checksum mismatch: {name}")
            return install_local_fonts(stage, destination_dir=destination_dir)
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ValueError("Unable to read the CodeOfReality font archive") from exc


def brand_font_path(variant: str = "classic") -> Path:
    """Return the installation path for a known, optional branding font.

    LASERLAB_BRAND_FONT_PATH remains an override for the classic OTF choice
    for backward compatibility; all other variants use named local files.
    """
    if variant not in BRAND_FONT_VARIANTS:
        raise ValueError("Unknown CodeOfReality font variant")
    override = os.environ.get(BRAND_FONT_ENV, "").strip() if variant == "classic" else ""
    if override:
        return Path(override).expanduser()
    # A release builder may explicitly package fonts after confirming permission.
    # Preserve local per-user font support for ordinary source/CI installations.
    bundled = resource_path("fonts", BRAND_FONT_VARIANTS[variant][1])
    if bundled.is_file():
        return bundled
    return get_state_dir() / "fonts" / BRAND_FONT_VARIANTS[variant][1]


def load_brand_font(variant: str = "classic") -> str | None:
    """Register an installed font after QApplication exists, or return None.

    None means use the legible system fallback. Reject family mismatch or a
    failed Qt registration instead of accidentally styling the wordmark with
    an unrelated installed font.
    """
    if variant == "system" or variant not in BRAND_FONT_VARIANTS:
        return None
    path = brand_font_path(variant)
    if not path.is_file():
        return None

    from PyQt5.QtGui import QFontDatabase

    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return None
    family = BRAND_FONT_VARIANTS[variant][2]
    families = QFontDatabase.applicationFontFamilies(font_id)
    if family in families:
        return family
    styled = BRAND_STYLED_VARIANTS.get(variant)
    if styled is not None and styled[0] in families:
        return styled[0]
    return None
