#!/usr/bin/env python3
"""Generate responsive profile images and the homepage sharing card.

Run from the repository root (Pillow is only a local generation dependency):
    python3 -m venv .cache/profile-images-venv
    .cache/profile-images-venv/bin/python -m pip install 'Pillow==11.3.0'
    .cache/profile-images-venv/bin/python scripts/build_profile_images.py

The original PNGs are never overwritten. WebP outputs retain transparency,
apply EXIF orientation, and omit embedded metadata. Fonts are read from the
host system, never copied into the repository. Pass --serif-font and
--sans-font to choose installed fonts on other systems. Image bytes may differ
between Pillow/libwebp versions; card typography depends on the chosen fonts.
"""

import argparse
import hashlib
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, features
except ImportError as exc:
    raise SystemExit("Pillow is required. See this script's setup instructions.") from exc


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "images" / "profile"
PROFILE_NAMES = ("profile5", "profile1", "profile2", "profile3")
SIZES = (240, 480, 720)
BACKGROUND = "#fcfbf9"
ACCENT = "#9c463b"
INK = "#292725"
MUTED = "#69625d"
SERIF_FONTS = (
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
    "C:/Windows/Fonts/georgia.ttf",
)
SANS_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def font_path(override, candidates, option):
    """Resolve an installed font, failing rather than using tiny bitmap text."""
    choices = (str(override.expanduser()),) if override else candidates
    for candidate in choices:
        if Path(candidate).is_file():
            return candidate
    raise ValueError(f"No installed font found; supply {option} /path/to/font.ttf")


def clean_photo(path):
    """Bake orientation into pixels and discard all source metadata."""
    with Image.open(path) as original:
        oriented = ImageOps.exif_transpose(original)
        mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
        pixels = oriented.convert(mode)
        clean = Image.new(mode, pixels.size)
        clean.paste(pixels)
        return clean


def validate_image(path, size, image_format):
    """Check decoded dimensions and absence of optional identifying metadata."""
    with Image.open(path) as image:
        image.load()
        if image.size != size or image.format != image_format:
            raise ValueError(f"Unexpected output dimensions or format: {path}")
        if image.getexif() or any(
            image.info.get(key) for key in ("exif", "icc_profile", "xmp", "XML:com.adobe.xmp", "comment")
        ):
            raise ValueError(f"Unexpected embedded metadata: {path}")
    return path.stat().st_size


def sharing_card(photo, serif, sans):
    """Render a restrained academic card at 2x, then downsample for crisp type."""
    scale = 2
    card = Image.new("RGB", (1200 * scale, 630 * scale), BACKGROUND)
    draw = ImageDraw.Draw(card)

    def text(label, x, y, font_file, size, color, max_width=630):
        font = ImageFont.truetype(font_file, size * scale)
        while draw.textlength(label, font=font) > max_width * scale:
            size -= 1
            if size < 20:
                raise ValueError(f"Font is too wide for sharing card text: {label}")
            font = ImageFont.truetype(font_file, size * scale)
        draw.text((x * scale, y * scale), label, font=font, fill=color, anchor="lt")

    draw.rectangle((76 * scale, 144 * scale, 140 * scale, 148 * scale), fill=ACCENT)
    text("Hongjie Fang", 72, 190, serif, 78, INK)
    text("Robotics & Robot Learning", 76, 299, sans, 32, INK)
    text("Shanghai Jiao Tong University", 76, 352, sans, 27, MUTED)
    text("tonyfang.net", 76, 484, sans, 26, ACCENT)

    portrait = photo.resize((360 * scale, 360 * scale), Image.Resampling.LANCZOS)
    position = (764 * scale, 128 * scale)
    card.paste(portrait, position, portrait.getchannel("A") if portrait.mode == "RGBA" else None)
    card = card.resize((1200, 630), Image.Resampling.LANCZOS)
    destination = PROFILE_DIR / "social-card.jpg"
    card.save(destination, "JPEG", quality=90, optimize=True, progressive=True, subsampling=0)
    size = validate_image(destination, (1200, 630), "JPEG")
    print(f"{destination.relative_to(ROOT)}: 1200x630, {size:,} bytes ({size / 1024:.1f} KiB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quality", type=int, default=84, help="WebP quality, 1–100 (default: 84)")
    parser.add_argument("--serif-font", type=Path, help="Installed serif font for the sharing-card name")
    parser.add_argument("--sans-font", type=Path, help="Installed sans-serif font for sharing-card details")
    args = parser.parse_args()
    if not 1 <= args.quality <= 100:
        parser.error("--quality must be between 1 and 100")
    if not features.check("webp"):
        parser.error("This Pillow installation lacks WebP support")

    serif = font_path(args.serif_font, SERIF_FONTS, "--serif-font")
    sans = font_path(args.sans_font, SANS_FONTS, "--sans-font")
    sources = {name: PROFILE_DIR / f"{name}.png" for name in PROFILE_NAMES}
    originals = {path: hashlib.sha256(path.read_bytes()).digest() for path in sources.values()}
    photos = {name: clean_photo(path) for name, path in sources.items()}
    totals = {width: 0 for width in SIZES}
    original_total = sum(path.stat().st_size for path in sources.values())

    print(f"WebP quality: {args.quality}; metadata: stripped; EXIF orientation: applied")
    for name, source in sources.items():
        photo = photos[name]
        original_size = source.stat().st_size
        print(f"\n{source.relative_to(ROOT)}: {photo.width}x{photo.height}, {original_size:,} bytes")
        for width in SIZES:
            destination = PROFILE_DIR / f"{name}-{width}.webp"
            # Center-crop the nearly square source without distorting its aspect ratio.
            resized = ImageOps.fit(photo, (width, width), method=Image.Resampling.LANCZOS)
            resized.save(destination, "WEBP", quality=args.quality, method=6)
            output_size = validate_image(destination, (width, width), "WEBP")
            totals[width] += output_size
            reduction = 100 * (1 - output_size / original_size)
            print(
                f"  {destination.name}: {width}x{width}, {output_size:,} bytes "
                f"({output_size / 1024:.1f} KiB), {reduction:.2f}% smaller"
            )

    print(f"\nSharing-card fonts: {serif}; {sans}")
    sharing_card(photos["profile5"], serif, sans)
    for path, digest in originals.items():
        if hashlib.sha256(path.read_bytes()).digest() != digest:
            raise ValueError(f"Original source changed unexpectedly: {path}")
    print(f"\nOriginal PNGs preserved and verified: {original_total:,} bytes total")
    for width, total in totals.items():
        print(f"All four {width}px variants: {total:,} bytes, {100 * (1 - total / original_total):.2f}% smaller")


if __name__ == "__main__":
    main()
