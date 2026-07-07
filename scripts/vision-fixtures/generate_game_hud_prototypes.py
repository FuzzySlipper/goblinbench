#!/usr/bin/env python3
"""Generate prototype game-HUD chaos fixtures for visual-inspect calibration.

These are deliberately synthetic PIL drawings: the goal is to see whether a
cheap deterministic style can create enough central visual noise while keeping
border UI facts exact and manifestable.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "fixtures" / "vision" / "chaotic" / "prototypes"


def font(size: int = 18, bold: bool = False):
    names = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def save_manifest(name: str, manifest: dict) -> None:
    path = OUT / f"{name}.manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def label(d: ImageDraw.ImageDraw, xy, text: str, fill=(235, 238, 245), size=18, bold=False, anchor=None):
    d.text(xy, text, fill=fill, font=font(size, bold), anchor=anchor)


def panel(d: ImageDraw.ImageDraw, box, fill=(18, 22, 34, 215), outline=(150, 170, 210), width=2, radius=10):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def bar(d: ImageDraw.ImageDraw, box, frac: float, fill, back=(55, 55, 65), outline=(230, 230, 240), text: str | None = None):
    x1, y1, x2, y2 = box
    d.rounded_rectangle(box, radius=7, fill=back, outline=outline, width=2)
    w = int((x2 - x1 - 4) * max(0, min(1, frac)))
    d.rounded_rectangle((x1 + 2, y1 + 2, x1 + 2 + w, y2 - 2), radius=5, fill=fill)
    if text:
        label(d, ((x1 + x2) // 2, (y1 + y2) // 2), text, fill=(255, 255, 255), size=17, bold=True, anchor="mm")


def draw_center_battle(d: ImageDraw.ImageDraw, rng: random.Random, theme: str):
    # Noisy background hills/lava/arena chunks.
    if theme == "lava":
        bg = [(50, 20, 18), (88, 28, 14), (120, 45, 18), (35, 25, 30)]
        lava = (245, 78, 16)
        smoke = (80, 72, 70)
    else:
        bg = [(12, 28, 54), (28, 48, 83), (55, 26, 89), (18, 73, 86)]
        lava = (60, 220, 245)
        smoke = (130, 130, 165)
    for _ in range(130):
        x = rng.randint(170, 1110)
        y = rng.randint(90, 635)
        r = rng.randint(8, 60)
        color = rng.choice(bg)
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(min(255, max(0, c + rng.randint(-20, 20))) for c in color))
    # Terrain ridges.
    for i in range(18):
        pts = []
        base_y = rng.randint(245, 610)
        for x in range(135, 1160, 80):
            pts.append((x, base_y + rng.randint(-45, 45)))
        pts.append((1160, 720)); pts.append((135, 720))
        d.polygon(pts, fill=bg[i % len(bg)], outline=(20, 20, 25))
    # Energy beams and particle spam.
    for _ in range(80):
        x1 = rng.randint(210, 1030); y1 = rng.randint(130, 580)
        x2 = x1 + rng.randint(-180, 180); y2 = y1 + rng.randint(-120, 120)
        col = rng.choice([(255, 210, 60), (255, 80, 50), (80, 220, 255), (190, 90, 255), (130, 255, 120)])
        d.line((x1, y1, x2, y2), fill=col, width=rng.randint(1, 5))
    for _ in range(260):
        x = rng.randint(170, 1110); y = rng.randint(105, 625)
        r = rng.randint(1, 7)
        col = rng.choice([(255, 255, 120), (255, 90, 45), (90, 220, 255), (220, 220, 255), (120, 255, 160), smoke])
        d.ellipse((x-r, y-r, x+r, y+r), fill=col)
    # Tiny enemies / skeleton decoys / background nonsense.
    for i in range(34):
        x = rng.randint(190, 1080); y = rng.randint(145, 600)
        scale = rng.randint(6, 16)
        bone = (225, 220, 200)
        d.ellipse((x-scale//2, y-scale*2, x+scale//2, y-scale), outline=bone, width=2)
        d.line((x, y-scale, x, y+scale), fill=bone, width=2)
        d.line((x-scale, y, x+scale, y), fill=bone, width=2)
        d.line((x, y+scale, x-scale, y+scale*2), fill=bone, width=2)
        d.line((x, y+scale, x+scale, y+scale*2), fill=bone, width=2)
        if i % 5 == 0:
            label(d, (x, y-scale*3), rng.choice(["12", "-4", "MISS", "+8", "CRIT"]), fill=(255, 230, 90), size=12, bold=True, anchor="mm")
    # Big central visual attractor that should mostly be ignored.
    cx, cy = 655, 360
    for a in range(0, 360, 14):
        rad = math.radians(a)
        d.line((cx, cy, cx + math.cos(rad)*220, cy + math.sin(rad)*150), fill=(255, 110, 45) if theme == "lava" else (85, 220, 255), width=3)
    d.ellipse((cx-95, cy-70, cx+95, cy+70), fill=(30, 20, 40), outline=(255, 120, 40) if theme == "lava" else (80, 240, 255), width=5)
    label(d, (cx, cy-12), "CHAOS BOSS", fill=(255, 240, 160), size=24, bold=True, anchor="mm")
    label(d, (cx, cy+20), "ignore center mess", fill=(210, 210, 220), size=15, anchor="mm")


def game_hud_low_health() -> None:
    rng = random.Random(342501)
    img = Image.new("RGB", (1280, 720), (25, 25, 30))
    d = ImageDraw.Draw(img, "RGBA")
    draw_center_battle(d, rng, "lava")
    # Slight blur/noise in the center only, then redraw crisp UI over it.
    center = img.crop((130, 80, 1160, 650)).filter(ImageFilter.GaussianBlur(0.35))
    img.paste(center, (130, 80))
    d = ImageDraw.Draw(img, "RGBA")

    # HUD border facts.
    panel(d, (24, 22, 390, 142), fill=(15, 18, 28, 230), outline=(210, 80, 80), width=3)
    label(d, (42, 35), "PLAYER: PATCH", size=19, bold=True)
    bar(d, (42, 66, 350, 92), 0.23, fill=(220, 35, 35), text="HEALTH 23%")
    bar(d, (42, 101, 350, 125), 0.61, fill=(45, 115, 235), text="MANA 61%")
    label(d, (42, 132), "STATUS: POISONED", fill=(145, 255, 135), size=15, bold=True)

    panel(d, (453, 16, 827, 72), fill=(70, 15, 18, 230), outline=(255, 80, 70), width=3)
    label(d, (640, 44), "LOW HEALTH — USE POTION", fill=(255, 245, 210), size=24, bold=True, anchor="mm")

    panel(d, (1010, 24, 1256, 220), fill=(14, 20, 31, 226), outline=(95, 190, 255), width=3)
    label(d, (1030, 42), "MINIMAP", size=17, bold=True)
    d.rectangle((1030, 68, 1235, 196), fill=(22, 45, 58), outline=(130, 210, 240), width=2)
    for _ in range(45):
        x = rng.randint(1038, 1228); y = rng.randint(76, 188)
        d.rectangle((x, y, x+2, y+2), fill=rng.choice([(80, 180, 80), (180, 80, 80), (80, 140, 220), (220, 220, 120)]))
    d.polygon([(1135, 118), (1150, 145), (1120, 145)], fill=(255, 255, 255), outline=(0,0,0))
    label(d, (1040, 202), "OBJECTIVE: REACH EXIT", fill=(255, 230, 120), size=14, bold=True)

    panel(d, (402, 610, 878, 704), fill=(15, 17, 25, 230), outline=(210, 210, 230), width=3)
    label(d, (424, 624), "ABILITIES", size=16, bold=True)
    icons = [(450, 655, "Q", "READY", (60, 180, 80)), (535, 655, "W", "04s", (190, 80, 80)), (620, 655, "E", "READY", (60, 180, 80)), (705, 655, "R", "31s", (190, 80, 80)), (790, 655, "F", "2", (170, 135, 50))]
    for x, y, key, txt, color in icons:
        d.rounded_rectangle((x, y, x+58, y+38), radius=8, fill=color, outline=(235,235,245), width=2)
        label(d, (x+13, y+7), key, size=18, bold=True)
        label(d, (x+30, y+49), txt, size=13, bold=True, anchor="mm")

    panel(d, (1018, 610, 1254, 699), fill=(18, 17, 24, 230), outline=(230, 190, 90), width=3)
    label(d, (1036, 628), "AMMO", size=16, bold=True)
    label(d, (1118, 668), "7 / 30", fill=(255, 235, 160), size=38, bold=True, anchor="mm")

    panel(d, (24, 530, 304, 698), fill=(15, 20, 25, 220), outline=(160, 215, 120), width=2)
    label(d, (42, 548), "QUEST TRACKER", size=16, bold=True)
    label(d, (42, 580), "✓ Find the old key", fill=(190, 255, 190), size=15)
    label(d, (42, 608), "• Escape the crypt", fill=(255, 238, 170), size=15)
    label(d, (42, 636), "• Optional: ignore bones", fill=(200, 205, 215), size=14)

    img.save(OUT / "game-hud-low-health-chaos.png")
    save_manifest("game-hud-low-health-chaos", {
        "image_path": "fixtures/vision/chaotic/prototypes/game-hud-low-health-chaos.png",
        "description_goal": "Inspect border HUD state while ignoring chaotic center combat art.",
        "required_mentions": [
            {"id": "health_23", "aliases": ["HEALTH 23%", "health 23", "23% health"], "region": "upper left", "importance": 4},
            {"id": "low_health_warning", "aliases": ["LOW HEALTH", "USE POTION"], "region": "upper center", "importance": 4},
            {"id": "mana_61", "aliases": ["MANA 61%", "mana 61"], "region": "upper left", "importance": 2},
            {"id": "poisoned", "aliases": ["POISONED", "status poisoned"], "region": "upper left", "importance": 2},
            {"id": "objective_exit", "aliases": ["OBJECTIVE: REACH EXIT", "reach exit"], "region": "upper right", "importance": 3},
            {"id": "ammo_7_30", "aliases": ["7 / 30", "ammo 7"], "region": "lower right", "importance": 3},
            {"id": "quest_tracker", "aliases": ["QUEST TRACKER", "Escape the crypt"], "region": "lower left", "importance": 2}
        ],
        "forbidden_claims": ["full health", "health is 100", "no warning", "ammo 30 / 30"],
        "distractor_mentions": ["CHAOS BOSS", "skeleton", "hill", "bones", "particles"],
        "relationship_expectations": [
            {"subject": "LOW HEALTH", "relation": "upper center", "object": "HUD"},
            {"subject": "ammo", "relation": "lower right", "object": "HUD"}
        ],
        "visible_text": [{"text": "HEALTH 23%", "strict": True}, {"text": "LOW HEALTH", "strict": False}, {"text": "7 / 30", "strict": True}],
        "ambiguous_items": ["tiny skeletons in center background"]
    })


def game_hud_overheated_mech() -> None:
    rng = random.Random(342502)
    img = Image.new("RGB", (1280, 720), (12, 18, 30))
    d = ImageDraw.Draw(img, "RGBA")
    draw_center_battle(d, rng, "neon")
    # Add central fake popups/nameplates to distract from border UI.
    for i in range(22):
        x = rng.randint(250, 1030); y = rng.randint(140, 575)
        d.rounded_rectangle((x, y, x+rng.randint(55, 130), y+22), radius=4, fill=(20, 20, 28, 190), outline=(240, 90, 120), width=1)
        label(d, (x+5, y+4), rng.choice(["SKELETON", "DRONE", "LOOT?", "999", "TARGET", "???"]), fill=(255, 210, 220), size=12, bold=True)

    # Crisp sci-fi HUD.
    panel(d, (20, 18, 392, 172), fill=(8, 17, 28, 232), outline=(70, 230, 245), width=3)
    label(d, (40, 36), "MECH UNIT: K8-GOBLIN", fill=(170, 245, 255), size=18, bold=True)
    bar(d, (40, 68, 355, 94), 0.74, fill=(60, 210, 105), text="ARMOR 74%")
    bar(d, (40, 105, 355, 131), 0.91, fill=(80, 180, 255), text="SHIELD 91%")
    bar(d, (40, 142, 355, 162), 0.88, fill=(255, 115, 35), text="HEAT 88%")

    panel(d, (444, 16, 836, 82), fill=(80, 35, 5, 235), outline=(255, 170, 60), width=3)
    label(d, (640, 48), "OVERHEAT WARNING", fill=(255, 245, 210), size=26, bold=True, anchor="mm")

    panel(d, (978, 18, 1260, 260), fill=(8, 16, 28, 230), outline=(120, 220, 255), width=3)
    label(d, (1000, 38), "TACTICAL MAP", fill=(190, 240, 255), size=17, bold=True)
    d.rectangle((1000, 66, 1238, 218), fill=(5, 36, 48), outline=(90, 190, 220), width=2)
    for gx in range(1008, 1238, 24):
        d.line((gx, 66, gx, 218), fill=(30, 80, 90), width=1)
    for gy in range(74, 218, 24):
        d.line((1000, gy, 1238, gy), fill=(30, 80, 90), width=1)
    d.ellipse((1116, 132, 1134, 150), fill=(255,255,255), outline=(0,0,0))
    d.rectangle((1190, 84, 1225, 116), fill=(255, 80, 70), outline=(255,220,220))
    label(d, (1008, 230), "ZONE: BETA-9", fill=(255, 235, 140), size=15, bold=True)

    panel(d, (420, 598, 860, 704), fill=(8, 12, 24, 235), outline=(150, 180, 255), width=3)
    label(d, (440, 615), "WEAPONS", fill=(200, 220, 255), size=16, bold=True)
    weapons = [(452, 650, "LASER", "12s", (170, 65, 65)), (555, 650, "MISSILE", "READY", (55, 150, 70)), (672, 650, "DASH", "READY", (55, 130, 180)), (770, 650, "ULT", "LOCKED", (60, 60, 70))]
    for x,y,name,state,color in weapons:
        d.rounded_rectangle((x,y,x+80,y+36), radius=7, fill=color, outline=(230,230,250), width=2)
        label(d, (x+40,y+8), name, size=12, bold=True, anchor="mm")
        label(d, (x+40,y+47), state, size=12, bold=True, anchor="mm")

    panel(d, (22, 520, 342, 700), fill=(9, 18, 23, 225), outline=(140, 235, 180), width=2)
    label(d, (42, 540), "COMMS", fill=(180, 245, 210), size=16, bold=True)
    label(d, (42, 572), "ALLY: fall back", fill=(210, 230, 245), size=15)
    label(d, (42, 602), "SYS: coolant low", fill=(255, 210, 120), size=15, bold=True)
    label(d, (42, 632), "PING: 142ms", fill=(255, 170, 130), size=15, bold=True)
    label(d, (42, 662), "REPAIR KITS: 1", fill=(210, 255, 210), size=15)

    panel(d, (1010, 604, 1252, 700), fill=(26, 10, 16, 232), outline=(255, 120, 150), width=3)
    label(d, (1030, 624), "CORE", fill=(255, 210, 220), size=16, bold=True)
    label(d, (1130, 666), "CRITICAL", fill=(255, 90, 90), size=34, bold=True, anchor="mm")

    img.save(OUT / "game-hud-overheat-chaos.png")
    save_manifest("game-hud-overheat-chaos", {
        "image_path": "fixtures/vision/chaotic/prototypes/game-hud-overheat-chaos.png",
        "description_goal": "Inspect mech HUD status around borders; ignore noisy combat/nameplate center.",
        "required_mentions": [
            {"id": "armor_74", "aliases": ["ARMOR 74%", "armor 74"], "region": "upper left", "importance": 3},
            {"id": "shield_91", "aliases": ["SHIELD 91%", "shield 91"], "region": "upper left", "importance": 3},
            {"id": "heat_88", "aliases": ["HEAT 88%", "heat 88"], "region": "upper left", "importance": 4},
            {"id": "overheat_warning", "aliases": ["OVERHEAT WARNING", "overheat"], "region": "upper center", "importance": 4},
            {"id": "zone_beta_9", "aliases": ["ZONE: BETA-9", "Beta-9"], "region": "upper right", "importance": 2},
            {"id": "coolant_low", "aliases": ["coolant low", "SYS: coolant low"], "region": "lower left", "importance": 3},
            {"id": "ping_142", "aliases": ["PING: 142ms", "142ms"], "region": "lower left", "importance": 2},
            {"id": "core_critical", "aliases": ["CORE", "CRITICAL"], "region": "lower right", "importance": 4}
        ],
        "forbidden_claims": ["heat is low", "shield down", "zone alpha", "core stable"],
        "distractor_mentions": ["SKELETON", "DRONE", "CHAOS BOSS", "LOOT", "TARGET"],
        "relationship_expectations": [
            {"subject": "OVERHEAT WARNING", "relation": "upper center", "object": "HUD"},
            {"subject": "CORE", "relation": "lower right", "object": "CRITICAL"}
        ],
        "visible_text": [{"text": "OVERHEAT WARNING", "strict": True}, {"text": "HEAT 88%", "strict": True}, {"text": "CRITICAL", "strict": True}],
        "ambiguous_items": ["many central combat nameplates"]
    })


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    game_hud_low_health()
    game_hud_overheated_mech()
    print(f"wrote prototypes to {OUT}")
    for p in sorted(OUT.glob("game-hud-*.png")):
        print(p, p.stat().st_size)


if __name__ == "__main__":
    main()
