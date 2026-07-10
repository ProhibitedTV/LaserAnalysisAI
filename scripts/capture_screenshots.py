"""Generate release screenshots without requiring a browser."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def capture_gui(output: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 780)
    window.show()
    app.processEvents()
    pixmap = window.grab()
    output.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(output))
    window.close()


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
    draw.text((46, 78), "Release executable target: LaserLab.exe", fill="#93a4b8", font=font)

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
    capture_cli(output_dir / "release_cli_surface.png")
    capture_report(Path(args.summary), Path(args.candidates), output_dir / "release_report_summary.png")
    print(output_dir / "release_cli_surface.png")
    print(output_dir / "release_report_summary.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
