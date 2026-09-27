"""Validate the checked-in desktop icon assets.

Run from the repository root:
    python scripts/validate_desktop_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError


ICON_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "content"
    / "assets"
    / "desktop"
    / "icons"
)


def main() -> int:
    icons = sorted(ICON_DIRECTORY.glob("*.png"))
    if not icons:
        raise SystemExit(f"No PNG icons found in {ICON_DIRECTORY}")

    failures: list[str] = []
    for path in icons:
        try:
            with Image.open(path) as source:
                rgba = source.convert("RGBA")
                alpha = rgba.getchannel("A")
                corners = (
                    alpha.getpixel((0, 0)),
                    alpha.getpixel((rgba.width - 1, 0)),
                    alpha.getpixel((0, rgba.height - 1)),
                    alpha.getpixel((rgba.width - 1, rgba.height - 1)),
                )
                if rgba.size != (256, 256):
                    failures.append(f"{path.name}: expected 256x256, got {rgba.size}")
                if alpha.getextrema()[0] != 0:
                    failures.append(f"{path.name}: no transparent pixels")
                if any(corners):
                    failures.append(f"{path.name}: non-transparent corner pixel")
                if alpha.getbbox() is None:
                    failures.append(f"{path.name}: fully transparent")
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            failures.append(f"{path.name}: {exc}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1

    print(f"Validated {len(icons)} transparent RGBA desktop icons at 256x256.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())