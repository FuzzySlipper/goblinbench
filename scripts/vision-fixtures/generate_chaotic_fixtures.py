#!/usr/bin/env python3
"""Generate deterministic synthetic chaotic-vision fixtures and manifests.

These images are intentionally simple drawings rather than photorealistic art:
the benchmark goal is stable, inspectable scoring calibration before spending
model time on generated/real messy screenshots.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "fixtures" / "vision" / "chaotic"


def font(size: int = 18):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def save_manifest(name: str, manifest: dict) -> None:
    path = OUT / f"{name}.manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill=(20, 20, 20), size: int = 18) -> None:
    draw.text(xy, text, fill=fill, font=font(size))


def chaotic_desk() -> None:
    img = Image.new("RGB", (960, 640), "#e7dcc8")
    d = ImageDraw.Draw(img)
    # Desk items.
    d.rectangle((350, 190, 615, 420), fill="#fff7dc", outline="#5d4a2f", width=4)
    d.line((370, 205, 592, 400), fill="#c9b88f", width=2)
    draw_label(d, (420, 300), "OPEN NOTEBOOK", size=22)
    d.ellipse((690, 390, 825, 525), fill="#c84232", outline="#6b1711", width=5)
    d.ellipse((725, 420, 790, 485), fill="#7f1e18")
    draw_label(d, (710, 535), "RED MUG", fill="#6b1711", size=18)
    d.rectangle((110, 55, 285, 135), fill="#ffec4f", outline="#806c00", width=3)
    draw_label(d, (145, 78), "TODO", size=26)
    d.line((70, 500, 320, 585), fill="#111111", width=8)
    d.arc((130, 455, 350, 610), 15, 325, fill="#111111", width=8)
    d.arc((190, 470, 430, 620), 180, 30, fill="#222222", width=7)
    draw_label(d, (105, 590), "tangled cable", size=16)
    # Extra clutter.
    d.rounded_rectangle((610, 58, 835, 150), radius=18, fill="#202124", outline="#111")
    draw_label(d, (650, 92), "PHONE", fill="#f1f3f4", size=22)
    d.polygon([(80, 230), (180, 215), (205, 305), (96, 325)], fill="#ffffff", outline="#9a9a9a")
    draw_label(d, (112, 252), "receipt", size=17)
    d.rectangle((250, 120, 335, 155), fill="#3f7fc0", outline="#123456")
    d.rectangle((255, 160, 340, 194), fill="#4e9a51", outline="#1a4c20")
    d.ellipse((535, 470, 575, 510), fill="#666", outline="#222")
    draw_label(d, (505, 520), "small dark object?", size=14)
    img.save(OUT / "chaotic-desk.png")
    save_manifest("chaotic-desk", {
        "image_path": "fixtures/vision/chaotic/chaotic-desk.png",
        "description_goal": "Describe the cluttered desk with enough detail for another agent to inspect regions.",
        "required_mentions": [
            {"id": "open_notebook", "aliases": ["open notebook", "notebook"], "region": "center", "importance": 3},
            {"id": "red_mug", "aliases": ["red mug", "mug", "cup"], "region": "lower right", "importance": 3},
            {"id": "yellow_sticky_note", "aliases": ["yellow sticky note", "sticky note", "TODO"], "region": "upper left", "importance": 2},
            {"id": "tangled_cable", "aliases": ["tangled cable", "cable"], "region": "lower left", "importance": 2},
            {"id": "phone", "aliases": ["phone", "black phone"], "region": "upper right", "importance": 1},
            {"id": "receipt", "aliases": ["receipt", "paper receipt"], "region": "left", "importance": 1}
        ],
        "optional_mentions": [{"id": "colored_bars", "aliases": ["colored bars", "blue and green blocks"], "region": "upper left", "importance": 1}],
        "forbidden_claims": ["fire extinguisher", "person", "dog"],
        "relationship_expectations": [
            {"subject": "red_mug", "relation": "beside", "object": "open_notebook"},
            {"subject": "tangled_cable", "relation": "crosses", "object": "lower left"}
        ],
        "visible_text": [{"text": "TODO", "strict": True}, {"text": "OPEN NOTEBOOK", "strict": False}],
        "ambiguous_items": ["small dark object"]
    })


def busy_dashboard() -> None:
    img = Image.new("RGB", (1100, 700), "#f5f7fb")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 180, 700), fill="#182033")
    for i, label in enumerate(["Home", "Surfaces", "Reviews", "Settings"]):
        y = 70 + i * 60
        fill = "#31405f" if label == "Surfaces" else "#202a40"
        d.rounded_rectangle((18, y, 162, y + 40), radius=8, fill=fill)
        draw_label(d, (42, y + 10), label, fill="#f7f9ff", size=16)
    for i, (x, title, color) in enumerate([(220, "Browser", "#cfe8ff"), (490, "Terminal", "#d7f5dc"), (760, "Notes", "#fff0b8")]):
        d.rounded_rectangle((x, 55, x + 235, 185), radius=16, fill=color, outline="#738299", width=3)
        draw_label(d, (x + 24, 78), title, size=24)
        draw_label(d, (x + 24, 122), "surface card", size=16)
    d.rectangle((230, 235, 555, 520), fill="#ffffff", outline="#aeb8ca", width=3)
    draw_label(d, (250, 250), "CPU chart", size=20)
    d.line([(260, 470), (310, 430), (360, 455), (415, 345), (470, 390), (525, 300)], fill="#2b6cb0", width=5)
    d.rectangle((595, 235, 1015, 520), fill="#ffffff", outline="#aeb8ca", width=3)
    draw_label(d, (620, 250), "Task table", size=20)
    for r, txt in enumerate(["ERR-42   failing", "OK-17    done", "WARN-8   waiting"]):
        y = 300 + r * 55
        d.rectangle((620, y, 980, y + 38), fill="#fff" if r else "#ffe2e2", outline="#ddd")
        draw_label(d, (640, y + 9), txt, size=17)
    d.rounded_rectangle((415, 360, 770, 575), radius=18, fill="#fffdf0", outline="#d78c00", width=5)
    draw_label(d, (455, 390), "Review modal", size=26)
    draw_label(d, (455, 440), "Terminal card needs focus", size=18)
    d.rounded_rectangle((780, 30, 1055, 85), radius=12, fill="#ffe6b3", outline="#b56a00", width=3)
    draw_label(d, (805, 48), "Warning: stale screenshot", size=18)
    img.save(OUT / "busy-dashboard.png")
    save_manifest("busy-dashboard", {
        "image_path": "fixtures/vision/chaotic/busy-dashboard.png",
        "description_goal": "Describe a noisy UI dashboard and identify overlapping UI state.",
        "required_mentions": [
            {"id": "sidebar", "aliases": ["sidebar", "navigation"], "region": "left", "importance": 2},
            {"id": "browser_card", "aliases": ["Browser", "browser card"], "region": "upper", "importance": 2},
            {"id": "terminal_card", "aliases": ["Terminal", "terminal card"], "region": "upper", "importance": 3},
            {"id": "notes_card", "aliases": ["Notes", "notes card"], "region": "upper right", "importance": 2},
            {"id": "review_modal", "aliases": ["Review modal", "modal"], "region": "center", "importance": 3},
            {"id": "warning_toast", "aliases": ["Warning", "stale screenshot", "toast"], "region": "upper right", "importance": 2},
            {"id": "task_table", "aliases": ["Task table", "ERR-42", "table"], "region": "right", "importance": 2}
        ],
        "forbidden_claims": ["success banner", "all checks passed", "four surface cards"],
        "relationship_expectations": [
            {"subject": "review_modal", "relation": "overlaps", "object": "task_table"},
            {"subject": "warning_toast", "relation": "upper right", "object": "dashboard"}
        ],
        "visible_text": [{"text": "ERR-42", "strict": True}, {"text": "Terminal card needs focus", "strict": False}],
        "ambiguous_items": []
    })


def warehouse_shelf() -> None:
    img = Image.new("RGB", (1000, 640), "#d9d2c5")
    d = ImageDraw.Draw(img)
    for y in [145, 320, 500]:
        d.rectangle((50, y, 950, y + 18), fill="#71563b")
    boxes = [
        (80, 55, 230, 145, "A-12", "#b98b5d"), (260, 65, 420, 145, "B-07", "#d2a56f"),
        (455, 45, 630, 145, "C-19", "#c48c60"), (700, 70, 900, 145, "FRAGILE", "#e6c089"),
        (110, 225, 300, 320, "BIN-3", "#8fb6d8"), (335, 205, 555, 320, "QR-55", "#9bcf8c"),
        (610, 230, 775, 320, "D-02", "#d8a0a0"), (790, 210, 935, 320, "E-09", "#b8b1de"),
        (75, 405, 250, 500, "TOOLS", "#a8d7d1"), (295, 390, 500, 500, "PARTS", "#e0d08f"),
        (570, 405, 770, 500, "A-12", "#b98b5d"), (800, 390, 930, 500, "?", "#777777"),
    ]
    for x1, y1, x2, y2, label, fill in boxes:
        d.rectangle((x1, y1, x2, y2), fill=fill, outline="#4b3a2a", width=3)
        draw_label(d, (x1 + 18, y1 + 28), label, size=22)
    d.rectangle((510, 185, 660, 345), fill="#444", outline="#111")
    draw_label(d, (520, 250), "occluding", fill="#eee", size=18)
    img.save(OUT / "warehouse-shelf.png")
    save_manifest("warehouse-shelf", {
        "image_path": "fixtures/vision/chaotic/warehouse-shelf.png",
        "description_goal": "Describe shelf contents, labels, and occlusion patterns.",
        "required_mentions": [
            {"id": "top_shelf_boxes", "aliases": ["top shelf", "A-12", "B-07", "C-19", "FRAGILE"], "region": "upper", "importance": 3},
            {"id": "blue_bin_3", "aliases": ["BIN-3", "blue bin"], "region": "middle left", "importance": 2},
            {"id": "green_qr_55", "aliases": ["QR-55", "green box"], "region": "middle", "importance": 2},
            {"id": "occluding_dark_box", "aliases": ["occluding", "dark box", "black box"], "region": "center", "importance": 3},
            {"id": "tools_box", "aliases": ["TOOLS", "tools box"], "region": "lower left", "importance": 1},
            {"id": "unknown_gray_box", "aliases": ["gray box", "?"], "region": "lower right", "importance": 1}
        ],
        "forbidden_claims": ["empty shelf", "person", "barcode scanner"],
        "relationship_expectations": [{"subject": "occluding_dark_box", "relation": "occluding", "object": "QR-55"}],
        "visible_text": [{"text": "FRAGILE", "strict": True}, {"text": "BIN-3", "strict": True}, {"text": "QR-55", "strict": True}],
        "ambiguous_items": ["unknown gray box"]
    })


def map_board() -> None:
    img = Image.new("RGB", (1000, 700), "#f7f3e8")
    d = ImageDraw.Draw(img)
    d.rectangle((55, 55, 945, 645), fill="#fffaf0", outline="#5f5240", width=5)
    nodes = {
        "Alpha": (170, 150, "#d94b4b"), "Beta": (430, 120, "#4b84d9"), "Gamma": (760, 180, "#4bad64"),
        "Delta": (260, 430, "#d9b34b"), "Omega": (700, 480, "#8b55c7"),
    }
    for a, b in [("Alpha", "Beta"), ("Beta", "Gamma"), ("Alpha", "Delta"), ("Delta", "Omega"), ("Gamma", "Omega"), ("Beta", "Omega")]:
        x1, y1, _ = nodes[a]
        x2, y2, _ = nodes[b]
        d.line((x1, y1, x2, y2), fill="#333", width=4)
    d.line((430, 120, 700, 480), fill="#d14", width=8)
    for label, (x, y, color) in nodes.items():
        d.ellipse((x - 38, y - 38, x + 38, y + 38), fill=color, outline="#222", width=4)
        draw_label(d, (x - 34, y + 48), label, size=22)
    d.rectangle((95, 560, 330, 620), fill="#ffe680", outline="#8d6c00", width=3)
    draw_label(d, (120, 578), "ROUTE B BLOCKED", size=19)
    d.polygon([(895, 100), (925, 160), (865, 160)], fill="#d33", outline="#811")
    draw_label(d, (850, 170), "alert", size=18)
    img.save(OUT / "map-board.png")
    save_manifest("map-board", {
        "image_path": "fixtures/vision/chaotic/map-board.png",
        "description_goal": "Describe a route board with nodes, crossings, alert markers, and text.",
        "required_mentions": [
            {"id": "alpha_node", "aliases": ["Alpha"], "region": "upper left", "importance": 2},
            {"id": "beta_node", "aliases": ["Beta"], "region": "upper center", "importance": 2},
            {"id": "gamma_node", "aliases": ["Gamma"], "region": "upper right", "importance": 2},
            {"id": "delta_node", "aliases": ["Delta"], "region": "lower left", "importance": 2},
            {"id": "omega_node", "aliases": ["Omega"], "region": "lower right", "importance": 2},
            {"id": "route_b_blocked", "aliases": ["ROUTE B BLOCKED", "blocked"], "region": "lower left", "importance": 3},
            {"id": "alert_triangle", "aliases": ["alert", "red triangle"], "region": "upper right", "importance": 1}
        ],
        "forbidden_claims": ["map is blank", "three nodes", "success"],
        "relationship_expectations": [
            {"subject": "Beta", "relation": "line", "object": "Omega"},
            {"subject": "ROUTE B BLOCKED", "relation": "lower left", "object": "board"}
        ],
        "visible_text": [{"text": "ROUTE B BLOCKED", "strict": True}, {"text": "Omega", "strict": True}],
        "ambiguous_items": []
    })


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    chaotic_desk()
    busy_dashboard()
    warehouse_shelf()
    map_board()
    print(f"wrote chaotic fixtures to {OUT}")


if __name__ == "__main__":
    main()
