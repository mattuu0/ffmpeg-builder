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

# Use the Apple Silicon Homebrew prefix explicitly. On a Mac that also has
# an Intel Homebrew installed at /usr/local (e.g. via Rosetta), that one may
# come first on PATH — its bottles are x86_64 and would produce an x86_64
# openh264 that can't link against this arm64 ffmpeg build.
BREW="/opt/homebrew/bin/brew"
command -v "$BREW" >/dev/null 2>&1 || { echo "Apple Silicon Homebrew (/opt/homebrew) is required" >&2; exit 1; }
"$BREW" install nasm pkg-config meson ninja
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/pkgconf/bin:${PATH}"

# openh264 (BSD-licensed H.264 software encoder), used as a fallback encoder
# alongside VideoToolbox. Installed into a local prefix rather than
# /usr/local, which the GitHub Actions macos runner user cannot write to.
OPENH264_PREFIX="${BUILD_TMP}/openh264-install"
git clone --depth 1 --branch v2.6.0 https://github.com/cisco/openh264.git "${BUILD_TMP}/openh264"
meson setup "${BUILD_TMP}/openh264/build" "${BUILD_TMP}/openh264" --prefix="$OPENH264_PREFIX" --libdir=lib
ninja -C "${BUILD_TMP}/openh264/build" install

# Rewrite the dylib's own install name (embedded at link time as the
# absolute build-tmp path) to an @rpath-relative one now, before ffmpeg
# links against it — otherwise ffmpeg/libavcodec bake in that absolute
# temp path, which no longer exists once this script's trap removes
# BUILD_TMP, and the resulting binary fails to load on any machine.
OPENH264_DYLIB="$(find "${OPENH264_PREFIX}/lib" -name 'libopenh264.*.dylib' ! -type l)"
install_name_tool -id "@rpath/$(basename "$OPENH264_DYLIB")" "$OPENH264_DYLIB"

# libopus (BSD-licensed) for Opus audio encode/decode. Uses the release
# tarball (ships a pre-generated ./configure) rather than a git clone of the
# tag, which would need autoreconf (autoconf/automake/libtool + a network
# fetch) to produce configure.
OPUS_PREFIX="${BUILD_TMP}/opus-install"
curl -L -o "${BUILD_TMP}/opus.tar.gz" https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz
mkdir "${BUILD_TMP}/opus"
tar -xzf "${BUILD_TMP}/opus.tar.gz" -C "${BUILD_TMP}/opus" --strip-components=1
mkdir "${BUILD_TMP}/opus/build"
( cd "${BUILD_TMP}/opus/build" && ../configure --prefix="$OPUS_PREFIX" --disable-shared --enable-static --disable-doc --disable-extra-programs --with-pic && make -j"$(sysctl -n hw.ncpu)" && make install )

export PKG_CONFIG_PATH="${OPENH264_PREFIX}/lib/pkgconfig:${OPUS_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"

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
  --enable-muxer=h264 \
  --enable-muxer=hevc \
  --enable-parser=h264 \
  --enable-parser=hevc \
  --enable-parser=opus \
  --enable-bsf=h264_mp4toannexb \
  --enable-bsf=hevc_mp4toannexb \
  --enable-filter=format \
  --enable-filter=scale \
  --enable-filter=null \
  --enable-filter=aformat \
  --enable-filter=anull \
  --enable-swscale \
  --enable-swresample \
  --enable-videotoolbox \
  --enable-libopenh264 \
  --enable-libopus \
  --enable-encoder=h264_videotoolbox \
  --enable-encoder=hevc_videotoolbox \
  --enable-encoder=libopenh264 \
  --enable-encoder=libopus \
  --enable-decoder=libopus \
  --extra-cflags="-Os -ffunction-sections -fdata-sections" \
  --extra-ldflags="-Wl,-dead_strip -L${OPENH264_PREFIX}/lib -L${OPUS_PREFIX}/lib -Wl,-rpath,@executable_path/../lib" \
  --extra-libs="-lm"

make -j"$(sysctl -n hw.ncpu)"
make install

# libopenh264 is a shared library (opus is statically linked above), so the
# dylib itself must ship alongside the ffmpeg binary — the rpath above points
# at @executable_path/../lib, not the temporary build prefix, which is
# deleted when this script exits.
mkdir -p "${DIST_DIR}/lib"
cp -L "${OPENH264_PREFIX}"/lib/libopenh264*.dylib "${DIST_DIR}/lib/"

strip -x "${DIST_DIR}/bin/ffmpeg"

( cd "$DIST_DIR" && find . -type f ! -name 'SHA256SUMS.txt' -exec shasum -a 256 {} + | sed 's# \./# #' > SHA256SUMS.txt )

echo "Build complete: ${DIST_DIR}/bin/ffmpeg"
