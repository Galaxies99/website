#!/usr/bin/env bash
# Optimize teaser media for the website.
#
# - Converts every GIF under images/research/ and images/project/ to both
#   MP4 (H.264) and WebM (VP9). Animated MP4/WebM are typically 10-30x
#   smaller than the equivalent GIF.
# - Re-encodes large PNGs (>= 1 MB) to WebP at high quality.
#
# Originals are kept untouched. Optimized files are written next to them
# with the original basename and a new extension (e.g. airexo.gif ->
# airexo.mp4, airexo.webm; cage.png -> cage.webp).
#
# Requires: ffmpeg, cwebp.
#   macOS:   brew install ffmpeg webp
#   Ubuntu:  sudo apt install ffmpeg webp
#
# Usage (run from the repo root):
#   bash scripts/optimize_media.sh
#   bash scripts/optimize_media.sh --dry-run        # show what would be done
#   bash scripts/optimize_media.sh --max-width 480  # override max width
#   bash scripts/optimize_media.sh --png-min-mb 2   # only convert larger PNGs

set -euo pipefail

MAX_WIDTH=480       # teasers render at width=160; 480px covers 3x retina
PNG_MIN_BYTES=$((1 * 1024 * 1024))  # only re-encode PNGs >= 1 MB
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)     DRY_RUN=1; shift ;;
    --max-width)   MAX_WIDTH="$2"; shift 2 ;;
    --png-min-mb)  PNG_MIN_BYTES=$(( $2 * 1024 * 1024 )); shift 2 ;;
    -h|--help)
      sed -n '2,/^set -/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v ffmpeg >/dev/null || { echo "ffmpeg not found. Install with: brew install ffmpeg" >&2; exit 1; }
command -v cwebp  >/dev/null || { echo "cwebp not found. Install with: brew install webp"  >&2; exit 1; }

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry] $*"
  else
    "$@"
  fi
}

human() {
  # bytes -> human-readable
  awk -v b="$1" 'BEGIN{
    split("B KB MB GB", u);
    for (i=1; b>=1024 && i<4; i++) b/=1024;
    printf "%.1f %s", b, u[i];
  }'
}

# Even-width scaler so H.264/VP9 don't reject odd dimensions.
SCALE_FILTER="scale='min(${MAX_WIDTH},iw)':-2:flags=lanczos"

convert_gif() {
  local gif="$1"
  local base="${gif%.gif}"
  local mp4="${base}.mp4"
  local webm="${base}.webm"

  echo "GIF  $gif  ($(human "$(stat -f%z "$gif" 2>/dev/null || stat -c%s "$gif")"))"

  # MP4 / H.264. yuv420p for max compatibility (Safari iOS especially).
  # +faststart lets playback start before the whole file downloads.
  if ! run ffmpeg -y -loglevel error -i "$gif" \
      -movflags +faststart \
      -pix_fmt yuv420p \
      -vf "$SCALE_FILTER" \
      -an -c:v libx264 -profile:v high -preset slower -crf 23 \
      "$mp4"; then
    echo "     !! mp4 encode failed; skipping" >&2
  fi

  # WebM / VP9. Smaller than MP4 in many cases; Chromium/Firefox prefer it.
  # yuva420p preserves alpha channel if the source GIF has one.
  if ! run ffmpeg -y -loglevel error -i "$gif" \
      -pix_fmt yuva420p \
      -vf "$SCALE_FILTER" \
      -an -c:v libvpx-vp9 -b:v 0 -crf 34 -row-mt 1 -tile-columns 2 \
      "$webm"; then
    echo "     !! webm encode failed; skipping" >&2
  fi

  if [[ "$DRY_RUN" -eq 0 ]]; then
    local s_gif s_mp4 s_webm
    s_gif=$(stat -f%z "$gif"  2>/dev/null || stat -c%s "$gif")
    if [[ -s "$mp4" ]]; then
      s_mp4=$(stat -f%z "$mp4"  2>/dev/null || stat -c%s "$mp4")
      printf "     -> mp4  %s   (%.1fx smaller)\n" "$(human "$s_mp4")"  "$(awk "BEGIN{printf \"%.2f\", $s_gif/$s_mp4}")"
    fi
    if [[ -s "$webm" ]]; then
      s_webm=$(stat -f%z "$webm" 2>/dev/null || stat -c%s "$webm")
      printf "     -> webm %s   (%.1fx smaller)\n" "$(human "$s_webm")" "$(awk "BEGIN{printf \"%.2f\", $s_gif/$s_webm}")"
    fi
  fi
}

convert_png() {
  local png="$1"
  local size
  size=$(stat -f%z "$png" 2>/dev/null || stat -c%s "$png")
  if (( size < PNG_MIN_BYTES )); then return 0; fi

  local webp="${png%.png}.webp"
  echo "PNG  $png  ($(human "$size"))"
  # -q 82 is a good visual sweet spot for screenshots/figures.
  # -m 6 = max compression effort. -mt = multithread.
  run cwebp -quiet -q 82 -m 6 -mt "$png" -o "$webp"

  if [[ "$DRY_RUN" -eq 0 ]]; then
    local s_webp
    s_webp=$(stat -f%z "$webp" 2>/dev/null || stat -c%s "$webp")
    printf "     -> webp %s   (%.1fx smaller)\n" "$(human "$s_webp")" "$(awk "BEGIN{printf \"%.2f\", $size/$s_webp}")"
  fi
}

shopt -s nullglob
for dir in images/research images/project; do
  for gif in "$dir"/*.gif;          do convert_gif "$gif"; done
  for png in "$dir"/*.png "$dir"/*.PNG; do convert_png "$png"; done
done

echo
echo "Done. Originals are untouched; new .mp4/.webm/.webp files sit alongside them."
echo "Next step: in index.html, replace each <img src=\"...gif\"> with"
echo
echo '    <video loop muted playsinline preload="none" data-autoplay="1" width="160">'
echo '      <source src="...webm" type="video/webm">'
echo '      <source src="...mp4"  type="video/mp4">'
echo '    </video>'
echo
echo "and each large <img src=\"...png\"> with the .webp equivalent (or use <picture>"
echo "to serve .webp with a .png fallback)."
