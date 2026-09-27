"""Render Windows 10 desktop screenshots from local assets with Pillow.

The renderer intentionally does not call an image-generation service.  It
composes a real wallpaper, transparent application icons, labels, and a
Windows 10-style taskbar locally so every generated image has deterministic
desktop UI instead of AI-rendered lock screens or duplicate taskbars.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime
from pathlib import Path
from random import SystemRandom
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError

from app.core.logging import get_logger

logger = get_logger(__name__)

IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
# The checked-in wallpaper screenshots contain an older captured taskbar from
# y=1013 through the bottom edge. Cover that whole band before drawing the
# final taskbar so its clock/search box cannot bleed through.
TASKBAR_HEIGHT = 67
TASKBAR_TOP = IMAGE_HEIGHT - TASKBAR_HEIGHT
TASKBAR_COLOR = (26, 26, 26, 255)
DESKTOP_ICON_SIZE = 48
DESKTOP_ICON_X = 26
DESKTOP_ICON_TOP = 26
DESKTOP_ICON_ROW_SPACING = 98
DESKTOP_ICON_CONTENT_SIZE = 42
DESKTOP_LABEL_MARGIN = 5
DESKTOP_LABEL_MAX_WIDTH = 100
TASKBAR_START_X = 18
TASKBAR_SEARCH_X = 55
TASKBAR_SEARCH_WIDTH = 282
TASKBAR_PINNED_ICON_SIZE = 28
TASKBAR_PINNED_GAP = 42
TASKBAR_TRAY_NETWORK_X = 1658
TASKBAR_TRAY_VOLUME_X = 1693
TASKBAR_TRAY_BATTERY_X = 1728
TASKBAR_CLOCK_LEFT = 1770
TASKBAR_CLOCK_RIGHT = IMAGE_WIDTH - 1
MIN_DESKTOP_ICONS = 4
MAX_DESKTOP_ICONS = 8

CONTENT_ROOT = Path(__file__).resolve().parent
DESKTOP_ASSET_ROOT = CONTENT_ROOT / "assets" / "desktop"
WALLPAPER_DIRECTORY = DESKTOP_ASSET_ROOT / "wallpapers"
ICON_DIRECTORY = DESKTOP_ASSET_ROOT / "icons"
FONT_DIRECTORY = DESKTOP_ASSET_ROOT / "fonts"
OUTPUT_DIRECTORY = Path(__file__).resolve().parents[3] / "data" / "generated_images"

FONT_CANDIDATES = (
    FONT_DIRECTORY / "NotoSans-Regular.ttf",
    FONT_DIRECTORY / "Selawik-Regular.ttf",
    Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
)

ICON_LABELS = {
    "this-pc.png": "This PC",
    "recycle-bin.png": "Recycle Bin",
    "network.png": "Network",
    "google-chrome.png": "Google Chrome",
    "firefox.png": "Firefox",
    "teamviewer.png": "TeamViewer",
    "new-folder.png": "New Folder",
    "vlc.png": "VLC media player",
    "notepad-plus-plus.png": "Notepad++",
    "microsoft-word.png": "Microsoft Word",
    "zoom.png": "Zoom",
    "file-explorer.png": "File Explorer",
    "powershell.png": "PowerShell",
    "remote-desktop.png": "Remote Desktop",
    "telegram.png": "Telegram",
    "notepad.png": "Notepad",
}

_RANDOM = SystemRandom()
_SCENE_LOCK = asyncio.Lock()
_LAST_SELECTION: tuple[str, tuple[str, ...]] | None = None


class DesktopImageGenerationError(RuntimeError):
    """Raised when the local desktop asset set cannot produce an image."""


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size=size)
        except (OSError, TypeError):
            continue
    return ImageFont.load_default()


def _asset_files(directory: Path, *suffixes: str) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        )
    ) if directory.is_dir() else ()


def _wallpapers() -> tuple[Path, ...]:
    return _asset_files(WALLPAPER_DIRECTORY, ".png", ".jpg", ".jpeg")


def _icons() -> tuple[Path, ...]:
    icons = _asset_files(ICON_DIRECTORY, ".png")
    logger.info(
        "desktop_icon_directory_scanned",
        directory=str(ICON_DIRECTORY),
        exists=ICON_DIRECTORY.is_dir(),
        icon_count=len(icons),
        icon_names=[path.name for path in icons],
    )
    return icons


def _validate_assets() -> None:
    wallpapers = _wallpapers()
    icons = _icons()
    if not wallpapers:
        raise DesktopImageGenerationError(
            f"No desktop wallpapers found in {WALLPAPER_DIRECTORY}. "
            "Add at least one PNG or JPG wallpaper."
        )
    if not icons:
        raise DesktopImageGenerationError(
            f"No desktop icons found in {ICON_DIRECTORY}. Add transparent PNG icons."
        )
    if len(icons) < MIN_DESKTOP_ICONS:
        raise DesktopImageGenerationError(
            f"At least {MIN_DESKTOP_ICONS} desktop icons are required; found {len(icons)}."
        )
    for icon_path in icons:
        try:
            with Image.open(icon_path) as source:
                if source.width < 256 or source.height < 256:
                    raise DesktopImageGenerationError(
                        f"Desktop icon {icon_path.name} must be at least 256x256; "
                        f"found {source.width}x{source.height}."
                    )
                rgba = source.convert("RGBA")
                alpha = rgba.getchannel("A")
                if alpha.getextrema()[0] != 0:
                    raise DesktopImageGenerationError(
                        f"Desktop icon {icon_path.name} has no transparent pixels."
                    )
                if any(
                    alpha.getpixel(corner) != 0
                    for corner in ((0, 0), (rgba.width - 1, 0), (0, rgba.height - 1), (rgba.width - 1, rgba.height - 1))
                ):
                    raise DesktopImageGenerationError(
                        f"Desktop icon {icon_path.name} must have a transparent background."
                    )
        except DesktopImageGenerationError:
            raise
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise DesktopImageGenerationError(f"Could not validate icon {icon_path.name}.") from exc


def _choose_scene() -> tuple[Path, tuple[Path, ...]]:
    global _LAST_SELECTION

    wallpapers = _wallpapers()
    icons = _icons()
    icon_count = _RANDOM.randint(MIN_DESKTOP_ICONS, min(MAX_DESKTOP_ICONS, len(icons)))

    for _ in range(8):
        wallpaper = _RANDOM.choice(wallpapers)
        selected_icons = tuple(_RANDOM.sample(icons, k=icon_count))
        signature = (wallpaper.name, tuple(path.name for path in selected_icons))
        if signature != _LAST_SELECTION:
            _LAST_SELECTION = signature
            return wallpaper, selected_icons

    # UUID-based filenames still guarantee distinct output files if a tiny
    # asset collection makes the scene selection repeat.
    wallpaper = _RANDOM.choice(wallpapers)
    selected_icons = tuple(_RANDOM.sample(icons, k=icon_count))
    _LAST_SELECTION = (wallpaper.name, tuple(path.name for path in selected_icons))
    return wallpaper, selected_icons


def _load_wallpaper(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            source.load()
            image = source.convert("RGB")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise DesktopImageGenerationError(f"Could not read wallpaper {path.name}.") from exc

    # Cover-crop so user-provided wallpapers keep the exact 1920x1080 output.
    return ImageOps.fit(
        image,
        (IMAGE_WIDTH, IMAGE_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).convert("RGBA")


def _load_icon(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            source.load()
            icon = source.convert("RGBA")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise DesktopImageGenerationError(f"Could not read icon {path.name}.") from exc

    alpha_bbox = icon.getchannel("A").getbbox()
    if alpha_bbox:
        icon = icon.crop(alpha_bbox)
    icon.thumbnail(
        (DESKTOP_ICON_CONTENT_SIZE, DESKTOP_ICON_CONTENT_SIZE),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (DESKTOP_ICON_SIZE, DESKTOP_ICON_SIZE), (0, 0, 0, 0))
    canvas.alpha_composite(
        icon,
        (
            (DESKTOP_ICON_SIZE - icon.width) // 2,
            (DESKTOP_ICON_SIZE - icon.height) // 2,
        ),
    )
    return canvas


def _paste_icon(image: Image.Image, icon: Image.Image, position: tuple[int, int]) -> None:
    """Paste an RGBA icon onto the supplied canvas using its alpha channel."""
    rgba = icon.convert("RGBA")
    image.paste(rgba, position, rgba.getchannel("A"))


def _label_for_icon(path: Path) -> str:
    return ICON_LABELS.get(path.name, path.stem.replace("-", " ").title())


def _text_width(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox(
        (0, 0),
        text,
        font=font,
        anchor="la",
    )
    return max(0, bbox[2] - bbox[0])


def _wrap_label(
    label: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int = DESKTOP_LABEL_MAX_WIDTH,
) -> tuple[str, ...]:
    """Wrap labels by rendered pixel width, not character count."""
    words = label.split()
    if not words:
        return ("",)

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and _text_width(candidate, font) > max_width:
            lines.append(current)
            current = word
        elif not current and _text_width(word, font) > max_width:
            chunk = ""
            for character in word:
                if chunk and _text_width(chunk + character, font) > max_width:
                    lines.append(chunk)
                    chunk = character
                else:
                    chunk += character
            current = chunk
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines) or (label,)


def _clamped_label_left(
    image_width: int,
    center_x: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> int:
    """Keep a label inside both image edges while preserving centering when possible."""
    text_width = _text_width(text, font)
    centered_left = center_x - (text_width / 2)
    maximum_left = image_width - DESKTOP_LABEL_MARGIN - text_width
    return round(max(DESKTOP_LABEL_MARGIN, min(centered_left, maximum_left)))


def _draw_shadow_text(
    image: Image.Image,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    anchor: str | None = None,
    fill: tuple[int, int, int, int] = (255, 255, 255, 255),
    shadow: tuple[int, int, int, int] = (0, 0, 0, 210),
) -> None:
    shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.text(
        (position[0] + 1, position[1] + 1),
        text,
        font=font,
        fill=shadow,
        anchor=anchor,
    )
    image.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(radius=1.0)))
    draw = ImageDraw.Draw(image)
    draw.text(position, text, font=font, fill=fill, anchor=anchor)


def _draw_desktop_icons(image: Image.Image, selected_icons: tuple[Path, ...]) -> None:
    label_font = _font(14)
    logger.info(
        "desktop_icon_render_started",
        canvas_size=image.size,
        selected_count=len(selected_icons),
        selected_icons=[path.name for path in selected_icons],
    )

    current_icon: Path | None = None
    try:
        for index, icon_path in enumerate(selected_icons):
            current_icon = icon_path
            top = DESKTOP_ICON_TOP + index * DESKTOP_ICON_ROW_SPACING
            icon = _load_icon(icon_path)
            _paste_icon(image, icon, (DESKTOP_ICON_X, top))
            label = _label_for_icon(icon_path)
            label_lines = _wrap_label(label, label_font)
            label_top = top + DESKTOP_ICON_SIZE + 5
            for line_index, line in enumerate(label_lines[:2]):
                label_left = _clamped_label_left(
                    image.width,
                    DESKTOP_ICON_X + DESKTOP_ICON_SIZE // 2,
                    line,
                    label_font,
                )
                _draw_shadow_text(
                    image,
                    (label_left, label_top + line_index * 16),
                    line,
                    label_font,
                    anchor="la",
                    shadow=(0, 0, 0, 165),
                )
                logger.info(
                    "desktop_icon_label_layout",
                    icon=icon_path.name,
                    line=line,
                    line_index=line_index,
                    left=label_left,
                    width=_text_width(line, label_font),
                    wrapped=len(label_lines) > 1,
                )
            logger.info(
                "desktop_icon_rendered",
                icon=icon_path.name,
                index=index,
                position=(DESKTOP_ICON_X, top),
                size=icon.size,
            )
    except Exception as exc:
        logger.exception(
            "desktop_icon_render_failed",
            icon=current_icon.name if current_icon else None,
            selected_count=len(selected_icons),
            error=str(exc),
        )
        raise DesktopImageGenerationError(
            f"Could not render desktop icon {current_icon.name if current_icon else 'unknown'}."
        ) from exc

    logger.info("desktop_icon_render_completed", rendered_count=len(selected_icons))


def _draw_windows_logo(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    pane = max(3, size // 2 - 2)
    gap = max(2, size // 14)
    color = (238, 242, 247, 255)
    draw.rectangle((x, y, x + pane, y + pane), fill=color)
    draw.rectangle((x + pane + gap, y, x + size, y + pane), fill=color)
    draw.rectangle((x, y + pane + gap, x + pane, y + size), fill=color)
    draw.rectangle(
        (x + pane + gap, y + pane + gap, x + size, y + size),
        fill=color,
    )


def _draw_search_box(draw: ImageDraw.ImageDraw, left: int, top: int, width: int, height: int) -> None:
    draw.rounded_rectangle(
        (left, top, left + width, top + height),
        radius=2,
        fill=(58, 58, 58, 255),
    )
    center = (left + 20, top + height // 2)
    draw.ellipse((center[0] - 6, center[1] - 6, center[0] + 6, center[1] + 6), outline=(224, 224, 224, 240), width=2)
    draw.line((center[0] + 5, center[1] + 5, center[0] + 10, center[1] + 10), fill=(224, 224, 224, 240), width=2)
    draw.text((left + 38, top + 8), "Type here to search", font=_font(15), fill=(225, 225, 225, 245))


def _draw_network_icon(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    color: tuple[int, int, int, int],
    *,
    connected: bool,
) -> None:
    x, y = center
    if connected:
        draw.arc((x - 10, y - 9, x + 10, y + 11), 210, 330, fill=color, width=2)
        draw.arc((x - 6, y - 5, x + 6, y + 7), 210, 330, fill=color, width=2)
    else:
        draw.line((x - 8, y - 8, x + 8, y + 8), fill=color, width=2)
        draw.line((x + 8, y - 8, x - 8, y + 8), fill=color, width=2)
    draw.ellipse((x - 2, y + 4, x + 2, y + 8), fill=color)


def _draw_volume_icon(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    color: tuple[int, int, int, int],
    *,
    muted: bool,
) -> None:
    x, y = center
    draw.polygon(((x - 10, y - 3), (x - 5, y - 3), (x + 1, y - 9), (x + 1, y + 9), (x - 5, y + 3), (x - 10, y + 3)), fill=color)
    if muted:
        draw.line((x + 3, y - 7, x + 12, y + 7), fill=color, width=2)
        draw.line((x + 12, y - 7, x + 3, y + 7), fill=color, width=2)
    else:
        draw.arc((x - 2, y - 8, x + 11, y + 8), 285, 75, fill=color, width=2)


def _draw_battery_icon(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    color: tuple[int, int, int, int],
    *,
    charge: int,
) -> None:
    x, y = center
    draw.rectangle((x - 10, y - 6, x + 9, y + 6), outline=color, width=2)
    draw.rectangle((x + 10, y - 3, x + 12, y + 3), fill=color)
    fill_width = max(2, round(12 * max(0, min(charge, 100)) / 100))
    draw.rectangle((x - 7, y - 3, x - 7 + fill_width, y + 3), fill=color)


def _pinned_icons() -> tuple[Path, ...]:
    """Return a centered pinned set with Chrome and File Explorer when available."""
    available = {path.name: path for path in _icons()}
    preferred_names = (
        "google-chrome.png",
        "file-explorer.png",
        "telegram.png",
        "microsoft-word.png",
    )
    preferred = [available[name] for name in preferred_names if name in available]
    remaining = [path for path in available.values() if path not in preferred]
    pinned_count = min(4, len(available))
    if len(preferred) < pinned_count:
        preferred.extend(_RANDOM.sample(remaining, k=pinned_count - len(preferred)))
    return tuple(preferred[:pinned_count])


def _draw_taskbar_clock(image: Image.Image) -> None:
    """Clear and draw the clock/date exactly once on the right tray region."""
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (TASKBAR_CLOCK_LEFT, TASKBAR_TOP, TASKBAR_CLOCK_RIGHT, IMAGE_HEIGHT - 1),
        fill=TASKBAR_COLOR,
    )
    now = datetime.now()
    hour = now.hour % 12 or 12
    clock = f"{hour:02d}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"
    date = f"{now.month}/{now.day}/{now.year}"
    _draw_shadow_text(
        image,
        (1888, TASKBAR_TOP + 10),
        clock,
        _font(15),
        anchor="ra",
        fill=(240, 240, 240, 255),
        shadow=(0, 0, 0, 150),
    )
    _draw_shadow_text(
        image,
        (1888, TASKBAR_TOP + 28),
        date,
        _font(13),
        anchor="ra",
        fill=(240, 240, 240, 255),
        shadow=(0, 0, 0, 150),
    )
    logger.info("desktop_taskbar_clock_rendered_once", clock=clock, date=date)


def _clear_taskbar_region(image: Image.Image) -> None:
    """Erase wallpaper UI and any earlier taskbar pass with an opaque fill."""
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (0, TASKBAR_TOP, IMAGE_WIDTH - 1, IMAGE_HEIGHT - 1),
        fill=TASKBAR_COLOR,
    )
    logger.info(
        "desktop_taskbar_region_cleared",
        top=TASKBAR_TOP,
        bottom=IMAGE_HEIGHT - 1,
        height=TASKBAR_HEIGHT,
        opaque=True,
    )


def _draw_taskbar(image: Image.Image, selected_icons: tuple[Path, ...]) -> None:
    _clear_taskbar_region(image)
    draw = ImageDraw.Draw(image)
    draw.line(
        (0, TASKBAR_TOP, IMAGE_WIDTH - 1, TASKBAR_TOP),
        fill=(73, 73, 73, 255),
        width=1,
    )

    # Left section: Start button and search box only.
    _draw_windows_logo(draw, TASKBAR_START_X, TASKBAR_TOP + 13, 23)
    _draw_search_box(draw, TASKBAR_SEARCH_X, TASKBAR_TOP + 7, TASKBAR_SEARCH_WIDTH, 34)

    # Center section: pinned apps. Chrome and File Explorer are preferred.
    pinned = _pinned_icons()
    pinned_width = TASKBAR_PINNED_ICON_SIZE + TASKBAR_PINNED_GAP * max(0, len(pinned) - 1)
    pinned_x = (IMAGE_WIDTH - pinned_width) // 2
    for index, icon_path in enumerate(pinned):
        icon = _load_icon(icon_path).resize(
            (TASKBAR_PINNED_ICON_SIZE, TASKBAR_PINNED_ICON_SIZE),
            Image.Resampling.LANCZOS,
        )
        _paste_icon(image, icon, (pinned_x + index * TASKBAR_PINNED_GAP, TASKBAR_TOP + 10))

    # Right section: system tray glyphs and one clock/date region.
    tray_color = (230, 234, 238, 245)
    _draw_network_icon(
        draw,
        (TASKBAR_TRAY_NETWORK_X, TASKBAR_TOP + 24),
        tray_color,
        connected=_RANDOM.choice((True, True, False)),
    )
    _draw_volume_icon(
        draw,
        (TASKBAR_TRAY_VOLUME_X, TASKBAR_TOP + 24),
        tray_color,
        muted=_RANDOM.choice((False, False, True)),
    )
    _draw_battery_icon(
        draw,
        (TASKBAR_TRAY_BATTERY_X, TASKBAR_TOP + 24),
        tray_color,
        charge=_RANDOM.choice((25, 50, 75, 100)),
    )
    _draw_taskbar_clock(image)
    logger.info(
        "desktop_taskbar_rendered",
        left_section={"start_x": TASKBAR_START_X, "search_x": TASKBAR_SEARCH_X},
        pinned_section={"x": pinned_x, "icons": [path.name for path in pinned]},
        tray_section={
            "network_x": TASKBAR_TRAY_NETWORK_X,
            "volume_x": TASKBAR_TRAY_VOLUME_X,
            "battery_x": TASKBAR_TRAY_BATTERY_X,
            "clock_left": TASKBAR_CLOCK_LEFT,
        },
    )


def _render_scene() -> bytes:
    _validate_assets()
    wallpaper, selected_icons = _choose_scene()
    logger.info(
        "desktop_scene_selected",
        wallpaper=wallpaper.name,
        selected_icons=[path.name for path in selected_icons],
    )
    image = _load_wallpaper(wallpaper)
    _draw_desktop_icons(image, selected_icons)
    _draw_taskbar(image, selected_icons)

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    logger.info(
        "desktop_scene_rendered",
        image_size=image.size,
        output_bytes=output.tell(),
        selected_icon_count=len(selected_icons),
    )
    return output.getvalue()


def _save_image(image_bytes: bytes) -> str:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    filename = f"windows10-desktop-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{uuid4().hex}.png"
    path = OUTPUT_DIRECTORY / filename
    path.write_bytes(image_bytes)
    return str(path)


async def generate_desktop_image(prompt: str | None = None) -> str:
    """Create a fresh local Windows 10 desktop screenshot and return its path.

    ``prompt`` remains accepted for compatibility with existing callers, but
    the image is intentionally independent of text or external AI services.
    """
    del prompt
    async with _SCENE_LOCK:
        try:
            image_bytes = await asyncio.to_thread(_render_scene)
            return await asyncio.to_thread(_save_image, image_bytes)
        except DesktopImageGenerationError:
            raise
        except OSError as exc:
            message = f"Could not save the desktop image: {str(exc)[:240]}"
            logger.error("desktop_image_save_failed", error=str(exc)[:240])
            raise DesktopImageGenerationError(message) from exc
        except Exception as exc:
            message = f"Desktop image generation failed unexpectedly: {str(exc)[:240]}"
            logger.exception("desktop_image_generation_failed", error=str(exc)[:240])
            raise DesktopImageGenerationError(message) from exc


async def check_desktop_assets() -> bool:
    """Validate local assets during application startup."""
    _validate_assets()
    logger.info(
        "desktop_image_assets_configured",
        wallpapers=len(_wallpapers()),
        icons=len(_icons()),
        output_directory=str(OUTPUT_DIRECTORY),
    )
    return True