"""Generate three randomized desktop images and print their saved paths.

Run from the repository root:
    python scripts/test_desktop_image.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.services.content import desktop_image_generator as generator
from app.services.content.desktop_image_generator import (
    DesktopImageGenerationError,
    generate_desktop_image,
)


def _non_taskbar_pixels(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    region = image.crop(box)
    taskbar = (26, 26, 26)
    pixels = region.load()
    return sum(
        pixels[x, y] != taskbar
        for y in range(region.height)
        for x in range(region.width)
    )


def _verify_rendered_image(path: str) -> None:
    image_path = Path(path)
    if image_path.stat().st_size < 100_000:
        raise AssertionError(f"Rendered image is unexpectedly small: {image_path.stat().st_size} bytes")

    with Image.open(image_path) as source:
        image = source.convert("RGB")
        if image.size != (generator.IMAGE_WIDTH, generator.IMAGE_HEIGHT):
            raise AssertionError(f"Expected 1920x1080 output, got {image.size}")

        checks = {
            "Start": (0, generator.TASKBAR_TOP, 45, generator.IMAGE_HEIGHT),
            "search": (
                generator.TASKBAR_SEARCH_X,
                generator.TASKBAR_TOP + 7,
                generator.TASKBAR_SEARCH_X + generator.TASKBAR_SEARCH_WIDTH,
                generator.TASKBAR_TOP + 41,
            ),
            "pinned": (800, generator.TASKBAR_TOP, 1120, generator.IMAGE_HEIGHT),
            "system tray": (
                generator.TASKBAR_TRAY_NETWORK_X - 20,
                generator.TASKBAR_TOP,
                generator.TASKBAR_TRAY_BATTERY_X + 25,
                generator.IMAGE_HEIGHT,
            ),
            "clock": (
                generator.TASKBAR_CLOCK_LEFT,
                generator.TASKBAR_TOP,
                generator.IMAGE_WIDTH,
                generator.IMAGE_HEIGHT,
            ),
        }
        for name, box in checks.items():
            changed_pixels = _non_taskbar_pixels(image, box)
            if changed_pixels < 20:
                raise AssertionError(f"{name} region appears empty: {changed_pixels} changed pixels")

        # Compare the first icon slot with each clean wallpaper. The closest
        # wallpaper still must differ, proving the icon was composited onto the
        # same canvas that was saved.
        slot = (
            generator.DESKTOP_ICON_X,
            generator.DESKTOP_ICON_TOP,
            generator.DESKTOP_ICON_X + generator.DESKTOP_ICON_SIZE,
            generator.DESKTOP_ICON_TOP + generator.DESKTOP_ICON_SIZE,
        )
        output_slot = image.crop(slot)
        wallpaper_diffs = []
        for wallpaper_path in generator._wallpapers():
            wallpaper = generator._load_wallpaper(wallpaper_path).convert("RGB")
            mean = ImageStat.Stat(
                ImageChops.difference(output_slot, wallpaper.crop(slot))
            ).mean
            wallpaper_diffs.append(sum(mean) / len(mean))
        if not wallpaper_diffs or min(wallpaper_diffs) <= 0.5:
            raise AssertionError("The first desktop icon slot appears unchanged from every wallpaper")


def _verify_long_label_layout() -> None:
    font = generator._font(14)
    lines = generator._wrap_label("Remote Desktop", font)
    if lines != ("Remote", "Desktop"):
        raise AssertionError(f"Expected pixel-aware Remote Desktop wrapping, got {lines}")

    for center_x in (
        generator.DESKTOP_ICON_X + generator.DESKTOP_ICON_SIZE // 2,
        generator.IMAGE_WIDTH - generator.DESKTOP_ICON_SIZE // 2,
    ):
        for line in lines:
            left = generator._clamped_label_left(
                generator.IMAGE_WIDTH,
                center_x,
                line,
                font,
            )
            right = left + generator._text_width(line, font)
            if left < generator.DESKTOP_LABEL_MARGIN or right > generator.IMAGE_WIDTH - generator.DESKTOP_LABEL_MARGIN:
                raise AssertionError(
                    f"Label escaped image bounds: center={center_x}, line={line!r}, "
                    f"left={left}, right={right}"
                )


async def main() -> int:
    _verify_long_label_layout()
    paths: list[str] = []
    for index in range(3):
        try:
            path = await generate_desktop_image(f"Windows VPS desktop preview test {index + 1}")
            _verify_rendered_image(path)
        except DesktopImageGenerationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except (OSError, AssertionError) as exc:
            print(f"ERROR: rendered image verification failed: {exc}", file=sys.stderr)
            return 1
        paths.append(path)

    print("Generated desktop images:")
    for path in paths:
        print(path)
    if len(set(paths)) != 3:
        print("ERROR: output paths were not unique", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))