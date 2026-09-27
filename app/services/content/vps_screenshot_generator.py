"""Windows 10 desktop previews with a fresh icon layout for every RDP post.

The original Windows 10 wallpaper and taskbar are kept authentic, while the
shortcut set, positions, and wallpaper variant are regenerated for every new
image. This keeps previews varied without showing live server credentials.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from random import SystemRandom
from typing import Sequence
from zoneinfo import ZoneInfo

import cairosvg
from PIL import Image, ImageDraw, ImageFont

SCREENSHOT_WIDTH = 1673
SCREENSHOT_HEIGHT = 940
TEHRAN = ZoneInfo("Asia/Tehran")

_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets"
_ICON_ROOT = _ASSET_ROOT / "vps_desktop" / "icons"
_WALLPAPER_ROOT = _ASSET_ROOT / "vps_wallpapers"
_WALLPAPERS = (
    "windows10-original-1.png",
    "windows10-original-2.png",
    "windows10-original-3.png",
)

_CLOCK_BOX = (1580, 878, SCREENSHOT_WIDTH - 1, SCREENSHOT_HEIGHT - 1)

# These are the Windows 10-style desktop and utility icons used in the supplied
# references. Keep the catalog at ten so every post can show 2–10 unique icons.
_ICON_LABELS = {
    "chrome.svg": "Google Chrome",
    "control-panel.svg": "Control Panel",
    "edge.svg": "Microsoft Edge",
    "file-explorer.svg": "File Explorer",
    "notepad.svg": "Notepad",
    "powershell.svg": "PowerShell",
    "recycle-bin.svg": "Recycle Bin",
    "remote-desktop.svg": "Remote Desktop",
    "task-manager.svg": "Task Manager",
    "this-pc.svg": "This PC",
}
_ICON_FILES = tuple(sorted(_ICON_LABELS))
_ICON_SLOTS = tuple(
    (28 + column * 108, 22 + row * 104)
    for row in range(4)
    for column in range(5)
)
_RANDOM = SystemRandom()
_SCENE_LOCK = asyncio.Lock()


def _font(size: int):
    candidates = (
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _clock_parts(now: datetime) -> tuple[str, str]:
    """Match the en-US Windows 10 tray format without server-local timezone drift."""
    hour = now.hour % 12 or 12
    meridiem = "AM" if now.hour < 12 else "PM"
    return f"{hour}:{now.minute:02d} {meridiem}", f"{now.month}/{now.day}/{now.year}"


@lru_cache(maxsize=32)
def _rasterize_svg(path: str, width: int, height: int) -> bytes:
    return cairosvg.svg2png(
        url=path,
        output_width=width,
        output_height=height,
    )


@lru_cache(maxsize=8)
def _load_wallpaper(path: str) -> bytes:
    return Path(path).read_bytes()


def _validate_assets() -> None:
    missing_wallpapers = [
        name for name in _WALLPAPERS if not (_WALLPAPER_ROOT / name).exists()
    ]
    if missing_wallpapers:
        raise RuntimeError(
            f"Missing original Windows 10 wallpapers: {', '.join(missing_wallpapers)}"
        )
    missing = [name for name in _ICON_FILES if not (_ICON_ROOT / name).exists()]
    if missing:
        raise RuntimeError(f"Missing RDP desktop icons: {', '.join(missing)}")
    if len(_ICON_FILES) != 10:
        raise RuntimeError("RDP desktop icon catalog must contain exactly 10 icons")


def _render_desktop_background() -> Image.Image:
    wallpaper_path = _WALLPAPER_ROOT / _RANDOM.choice(_WALLPAPERS)
    image = Image.open(
        io.BytesIO(_load_wallpaper(str(wallpaper_path)))
    ).convert("RGBA")
    if image.size != (SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT):
        raise RuntimeError(
            f"Original Windows 10 wallpaper must be {SCREENSHOT_WIDTH}x{SCREENSHOT_HEIGHT}, "
            f"got {image.width}x{image.height}"
        )
    return image


def _draw_icon_layout(image: Image.Image) -> None:
    """Place 2–10 unique Windows 10 shortcuts in a new layout."""
    icon_count = _RANDOM.randint(2, 10)
    chosen_icons = _RANDOM.sample(_ICON_FILES, k=icon_count)
    chosen_slots = _RANDOM.sample(_ICON_SLOTS, k=icon_count)
    draw = ImageDraw.Draw(image)
    label_font = _font(10)

    for filename, (slot_x, slot_y) in zip(chosen_icons, chosen_slots):
        icon_png = _rasterize_svg(str(_ICON_ROOT / filename), 58, 58)
        with Image.open(io.BytesIO(icon_png)) as source:
            icon = source.convert("RGBA")
        icon_x = slot_x + 22
        image.alpha_composite(icon, dest=(icon_x, slot_y))

        label = _ICON_LABELS[filename]
        center_x = slot_x + 51
        label_y = slot_y + 61
        # Windows desktop labels use a dark outline so they remain readable
        # over both the bright and dark parts of the wallpaper.
        draw.text(
            (center_x, label_y),
            label,
            font=label_font,
            fill=(245, 248, 252, 255),
            anchor="ma",
            stroke_width=2,
            stroke_fill=(8, 16, 30, 220),
        )


def _paint_taskbar_background(draw: ImageDraw.ImageDraw, image: Image.Image) -> None:
    """Cover the old clock using the adjacent taskbar gradient, without a box."""
    left, top, right, bottom = _CLOCK_BOX
    sample_x = left - 4
    for y in range(top, bottom + 1):
        color = image.getpixel((sample_x, y))
        draw.line((left, y, right, y), fill=color)


def _render_fixed_template(
    icon_files: Sequence[str] | None = None,
    wallpaper_name: str | None = None,
) -> bytes:
    _validate_assets()
    if wallpaper_name and wallpaper_name in _WALLPAPERS:
        wallpaper_path = _WALLPAPER_ROOT / wallpaper_name
        image = Image.open(io.BytesIO(_load_wallpaper(str(wallpaper_path)))).convert("RGBA")
    else:
        image = _render_desktop_background()

    if icon_files:
        selected_icons = tuple(icon_files)
        if len(selected_icons) < 2 or len(selected_icons) > 10:
            raise ValueError("Desktop image requires between 2 and 10 icons")
        if len(set(selected_icons)) != len(selected_icons):
            raise ValueError("Desktop image icons must be unique")
        unknown_icons = set(selected_icons) - set(_ICON_FILES)
        if unknown_icons:
            raise ValueError(f"Unknown desktop icons: {', '.join(sorted(unknown_icons))}")
        _draw_icon_layout_with_selection(image, selected_icons)
    else:
        _draw_icon_layout(image)

    now = datetime.now(TEHRAN)
    clock, date = _clock_parts(now)
    draw = ImageDraw.Draw(image)
    _paint_taskbar_background(draw, image)

    right = SCREENSHOT_WIDTH - 10
    draw.text(
        (right, 883),
        clock,
        font=_font(17),
        fill=(238, 242, 247),
        anchor="ra",
    )
    draw.text(
        (right, 909),
        date,
        font=_font(16),
        fill=(238, 242, 247),
        anchor="ra",
    )

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_icon_layout_with_selection(
    image: Image.Image,
    selected_icons: Sequence[str],
) -> None:
    """Place a validated, model-selected set of unique shortcuts."""
    draw = ImageDraw.Draw(image)
    label_font = _font(10)
    chosen_slots = _RANDOM.sample(_ICON_SLOTS, k=len(selected_icons))

    for filename, (slot_x, slot_y) in zip(selected_icons, chosen_slots):
        icon_png = _rasterize_svg(str(_ICON_ROOT / filename), 58, 58)
        with Image.open(io.BytesIO(icon_png)) as source:
            icon = source.convert("RGBA")
        icon_x = slot_x + 22
        image.alpha_composite(icon, dest=(icon_x, slot_y))

        label = _ICON_LABELS[filename]
        center_x = slot_x + 51
        label_y = slot_y + 61
        draw.text(
            (center_x, label_y),
            label,
            font=label_font,
            fill=(245, 248, 252, 255),
            anchor="ma",
            stroke_width=2,
            stroke_fill=(8, 16, 30, 220),
        )


def available_desktop_icon_files() -> tuple[str, ...]:
    """Return the safe icon filenames that can be selected by the scene planner."""
    return _ICON_FILES


def available_desktop_wallpaper_files() -> tuple[str, ...]:
    """Return the safe wallpaper filenames that can be selected by the scene planner."""
    return _WALLPAPERS


async def generate_vps_desktop_screenshot(
    icon_files: Sequence[str] | None = None,
    wallpaper_name: str | None = None,
) -> bytes:
    """Return a Windows 10 image with either a fresh or planned icon layout."""
    async with _SCENE_LOCK:
        return _render_fixed_template(icon_files, wallpaper_name)


async def close_vps_screenshot_browser() -> None:
    """Compatibility no-op retained for the existing application shutdown hook."""