"""Fixture catalog and downloader for public laser/interference media."""

from __future__ import annotations

import urllib.request
from urllib.parse import urlencode
from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, sha256_file, write_json

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
        "redistributable": False,
    },
]


def list_fixtures(include_restricted: bool = False) -> list[dict[str, Any]]:
    if include_restricted:
        return FIXTURE_CATALOG[:]
    return [item for item in FIXTURE_CATALOG if item["redistributable"]]


def fetch_fixtures(
    output_dir: Path,
    fixture_ids: list[str] | None = None,
    include_restricted: bool = False,
) -> list[dict[str, Any]]:
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
