#!/usr/bin/env bash
# Build ffmpeg for linux or windows via Docker and copy the result to
# dist/<platform>/<arch>/. Used both locally and from GitHub Actions.
set -euo pipefail

PLATFORM="${1:?usage: build.sh <linux|windows> [amd64|arm64]}"
ARCH="${2:-amd64}"

case "$PLATFORM" in
  linux|windows) ;;
  *) echo "Unsupported platform: $PLATFORM (expected linux or windows)" >&2; exit 1 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="ffmpeg-${PLATFORM}-${ARCH}"
CONTAINER="ffmpeg-${PLATFORM}-${ARCH}-extract"
OUT_DIR="${REPO_ROOT}/dist/${PLATFORM}/${ARCH}"

docker build --build-arg ARCH="$ARCH" -f "${REPO_ROOT}/docker/${PLATFORM}/Dockerfile" -t "$IMAGE" "$REPO_ROOT"

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker create --name "$CONTAINER" "$IMAGE" >/dev/null

mkdir -p "$OUT_DIR"
docker cp "${CONTAINER}:/dist/." "$OUT_DIR/"
docker rm "$CONTAINER" >/dev/null

( cd "$OUT_DIR" && find . -type f ! -name 'SHA256SUMS.txt' -exec sha256sum {} + | sed 's# \./# #' > SHA256SUMS.txt )

echo "Build complete: ${OUT_DIR}"
