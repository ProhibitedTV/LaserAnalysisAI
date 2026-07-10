"""Fixture catalog and downloader for public laser/interference media."""

from __future__ import annotations

import urllib.request
from urllib.parse import urlencode
from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, sha256_file, write_json


REQUIRED_FIXTURE_FIELDS = {
    "id",
    "title",
    "kind",
    "label",
    "license",
    "attribution",
    "source_page",
    "phenomena",
    "expected_behavior",
    "limitations",
    "redistributable",
}

FIXTURE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "commons-double-slit-experiment",
        "title": "Double slit experiment",
        "kind": "video",
        "label": "control",
        "filename": "commons-double-slit-experiment.webm",
        "commons_file": "Double_slit_experiment.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/a/a0/Double_slit_experiment.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:Double_slit_experiment.webm",
        "license": "CC BY-SA 4.0",
        "attribution": "G. Mikaberidze",
        "notes": "Small simulation useful for detector sanity checks, not physical laser footage.",
        "phenomena": ["interference", "simulation"],
        "expected_behavior": "Stable fringe-like spatial frequencies; no readable text is expected.",
        "limitations": "Rendered simulation rather than camera footage; use only as a structured control.",
        "redistributable": True,
    },
    {
        "id": "commons-young-double-slit",
        "title": "Young's double slit experiment video clip",
        "kind": "video",
        "label": "laser",
        "filename": "commons-young-double-slit.ogv",
        "commons_file": "Double_slit.theora.ogv",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/9/97/Double_slit.theora.ogv",
        "source_page": "https://commons.wikimedia.org/wiki/File:Double_slit.theora.ogv",
        "license": "CC BY-SA 3.0 or GFDL",
        "attribution": "Cookatoo.ergo.ZooM",
        "notes": "Educational double-slit video clip; useful as a small redistributable optical fixture.",
        "phenomena": ["diffraction", "interference"],
        "expected_behavior": "FFT and fringe metrics should respond more strongly than OCR metrics.",
        "limitations": "Educational compressed video with unknown camera and processing history.",
        "redistributable": True,
    },
    {
        "id": "commons-two-pinhole-laser-interference",
        "title": "3D interference of laser light through 2 pinholes",
        "kind": "video",
        "label": "laser",
        "filename": "commons-two-pinhole-laser-interference.webm",
        "commons_file": "3D_Interference_of_Laser_Light_Through_2_Pinholes_Animation.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/5/5f/3D_Interference_of_Laser_Light_Through_2_Pinholes_Animation.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:3D_Interference_of_Laser_Light_Through_2_Pinholes_Animation.webm",
        "license": "CC BY-SA 4.0",
        "attribution": "BrendaEM",
        "notes": "Tomographic visualization from monochromatic laser light through two pinholes.",
        "phenomena": ["interference", "diffraction", "visualization"],
        "expected_behavior": "Repeatable spectral structure is expected; text recovery is not.",
        "limitations": "Tomographic visualization, not a raw sensor recording of an experiment.",
        "redistributable": True,
    },
    {
        "id": "commons-focused-laguerre-gaussian",
        "title": "Focused Laguerre-Gaussian beam",
        "kind": "video",
        "label": "control",
        "filename": "commons-focused-laguerre-gaussian.webm",
        "commons_file": "Focused_Laguerre-Gaussian_beam.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/1/19/Focused_Laguerre-Gaussian_beam.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:Focused_Laguerre-Gaussian_beam.webm",
        "license": "CC BY-SA 4.0",
        "attribution": "Jack Kingsley-Smith",
        "notes": "Rendered optical beam fixture; useful for false-positive checks against structured non-text fields.",
        "phenomena": ["structured_beam", "diffraction", "rendered_control"],
        "expected_behavior": "Ring and texture metrics may respond while OCR should remain null.",
        "limitations": "Rendered beam field; not physical footage and not a matched camera control.",
        "redistributable": True,
    },
    {
        "id": "iwu-single-photon-video-set",
        "title": "Single-photon double-slit and ghost imaging videos",
        "kind": "external-video-set",
        "label": "laser",
        "filename": None,
        "download_url": None,
        "source_page": "https://sun.iwu.edu/~gspaldin/SinglePhotonVideos.html",
        "license": "Classroom-use page; redistribution not confirmed",
        "attribution": "R. S. Aspden, M. J. Padgett, G. C. Spalding",
        "notes": "Scientifically strongest candidate footage. Keep external/manual until redistribution terms are confirmed.",
        "phenomena": ["single_photon", "interference", "diffraction"],
        "expected_behavior": "Accumulating interference structure should emerge over time.",
        "limitations": "External manual source; redistribution and automated download are not permitted by LaserLab.",
        "redistributable": False,
    },
]


def list_fixtures(include_restricted: bool = False) -> list[dict[str, Any]]:
    if include_restricted:
        return FIXTURE_CATALOG[:]
    return [item for item in FIXTURE_CATALOG if item["redistributable"]]


def get_fixture(fixture_id: str) -> dict[str, Any]:
    for item in FIXTURE_CATALOG:
        if item["id"] == fixture_id:
            return item.copy()
    raise KeyError(f"Unknown fixture: {fixture_id}")


def fixture_metadata(fixture_id: str) -> dict[str, Any]:
    item = get_fixture(fixture_id)
    return {
        "fixture_id": item["id"],
        "fixture_title": item["title"],
        "source_page": item["source_page"],
        "license": item["license"],
        "attribution": item["attribution"],
        "phenomena": item["phenomena"],
        "expected_behavior": item["expected_behavior"],
        "limitations": item["limitations"],
        "redistributable": item["redistributable"],
    }


def validate_fixture_catalog(media_dir: Path | None = None, require_bundled_files: bool = False) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    media_dir = Path(media_dir) if media_dir is not None else None
    for item in FIXTURE_CATALOG:
        fixture_id = str(item.get("id") or "<missing-id>")
        missing = sorted(field for field in REQUIRED_FIXTURE_FIELDS if item.get(field) in (None, "", []))
        if missing:
            errors.append(f"{fixture_id}: missing {', '.join(missing)}")
        if fixture_id in seen_ids:
            errors.append(f"{fixture_id}: duplicate fixture id")
        seen_ids.add(fixture_id)
        if item.get("redistributable") and not item.get("filename"):
            errors.append(f"{fixture_id}: redistributable fixture has no filename")
        if require_bundled_files and item.get("redistributable"):
            if media_dir is None or not (media_dir / str(item.get("filename"))).is_file():
                errors.append(f"{fixture_id}: bundled media file is missing")
    return errors


def require_valid_fixture_catalog(media_dir: Path | None = None, require_bundled_files: bool = False) -> None:
    errors = validate_fixture_catalog(media_dir, require_bundled_files=require_bundled_files)
    if errors:
        raise ValueError("Invalid fixture catalog:\n- " + "\n- ".join(errors))


def fetch_fixtures(
    output_dir: Path,
    fixture_ids: list[str] | None = None,
    include_restricted: bool = False,
) -> list[dict[str, Any]]:
    require_valid_fixture_catalog()
    ensure_dir(output_dir)
    selected = list_fixtures(include_restricted=include_restricted)
    if fixture_ids:
        requested = set(fixture_ids)
        selected = [item for item in selected if item["id"] in requested]

    fetched = []
    for item in selected:
        download_url = item.get("download_url") or _commons_download_url(item.get("commons_file"))
        if not download_url or not item.get("filename"):
            fetched.append({**item, "status": "skipped", "reason": "no redistributable download URL"})
            continue
        destination = output_dir / item["filename"]
        _download(download_url, destination)
        fetched.append(
            {
                **item,
                "status": "fetched",
                "path": str(destination),
                "sha256": sha256_file(destination),
            }
        )

    write_json(output_dir / "fixture_manifest.json", {"fixtures": fetched})
    write_attribution(output_dir / "ATTRIBUTION.md", fetched)
    return fetched


def write_attribution(path: Path, fixtures: list[dict[str, Any]]) -> None:
    lines = ["# Fixture Attribution", ""]
    for item in fixtures:
        lines.extend(
            [
                f"## {item['title']}",
                "",
                f"- ID: `{item['id']}`",
                f"- Source: {item['source_page']}",
                f"- License: {item['license']}",
                f"- Attribution: {item['attribution']}",
                f"- Notes: {item['notes']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _download(url: str, destination: Path) -> None:
    ensure_dir(destination.parent)
    request = urllib.request.Request(url, headers={"User-Agent": "LaserAnalysisAI/0.2 fixture downloader"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def _commons_download_url(file_name: str | None) -> str | None:
    if not file_name:
        return None
    params = urlencode(
        {
            "action": "query",
            "titles": f"File:{file_name}",
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        }
    )
    api_url = f"https://commons.wikimedia.org/w/api.php?{params}"
    request = urllib.request.Request(api_url, headers={"User-Agent": "LaserAnalysisAI/0.2 fixture downloader"})
    with urllib.request.urlopen(request, timeout=60) as response:
        import json

        payload = json.loads(response.read().decode("utf-8"))
    pages = payload.get("query", {}).get("pages", {})
    for page in pages.values():
        image_info = page.get("imageinfo", [])
        if image_info and image_info[0].get("url"):
            return image_info[0]["url"]
    return None
