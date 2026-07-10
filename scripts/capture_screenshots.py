"""Generate release screenshots without requiring a browser."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def capture_gui(output: Path) -> None:
    from PIL import Image, ImageDraw

    from laserlab.fixtures import list_fixtures

    width = 1400
    height = 900
    image = Image.new("RGB", (width, height), "#f7fafc")
    draw = ImageDraw.Draw(image)
    font_title = _font(28, bold=True)
    font_h = _font(17, bold=True)
    font = _font(15)
    font_small = _font(13)

    tabs = ["Experiment", "Sources", "Run", "Review", "Fixtures", "Settings"]
    x = 32
    for index, tab in enumerate(tabs):
        tab_width = 140 if index != 3 else 132
        fill = "#ffffff" if index == 0 else "#e6eef5"
        draw.rounded_rectangle((x, 26, x + tab_width, 70), radius=6, fill=fill, outline="#b8c8d8")
        draw.text((x + 18, 40), tab, fill="#102a43", font=font_h)
        x += tab_width - 1

    draw.text((42, 105), "LaserLab", fill="#102a43", font=font_title)
    draw.text(
        (42, 143),
        "Blinded signal validation dashboard over the laserlab v2 engine",
        fill="#52616b",
        font=font,
    )

    _panel(draw, (42, 188, 1358, 302), "Experiment", font_h, font)
    _field(draw, (178, 228, 1040, 266), "experiments\\release-demo", font)
    _button(draw, (1060, 228, 1180, 266), "Browse", font_small)
    _button(draw, (1194, 228, 1294, 266), "Open", font_small)
    draw.text((68, 237), "Directory", fill="#334e68", font=font)

    _panel(draw, (42, 324, 1358, 500), "Sources", font_h, font)
    draw.text((68, 368), "Path", fill="#334e68", font=font)
    _field(draw, (178, 358, 1040, 396), "sample_media\\commons-young-double-slit.ogv", font)
    _button(draw, (1060, 358, 1180, 396), "Browse", font_small)
    _button(draw, (1194, 358, 1294, 396), "Add Capture", font_small)
    draw.text((68, 424), "Kind", fill="#334e68", font=font)
    _field(draw, (178, 414, 350, 452), "video", font)
    draw.text((400, 424), "Label", fill="#334e68", font=font)
    _field(draw, (482, 414, 654, 452), "laser", font)
    draw.text((704, 424), "Frame interval", fill="#334e68", font=font)
    _field(draw, (835, 414, 952, 452), "1", font)
    draw.text((994, 424), "Max frames", fill="#334e68", font=font)
    _field(draw, (1106, 414, 1223, 452), "2", font)
    draw.rectangle((1250, 423, 1264, 437), fill="#ffffff", outline="#9fb3c8")
    draw.text((1274, 419), "All frames", fill="#334e68", font=font)

    table = (42, 526, 1358, 744)
    headers = ["Capture ID", "Label", "Kind", "Frames", "Source"]
    rows = [
        ["cap-laser", "laser", "video", "2", "commons-young-double-slit.ogv"],
        ["cap-control", "control", "video", "2", "commons-double-slit-experiment.webm"],
    ]
    _table(draw, table, headers, rows, font_small)

    _panel(draw, (42, 770, 1358, 846), "Release Targets", font_h, font)
    draw.text((70, 810), "LaserLab.exe", fill="#102a43", font=font_h)
    draw.text((206, 812), "desktop dashboard", fill="#52616b", font=font)
    draw.text((470, 810), "LaserLabCLI.exe", fill="#102a43", font=font_h)
    draw.text((642, 812), "scripted init/run/report/fixtures workflows", fill="#52616b", font=font)
    draw.text((1018, 812), f"{len(list_fixtures())} bundled fixtures", fill="#102a43", font=font_h)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def capture_report(summary_path: Path, candidates_path: Path, output: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = []
    with candidates_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)[:8]

    width = 1400
    height = 900
    image = Image.new("RGB", (width, height), "#f7fafc")
    draw = ImageDraw.Draw(image)
    font_title = _font(34, bold=True)
    font_h = _font(20, bold=True)
    font = _font(17)
    font_small = _font(14)

    stats = summary["aggregate_statistics"]
    draw.text((48, 38), "LaserAnalysisAI Release Demo Report", fill="#16202a", font=font_title)
    draw.text((50, 90), f"Run: {summary['run_id']}  |  Profile: {summary['profile']}  |  Seed: {summary['blind_seed']}", fill="#52616b", font=font)

    cards = [
        ("Evidence", stats["evidence_ladder"]),
        ("Samples", str(summary["sample_count"])),
        ("Detector Records", str(summary["result_count"])),
        ("Laser Mean", f"{stats['laser_mean_score']:.4f}"),
        ("Control Mean", f"{stats['control_mean_score']:.4f}"),
        ("Permutation p", f"{stats['permutation_p_value']:.4f}"),
    ]
    x = 48
    y = 136
    for label, value in cards:
        draw.rounded_rectangle((x, y, x + 200, y + 92), radius=8, fill="#ffffff", outline="#cbd5e1")
        draw.text((x + 16, y + 16), label.upper(), fill="#627d98", font=font_small)
        draw.text((x + 16, y + 48), value, fill="#102a43", font=font_h)
        x += 218

    draw.text((48, 270), "Null Result Language", fill="#102a43", font=font_h)
    draw.multiline_text((48, 304), _wrap(stats["null_result_language"], 128), fill="#334e68", font=font, spacing=6)

    table_y = 410
    draw.text((48, table_y - 44), "Top Candidates", fill="#102a43", font=font_h)
    headers = ["Rank", "Blind ID", "Label", "Score", "Persist", "Variant", "OCR"]
    widths = [70, 130, 150, 90, 90, 190, 570]
    x = 48
    for header, col_width in zip(headers, widths):
        draw.rectangle((x, table_y, x + col_width, table_y + 34), fill="#d9e2ec")
        draw.text((x + 8, table_y + 8), header, fill="#243b53", font=font_small)
        x += col_width

    y = table_y + 34
    for row in rows:
        x = 48
        values = [
            row["rank"],
            row["blind_id"],
            row["unblinded_label"],
            row["structure_score"],
            row["persistence_score"],
            row["preprocessing_variant"],
            (row["ocr_text"] or "").replace("\n", " ")[:80],
        ]
        for value, col_width in zip(values, widths):
            draw.rectangle((x, y, x + col_width, y + 42), fill="#ffffff", outline="#e6eef5")
            draw.text((x + 8, y + 11), str(value), fill="#334e68", font=font_small)
            x += col_width
        y += 42

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def capture_cli(output: Path) -> None:
    from PIL import Image, ImageDraw

    commands = [
        [sys.executable, "-m", "laserlab.cli", "--help"],
        [sys.executable, "-m", "laserlab.cli", "fixtures", "list", "--include-restricted"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        blocks.append(f"> {' '.join(command[1:])}\n{result.stdout.strip()}")

    width = 1400
    height = 980
    image = Image.new("RGB", (width, height), "#0b1220")
    draw = ImageDraw.Draw(image)
    font_title = _font(30, bold=True)
    font = _font(17)
    font_small = _font(15)

    draw.text((44, 34), "LaserLab CLI Surface", fill="#e6f0ff", font=font_title)
    draw.text((46, 78), "GUI target: LaserLab.exe  |  CLI target: LaserLabCLI.exe", fill="#93a4b8", font=font)

    y = 124
    for block in blocks:
        lines = block.splitlines()
        draw.rounded_rectangle((44, y, width - 44, min(height - 44, y + 360)), radius=8, fill="#111827", outline="#334155")
        yy = y + 20
        for line in lines[:18]:
            color = "#7dd3fc" if line.startswith(">") else "#dbeafe"
            draw.text((64, yy), line[:132], fill=color, font=font_small)
            yy += 24
        y += 394

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def _panel(draw, box: tuple[int, int, int, int], title: str, font_h, font) -> None:
    draw.rounded_rectangle(box, radius=6, fill="#ffffff", outline="#cbd5e1")
    draw.text((box[0] + 22, box[1] + 18), title, fill="#102a43", font=font_h)


def _field(draw, box: tuple[int, int, int, int], text: str, font) -> None:
    draw.rounded_rectangle(box, radius=4, fill="#f8fbfd", outline="#9fb3c8")
    draw.text((box[0] + 12, box[1] + 10), text, fill="#243b53", font=font)


def _button(draw, box: tuple[int, int, int, int], text: str, font) -> None:
    draw.rounded_rectangle(box, radius=4, fill="#ffffff", outline="#9fb3c8")
    draw.text((box[0] + 14, box[1] + 10), text, fill="#102a43", font=font)


def _table(draw, box: tuple[int, int, int, int], headers: list[str], rows: list[list[str]], font) -> None:
    left, top, right, bottom = box
    widths = [190, 120, 120, 100, right - left - 530]
    x = left
    draw.rectangle((left, top, right, top + 38), fill="#d9e2ec")
    for header, width in zip(headers, widths):
        draw.text((x + 10, top + 11), header, fill="#243b53", font=font)
        x += width
    y = top + 38
    for row in rows:
        x = left
        for value, width in zip(row, widths):
            draw.rectangle((x, y, x + width, y + 46), fill="#ffffff", outline="#e6eef5")
            draw.text((x + 10, y + 14), value[:72], fill="#334e68", font=font)
            x += width
        y += 46
    draw.rectangle((left, top, right, bottom), outline="#cbd5e1")


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> str:
    words = text.split()
    lines = []
    current = []
    for word in words:
        if len(" ".join(current + [word])) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture release screenshots.")
    parser.add_argument("--summary", default="release_dumps/release-demo-summary.json")
    parser.add_argument("--candidates", default="release_dumps/release-demo-top-candidates.csv")
    parser.add_argument("--output-dir", default="screenshots")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    capture_gui(output_dir / "release_gui_dashboard.png")
    capture_cli(output_dir / "release_cli_surface.png")
    capture_report(Path(args.summary), Path(args.candidates), output_dir / "release_report_summary.png")
    print(output_dir / "release_gui_dashboard.png")
    print(output_dir / "release_cli_surface.png")
    print(output_dir / "release_report_summary.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
