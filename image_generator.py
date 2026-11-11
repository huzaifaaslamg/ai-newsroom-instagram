"""Create minimal bilingual editorial JPEG cards with Pillow."""
from __future__ import annotations
from pathlib import Path
import textwrap
import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG, INK, MUTED, ACCENT, RULE, WHITE = "#F7F6F2", "#171717", "#77746F", "#D94C3D", "#D9D6CF", "#FFFFFF"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_ARABIC = "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"

def font(size: int, bold: bool = False, rtl: bool = False):
    paths = [FONT_ARABIC, FONT_REG] if rtl else ([FONT_BOLD, FONT_REG] if bold else [FONT_REG])
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()

def draw_rtl(draw, value: str, xy: tuple[int, int], size: int,
             fill: str = INK, anchor: str = "ra"):
    shaped = get_display(arabic_reshaper.reshape(str(value or "")))
    draw.text(xy, shaped, font=font(size, rtl=True), fill=fill, anchor=anchor)

def wrap_text(value: str, max_chars: int) -> list[str]:
    return textwrap.wrap(str(value or ""), width=max_chars, break_long_words=False) or [""]

def draw_block(draw, value: str, x: int, y: int, width: int, size: int,
               color: str = INK, bold: bool = False, rtl: bool = False,
               max_lines: int = 4, gap: int = 10) -> int:
    lines = wrap_text(value, max(12, int(width / (size * 0.56))))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .،,") + "…"
    fnt = font(size, bold=bold, rtl=rtl)
    line_height = int(size * 1.55)
    for line in lines:
        if rtl:
            shaped = get_display(arabic_reshaper.reshape(line))
            draw.text((x + width, y), shaped, font=fnt, fill=color, anchor="ra")
        else:
            draw.text((x, y), line, font=fnt, fill=color)
        y += line_height
    return y + gap

def base_canvas(date_label: str, slot: str, page: str):
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    margin = 78
    draw.text((margin, 58), "THE WORLD BRIEF", font=font(29, True), fill=INK)
    draw.text((W-margin, 68), "GLOBAL NEWS  /  DAILY EDITION",
              font=font(19), fill=MUTED, anchor="ra")
    draw.line((margin, 118, W-margin, 118), fill=INK, width=3)
    draw.text((margin, 1260), f"{date_label}  ·  {slot.upper()} EDITION",
              font=font(19), fill=MUTED)
    draw.text((W-margin, 1260), page, font=font(19, True), fill=ACCENT, anchor="ra")
    return image, draw, margin

def save(image: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92, optimize=True, progressive=True)

def cover(date_label: str, slot: str, count: int, path: Path):
    image, draw, m = base_canvas(date_label, slot, "01 / BRIEF")
    draw.text((m, 235), "TODAY'S TOP STORIES", font=font(31, True), fill=ACCENT)
    draw.text((m, 315), "THE WORLD", font=font(100, True), fill=INK)
    draw.text((m, 435), "BRIEF.", font=font(130, True), fill=INK)
    draw_rtl(draw, "دنیا کی اہم خبریں", (W-m, 605), 66, INK)
    draw.rounded_rectangle((m, 760, W-m, 1000), radius=24, fill=INK)
    draw.text((m+34, 805), f"{count:02d}", font=font(104, True), fill=WHITE)
    draw.text((m+220, 846), "STORIES  ·  ONE CLEAR BRIEF",
              font=font(27, True), fill=WHITE)
    draw_rtl(draw, "خبر، پس منظر اور اہمیت", (m+220, 905), 34, WHITE, anchor="la")
    draw.text((m, 1100), "Swipe for the facts. Sources in caption.",
              font=font(23), fill=MUTED)
    save(image, path)

def story_slide(story: dict, date_label: str, slot: str,
                index: int, total: int, path: Path):
    image, draw, m = base_canvas(date_label, slot, f"{index+1:02d} / {total:02d}")
    draw.rounded_rectangle((m, 160, m+205, 211), radius=17, fill=ACCENT)
    draw.text((m+18, 170), story["category"][:18],
              font=font(20, True), fill=WHITE)
    draw.text((W-m, 176), f"STORY {index:02d}", font=font(20, True),
              fill=MUTED, anchor="ra")
    y = draw_block(draw, story["headline_en"], m, 260, W-2*m, 50,
                   bold=True, max_lines=2, gap=18)
    draw.line((m, y, W-m, y), fill=RULE, width=2)
    y += 28
    y = draw_block(draw, story["headline_ur"], m, y, W-2*m, 41,
                   rtl=True, max_lines=2, gap=12)
    y = draw_block(draw, story["summary_en"], m, y, W-2*m, 25,
                   color="#3E3E3E", max_lines=3, gap=10)
    y = draw_block(draw, story["summary_ur"], m, y, W-2*m, 25,
                   color="#3E3E3E", rtl=True, max_lines=3, gap=8)
    why_y = min(y+8, 1085)
    draw.text((m, why_y), "WHY IT MATTERS / AHAMIYAT",
              font=font(17, True), fill=ACCENT)
    why_text_y = min(why_y+35, 1120)
    next_y = draw_block(draw, story["why_en"], m, why_text_y, W-2*m, 18,
                        color=MUTED, max_lines=1, gap=2)
    draw_block(draw, story["why_ur"], m, next_y, W-2*m, 19,
               color=MUTED, rtl=True, max_lines=1, gap=0)
    domains = ", ".join(sorted({s["domain"] for s in story["sources"]}))
    draw.text((m, 1208), f"REPORTING: {domains[:75]}",
              font=font(15), fill=MUTED)
    save(image, path)

def sources_slide(brief: dict, date_label: str, slot: str,
                  index: int, total: int, path: Path):
    image, draw, m = base_canvas(date_label, slot, f"{index:02d} / {total:02d}")
    draw.text((m, 220), "READ BEYOND THE HEADLINES",
              font=font(42, True), fill=INK)
    draw_rtl(draw, "اصل رپورٹس پڑھیں", (W-m, 310), 45, INK)
    y, seen = 410, set()
    for story in brief["stories"]:
        for source in story["sources"]:
            if source["url"] in seen:
                continue
            seen.add(source["url"])
            draw.text((m, y), source["domain"][:55],
                      font=font(26, True), fill=INK)
            y += 42
            draw_block(draw, source["title"], m, y, W-2*m, 18,
                       color=MUTED, max_lines=2, gap=12)
            y += 62
            if y > 1080:
                break
        if y > 1080:
            break
    draw.text((m, 1140), "Direct article links are in the caption.",
              font=font(21), fill=ACCENT)
    save(image, path)

def single_story(story: dict, date_label: str, slot: str, path: Path):
    image, draw, m = base_canvas(date_label, slot, "FOCUS")
    draw.text((m, 190), "ONE STORY, CLEARLY",
              font=font(30, True), fill=ACCENT)
    y = draw_block(draw, story["headline_en"], m, 290, W-2*m, 63,
                   bold=True, max_lines=4, gap=36)
    draw.line((m, y, W-m, y), fill=RULE, width=3)
    y += 42
    y = draw_block(draw, story["headline_ur"], m, y, W-2*m, 54,
                   rtl=True, max_lines=4, gap=30)
    y = draw_block(draw, story["summary_en"], m, y, W-2*m, 33,
                   color="#383838", max_lines=5, gap=24)
    draw_block(draw, story["summary_ur"], m, y, W-2*m, 33,
               color="#383838", rtl=True, max_lines=5, gap=0)
    draw.text((m, 1160), "CONTEXT + SOURCES IN CAPTION",
              font=font(21, True), fill=ACCENT)
    save(image, path)

def generate_assets(brief: dict, output_dir: str) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stories = brief["stories"]
    if len(stories) < 4:
        raise ValueError("At least four validated stories are required.")
    date_label, slot = brief["date"], brief["slot"]
    carousel = []
    cover_path = out / "carousel_01.jpg"
    cover(date_label, slot, len(stories), cover_path)
    carousel.append(str(cover_path))
    total = len(stories) + 2
    for number, story in enumerate(stories, start=1):
        path = out / f"carousel_{number+1:02d}.jpg"
        story_slide(story, date_label, slot, number, total, path)
        carousel.append(str(path))
    source_path = out / f"carousel_{total:02d}.jpg"
    sources_slide(brief, date_label, slot, total, total, source_path)
    carousel.append(str(source_path))
    single_path = out / "single_headline.jpg"
    single_story(stories[0], date_label, slot, single_path)
    return {
        "carousel": {"files": carousel, "caption": brief["carousel_caption"],
                     "alt_text": "Bilingual global news carousel with headlines and summaries in English and Urdu."},
        "single": {"file": str(single_path), "caption": brief["single_caption"],
                   "alt_text": f"English and Urdu news graphic: {stories[0]['headline_en']}"[:950]},
    }
