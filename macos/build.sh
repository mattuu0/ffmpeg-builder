#!/usr/bin/env bash
# Native macOS build (no Docker/osxcross). Intended to run on a macOS
# GitHub Actions runner (macos-14, Apple Silicon) or a local Apple Silicon Mac.
#
# Minimal build: H.264/H.265 hardware encode (VideoToolbox) + openh264
# (H.264 software) fallback, no audio, no software decoders.
set -euo pipefail

ARCH="arm64"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FFMPEG_SRC="${REPO_ROOT}/ffmpeg-src"
DIST_DIR="${REPO_ROOT}/dist/macos/${ARCH}"
BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "$BUILD_TMP"' EXIT

command -v brew >/dev/null 2>&1 || { echo "Homebrew is required" >&2; exit 1; }
brew install nasm pkg-config meson ninja

# openh264 (BSD-licensed H.264 software encoder), used as a fallback encoder
# alongside VideoToolbox. Installed into a local prefix rather than
# /usr/local, which the GitHub Actions macos runner user cannot write to.
OPENH264_PREFIX="${BUILD_TMP}/openh264-install"
git clone --depth 1 --branch v2.6.0 https://github.com/cisco/openh264.git "${BUILD_TMP}/openh264"
meson setup "${BUILD_TMP}/openh264/build" "${BUILD_TMP}/openh264" --prefix="$OPENH264_PREFIX" --libdir=lib
ninja -C "${BUILD_TMP}/openh264/build" install

export PKG_CONFIG_PATH="${OPENH264_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"

cd "$FFMPEG_SRC"

# ---------------------------------------------------------------------------
# configure flags — edit below to add/remove features for the macOS build.
# NVENC is intentionally omitted: Apple Silicon has no NVIDIA GPU.
# ---------------------------------------------------------------------------
./configure \
  --prefix="$DIST_DIR" \
  --target-os=darwin \
  --arch="$ARCH" \
  --enable-shared \
  --disable-static \
  --disable-everything \
  --disable-ffprobe \
  --disable-ffplay \
  --disable-doc \
  --disable-htmlpages \
  --disable-manpages \
  --disable-podpages \
  --disable-txtpages \
  --disable-debug \
  --enable-avdevice \
  --enable-indev=avfoundation \
  --enable-pthreads \
  --enable-protocol=file \
  --enable-protocol=pipe \
  --enable-protocol=tcp \
  --enable-protocol=udp \
  --enable-protocol=rtmp \
  --enable-protocol=rtp \
  --enable-demuxer=rawvideo \
  --enable-muxer=rawvideo \
  --enable-muxer=mp4 \
  --enable-muxer=mov \
  --enable-muxer=matroska \
  --enable-muxer=mpegts \
  --enable-muxer=flv \
  --enable-parser=h264 \
  --enable-parser=hevc \
  --enable-bsf=h264_mp4toannexb \
  --enable-bsf=hevc_mp4toannexb \
  --enable-filter=scale \
  --enable-filter=format \
  --enable-filter=null \
  --enable-videotoolbox \
  --enable-libopenh264 \
  --enable-encoder=h264_videotoolbox \
  --enable-encoder=hevc_videotoolbox \
  --enable-encoder=libopenh264 \
  --extra-cflags="-Os -ffunction-sections -fdata-sections" \
  --extra-ldflags="-Wl,-dead_strip -L${OPENH264_PREFIX}/lib -Wl,-rpath,${OPENH264_PREFIX}/lib"

make -j"$(sysctl -n hw.ncpu)"
make install

strip -x "${DIST_DIR}/bin/ffmpeg"

( cd "$DIST_DIR" && find . -type f ! -name 'SHA256SUMS.txt' -exec shasum -a 256 {} + | sed 's# \./# #' > SHA256SUMS.txt )

echo "Build complete: ${DIST_DIR}/bin/ffmpeg"
