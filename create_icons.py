"""
Generator ikon pre Alpha Edge Scanner a Habit Guardian.
Spusti raz: python create_icons.py
"""
from PIL import Image, ImageDraw, ImageFont
import math
import os

def create_alpha_edge_icon(path, size=256):
    """Ikona pre Alpha Edge Scanner - tmave pozadie, zeleny graf s sipkou hore"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Kruhove pozadie - tmava modra/navy
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill="#0D1B2A")
    # Tenky okraj
    draw.ellipse([margin, margin, size - margin, size - margin], outline="#1B3A5C", width=3)

    cx, cy = size // 2, size // 2
    r = size // 2 - margin

    # Mriezka (jemna)
    grid_color = (40, 70, 100, 80)
    for i in range(5):
        y = int(cy - r * 0.6 + i * r * 0.3)
        draw.line([(cx - r * 0.7, y), (cx + r * 0.7, y)], fill=grid_color, width=1)

    # Stlpcovy graf (candlestick style)
    bar_data = [0.3, 0.45, 0.35, 0.55, 0.5, 0.7, 0.85]
    bar_w = int(r * 0.12)
    start_x = int(cx - r * 0.6)
    spacing = int(r * 1.2 / len(bar_data))
    base_y = int(cy + r * 0.45)

    for i, val in enumerate(bar_data):
        x = start_x + i * spacing
        h = int(val * r * 1.0)
        # Zeleny gradient - tmavsie dole, svetlejsie hore
        green_dark = (0, 150, 80)
        green_light = (0, 220, 120)
        t = val
        color = tuple(int(green_dark[j] + (green_light[j] - green_dark[j]) * t) for j in range(3))
        draw.rounded_rectangle([x, base_y - h, x + bar_w, base_y], radius=2, fill=color)

    # Sipka hore (biela, vyrazna)
    arrow_cx = int(cx + r * 0.35)
    arrow_top = int(cy - r * 0.55)
    arrow_bot = int(cy + r * 0.1)
    arrow_w = int(r * 0.08)
    # Telo sipky
    draw.rectangle([arrow_cx - arrow_w, arrow_top + int(r * 0.18), arrow_cx + arrow_w, arrow_bot], fill="white")
    # Hrot sipky
    draw.polygon([
        (arrow_cx, arrow_top),
        (arrow_cx - int(r * 0.18), arrow_top + int(r * 0.22)),
        (arrow_cx + int(r * 0.18), arrow_top + int(r * 0.22)),
    ], fill="white")

    # "$" symbol vlavo hore
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.14))
    except:
        font = ImageFont.load_default()
    draw.text((int(cx - r * 0.55), int(cy - r * 0.65)), "$", fill=(0, 200, 100), font=font)

    # Uloz
    img_256 = img.resize((256, 256), Image.LANCZOS)
    img_64 = img.resize((64, 64), Image.LANCZOS)
    img_48 = img.resize((48, 48), Image.LANCZOS)
    img_32 = img.resize((32, 32), Image.LANCZOS)
    img_16 = img.resize((16, 16), Image.LANCZOS)

    ico_path = os.path.splitext(path)[0] + ".ico"
    png_path = os.path.splitext(path)[0] + ".png"
    img_256.save(png_path, "PNG")
    img_256.save(ico_path, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Alpha Edge ikona: {ico_path}, {png_path}")


def create_habit_icon(path, size=256):
    """Ikona pre Habit Guardian - stit s checkmarkom, oranzovo-zlata"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    margin = 4

    # Kruhove pozadie - tmava oranzova/hneda
    draw.ellipse([margin, margin, size - margin, size - margin], fill="#1A1A2E")
    draw.ellipse([margin, margin, size - margin, size - margin], outline="#E65100", width=3)

    r = size // 2 - margin

    # Stit (shield shape)
    shield_top = int(cy - r * 0.55)
    shield_bot = int(cy + r * 0.55)
    shield_w = int(r * 0.55)
    shield_mid = int(cy + r * 0.05)

    # Shield body - oranzovo-zlata
    shield_points = [
        (cx, shield_top),                          # top center
        (cx + shield_w, shield_top + int(r * 0.15)), # top right
        (cx + shield_w, shield_mid),                # mid right
        (cx + int(shield_w * 0.6), int(shield_mid + (shield_bot - shield_mid) * 0.5)),
        (cx, shield_bot),                           # bottom point
        (cx - int(shield_w * 0.6), int(shield_mid + (shield_bot - shield_mid) * 0.5)),
        (cx - shield_w, shield_mid),                # mid left
        (cx - shield_w, shield_top + int(r * 0.15)), # top left
    ]
    draw.polygon(shield_points, fill="#E65100")

    # Vnutorny stit (tmavsi)
    inner_scale = 0.78
    inner_points = []
    for px, py in shield_points:
        ix = cx + (px - cx) * inner_scale
        iy = (shield_top + (shield_bot - shield_top) * 0.08) + (py - shield_top) * inner_scale
        inner_points.append((ix, iy))
    draw.polygon(inner_points, fill="#BF360C")

    # Checkmark (biely, vyrazny)
    check_cx = cx
    check_cy = int(cy + r * 0.02)
    check_size = int(r * 0.3)

    check_points = [
        (check_cx - check_size, check_cy),
        (check_cx - int(check_size * 0.3), check_cy + int(check_size * 0.7)),
        (check_cx + check_size, check_cy - int(check_size * 0.5)),
    ]
    draw.line(check_points, fill="white", width=max(int(r * 0.09), 3), joint="curve")

    # Uloz
    img_256 = img.resize((256, 256), Image.LANCZOS)
    img_64 = img.resize((64, 64), Image.LANCZOS)
    img_48 = img.resize((48, 48), Image.LANCZOS)
    img_32 = img.resize((32, 32), Image.LANCZOS)
    img_16 = img.resize((16, 16), Image.LANCZOS)

    ico_path = os.path.splitext(path)[0] + ".ico"
    png_path = os.path.splitext(path)[0] + ".png"
    img_256.save(png_path, "PNG")
    img_256.save(ico_path, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Habit Guardian ikona: {ico_path}, {png_path}")


if __name__ == "__main__":
    create_alpha_edge_icon(os.path.join("AI investovanie", "icon"))
    create_habit_icon(os.path.join("habits", "icon"))
    print("\nHotovo! Ikony vytvorene.")
