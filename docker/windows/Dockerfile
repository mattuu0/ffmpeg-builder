FROM debian:bookworm-slim

ARG ARCH=amd64

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    cmake \
    meson \
    ninja-build \
    pkg-config \
    yasm \
    nasm \
    git \
    curl \
    ca-certificates \
    gcc-mingw-w64-x86-64 \
    g++-mingw-w64-x86-64 \
    && rm -rf /var/lib/apt/lists/*

# gcc-mingw-w64-aarch64 is not available on Ubuntu 22.04's apt repos as of
# this writing. Fall back to llvm-mingw (prebuilt toolchain release) for the
# arm64 target when requested.
RUN set -eux; \
    if [ "$ARCH" = "arm64" ]; then \
      apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y xz-utils jq && rm -rf /var/lib/apt/lists/*; \
      LLVM_MINGW_URL=$(curl -s https://api.github.com/repos/mstorsjo/llvm-mingw/releases/latest \
        | jq -r '.assets[] | select(.name | test("ucrt-ubuntu-22.04-x86_64.tar.xz$")) | .browser_download_url'); \
      curl -L -o /tmp/llvm-mingw.tar.xz "$LLVM_MINGW_URL"; \
      mkdir -p /opt/llvm-mingw; \
      tar -xJf /tmp/llvm-mingw.tar.xz -C /opt/llvm-mingw --strip-components=1; \
      rm /tmp/llvm-mingw.tar.xz; \
    fi
ENV PATH="/opt/llvm-mingw/bin:${PATH}"

# Use the posix-threads mingw-w64 gcc variant (not win32-threads) so that
# -pthread / pthreads support is available, which FFmpeg's build requires.
RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then \
      update-alternatives --set x86_64-w64-mingw32-gcc /usr/bin/x86_64-w64-mingw32-gcc-posix; \
      update-alternatives --set x86_64-w64-mingw32-g++ /usr/bin/x86_64-w64-mingw32-g++-posix; \
    fi

WORKDIR /build

# NVIDIA NVENC headers (header-only, amd64 target only)
RUN git clone --depth 1 https://github.com/FFmpeg/nv-codec-headers.git /tmp/nv-codec-headers \
    && make -C /tmp/nv-codec-headers PREFIX=/usr/x86_64-w64-mingw32 install \
    && rm -rf /tmp/nv-codec-headers

# AMD AMF headers (header-only, amd64 target only)
RUN git clone --depth 1 https://github.com/GPUOpen-LibrariesAndSDKs/AMF.git /tmp/AMF \
    && mkdir -p /usr/x86_64-w64-mingw32/include/AMF \
    && cp -r /tmp/AMF/amf/public/include/* /usr/x86_64-w64-mingw32/include/AMF/ \
    && rm -rf /tmp/AMF

# openh264 (BSD-licensed H.264 software encoder), cross-built for mingw as a
# fallback encoder on every Windows target.
RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then \
      MINGW_PREFIX=x86_64-w64-mingw32; \
    else \
      MINGW_PREFIX=aarch64-w64-mingw32; \
    fi; \
    printf '%s\n' \
      "[binaries]" \
      "c = '${MINGW_PREFIX}-gcc'" \
      "cpp = '${MINGW_PREFIX}-g++'" \
      "ar = '${MINGW_PREFIX}-ar'" \
      "strip = '${MINGW_PREFIX}-strip'" \
      "windres = '${MINGW_PREFIX}-windres'" \
      "pkg-config = 'pkg-config'" \
      "[built-in options]" \
      "c_link_args = ['-static-libgcc', '-Wl,-Bstatic,-lwinpthread,-Bdynamic']" \
      "cpp_link_args = ['-static-libgcc', '-static-libstdc++', '-Wl,-Bstatic,-lwinpthread,-Bdynamic']" \
      "[host_machine]" \
      "system = 'windows'" \
      "cpu_family = '$( [ "$ARCH" = "amd64" ] && echo x86_64 || echo aarch64 )'" \
      "cpu = '$( [ "$ARCH" = "amd64" ] && echo x86_64 || echo aarch64 )'" \
      "endian = 'little'" \
      > /tmp/mingw-cross.ini; \
    git clone --depth 1 --branch v2.6.0 https://github.com/cisco/openh264.git /tmp/openh264; \
    cd /tmp/openh264; \
    meson setup build --cross-file /tmp/mingw-cross.ini --prefix="/usr/${MINGW_PREFIX}" --libdir=lib; \
    ninja -C build install; \
    cd /build && rm -rf /tmp/openh264 /tmp/mingw-cross.ini

# libopus (BSD-licensed), cross-built for mingw for Opus audio encode/decode.
# Uses the release tarball (which ships a pre-generated ./configure), not a
# git clone of the tag -- the opus git tree requires autoreconf (autoconf/
# automake/libtool, and a network fetch of the download-the-latest-model
# tool) to produce configure, none of which are installed in this image.
#
# arm64 needs --disable-rtcd: opus's ARM NEON run-time CPU detection
# (celt/arm/armcpu.c) has no implementation for the Windows-on-ARM target
# llvm-mingw builds for, so it fails to compile ("no CPU detection method
# available for your platform") unless run-time CPU detection is disabled
# in favor of the compile-time-selected NEON feature set.
RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then \
      MINGW_PREFIX=x86_64-w64-mingw32; \
    else \
      MINGW_PREFIX=aarch64-w64-mingw32; \
    fi; \
    curl -L -o /tmp/opus.tar.gz https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz; \
    mkdir /tmp/opus; \
    tar -xzf /tmp/opus.tar.gz -C /tmp/opus --strip-components=1; \
    rm /tmp/opus.tar.gz; \
    cd /tmp/opus; \
    if [ "$ARCH" = "arm64" ]; then EXTRA_OPUS_FLAGS="--disable-rtcd"; else EXTRA_OPUS_FLAGS=""; fi; \
    CFLAGS="-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0" ./configure \
      --host="${MINGW_PREFIX}" \
      --prefix="/usr/${MINGW_PREFIX}" \
      --disable-shared \
      --enable-static \
      --disable-doc \
      --disable-extra-programs \
      --with-pic \
      $EXTRA_OPUS_FLAGS; \
    make -j"$(nproc)" && make install; \
    cd /build && rm -rf /tmp/opus

COPY ffmpeg-src/ /build/

# Apply source patches to ffmpeg-src before configuring. Patches are kept
# outside the ffmpeg-src submodule and re-applied fresh on every build so
# they survive the daily automated submodule version bumps (see
# .github/workflows/check-ffmpeg-release.yml); if upstream changes enough to
# break a patch, fail the build loudly here rather than silently shipping
# unpatched behavior.
COPY patches/ddagrab-uac-recovery.patch /tmp/ddagrab-uac-recovery.patch
RUN cd /build && \
    (git apply --check /tmp/ddagrab-uac-recovery.patch 2>/tmp/patch-check.log && \
     git apply /tmp/ddagrab-uac-recovery.patch && \
     echo "ddagrab-uac-recovery.patch applied successfully") || \
    (echo "FATAL: ddagrab-uac-recovery.patch failed to apply -- upstream ffmpeg-src/libavfilter/vsrc_ddagrab.c likely changed. Manual patch rebase required." >&2; \
     cat /tmp/patch-check.log >&2; exit 1)

# Fixes scale_d3d11 (GPU BGRA->NV12 conversion used ahead of hardware H.264/
# HEVC encoders) silently defaulting to the wrong color range, which crushes
# blacks / fades colors once the encoded video is decoded and played back
# downstream. See patch header for full explanation.
COPY patches/scale_d3d11-colorspace.patch /tmp/scale_d3d11-colorspace.patch
RUN cd /build && \
    (git apply --check /tmp/scale_d3d11-colorspace.patch 2>/tmp/patch-check2.log && \
     git apply /tmp/scale_d3d11-colorspace.patch && \
     echo "scale_d3d11-colorspace.patch applied successfully") || \
    (echo "FATAL: scale_d3d11-colorspace.patch failed to apply -- upstream ffmpeg-src/libavfilter/vf_scale_d3d11.c likely changed. Manual patch rebase required." >&2; \
     cat /tmp/patch-check2.log >&2; exit 1)

# Adds ddagrab's output_name option (select a monitor by its stable DXGI
# DeviceName, e.g. \\.\DISPLAY1, instead of the enumeration-order-dependent
# output_idx). Depends on the UAC recovery patch above (extends
# recover_duplication()), so must be applied after it.
COPY patches/ddagrab-output-name.patch /tmp/ddagrab-output-name.patch
RUN cd /build && \
    (git apply --check /tmp/ddagrab-output-name.patch 2>/tmp/patch-check3.log && \
     git apply /tmp/ddagrab-output-name.patch && \
     echo "ddagrab-output-name.patch applied successfully") || \
    (echo "FATAL: ddagrab-output-name.patch failed to apply -- upstream ffmpeg-src/libavfilter/vsrc_ddagrab.c likely changed. Manual patch rebase required." >&2; \
     cat /tmp/patch-check3.log >&2; exit 1)

# Adds a native "wasapi" avdevice indev (libavdevice/wasapi.c, new file --
# doesn't touch any existing FFmpeg code beyond a few one-line registration
# entries) that captures the default render endpoint's output via WASAPI
# loopback, replacing the standalone wasapi_loopback.exe + stdin-pipe
# approach with a proper `-f wasapi -i default` input.
COPY patches/wasapi-indev.patch /tmp/wasapi-indev.patch
RUN cd /build && \
    (git apply --check /tmp/wasapi-indev.patch 2>/tmp/patch-check4.log && \
     git apply /tmp/wasapi-indev.patch && \
     echo "wasapi-indev.patch applied successfully") || \
    (echo "FATAL: wasapi-indev.patch failed to apply -- upstream ffmpeg-src configure/libavdevice files likely changed. Manual patch rebase required." >&2; \
     cat /tmp/patch-check4.log >&2; exit 1)

# ---------------------------------------------------------------------------
# configure flags — edit below to add/remove features for the Windows build.
#
# Minimal build: H.264/H.265 hardware encode + openh264 (H.264 software)
# fallback, plus Opus audio encode/decode and a native WASAPI loopback
# capture indev (patches/wasapi-indev.patch, see comment above) so system/
# application audio can be recorded with a plain `-f wasapi -i default`
# input. QSV (libvpl) cross-build for mingw is not wired up here — it needs
# a Windows-targeted libvpl build, which is nontrivial to cross-compile.
# VAAPI is Linux-only, excluded.
#
# No -flto here: linking libswscale with LTO enabled against this mingw
# toolchain fails with "undefined reference" to symbols defined in its x86
# NASM assembly objects (e.g. bF8/mask24r/mul16_mid) -- the LTO plugin can't
# see across the asm/C boundary the way it can on the Linux/macOS builds.
# ---------------------------------------------------------------------------
RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then \
      CROSS_PREFIX=x86_64-w64-mingw32-; \
      TARGET_ARCH=x86_64; \
      MINGW_PREFIX=x86_64-w64-mingw32; \
    elif [ "$ARCH" = "arm64" ]; then \
      CROSS_PREFIX=aarch64-w64-mingw32-; \
      TARGET_ARCH=aarch64; \
      MINGW_PREFIX=aarch64-w64-mingw32; \
    else \
      echo "Unsupported ARCH: $ARCH" >&2; exit 1; \
    fi; \
    export PKG_CONFIG_LIBDIR="/usr/${MINGW_PREFIX}/lib/pkgconfig"; \
    export PKG_CONFIG_PATH=; \
    ./configure \
      --prefix=/dist \
      --target-os=mingw32 \
      --arch="$TARGET_ARCH" \
      --cross-prefix="$CROSS_PREFIX" \
      --enable-cross-compile \
      --pkg-config=pkg-config \
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
      --enable-d3d11va \
      --enable-filter=ddagrab \
      --enable-filter=scale_d3d11 \
      --enable-avdevice \
      --enable-indev=wasapi \
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
      --enable-libopenh264 \
      --enable-libopus \
      --enable-encoder=libopenh264 \
      --enable-encoder=libopus \
      --enable-decoder=libopus \
      $( [ "$ARCH" = "amd64" ] && echo \
           --enable-ffnvcodec \
           --enable-amf \
           --enable-encoder=h264_nvenc \
           --enable-encoder=hevc_nvenc \
           --enable-encoder=h264_amf \
           --enable-encoder=hevc_amf ) \
      --extra-cflags="-Os -ffunction-sections -fdata-sections" \
      --extra-ldflags="-Wl,--gc-sections -static-libgcc -static-libstdc++" \
      --extra-libs="-lm -ldxgi -Wl,-Bstatic,-lwinpthread,-Bdynamic"

RUN make -j"$(nproc)" && make install

# ffmpeg.exe dynamically loads libopenh264-*.dll at runtime (--enable-libopenh264
# links it as a shared library, not statically), but `make install` only
# installs FFmpeg's own libraries into --prefix=/dist -- it doesn't pull in
# openh264's .dll from the mingw sysroot. Without this, ffmpeg.exe fails to
# start with "libopenh264-7.dll not found" as soon as it's moved outside the
# build container.
#
# libopenh264 also still depends on libwinpthread-1.dll at runtime: its
# meson.build pulls in Meson's `dependency('threads')`, whose link flags
# Ninja places after our cross-file's link_args, so the earlier
# -Wl,-Bstatic,-lwinpthread,-Bdynamic toggle can't reach it (unlike
# libgcc_s_seh/libstdc++, which the same cross-file successfully statically
# links). Ship libwinpthread-1.dll alongside instead of fighting Meson's
# link ordering.
RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then MINGW_PREFIX=x86_64-w64-mingw32; else MINGW_PREFIX=aarch64-w64-mingw32; fi; \
    cp "/usr/${MINGW_PREFIX}/bin/libopenh264"*.dll /dist/bin/; \
    winpthread_dll=$(find "/usr/${MINGW_PREFIX}" /opt/llvm-mingw -iname 'libwinpthread-*.dll' 2>/dev/null | head -n1); \
    if [ -z "$winpthread_dll" ]; then \
      echo "FATAL: libwinpthread-*.dll not found under /usr/${MINGW_PREFIX} or /opt/llvm-mingw" >&2; exit 1; \
    fi; \
    cp "$winpthread_dll" /dist/bin/

RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then STRIP=x86_64-w64-mingw32-strip; else STRIP=aarch64-w64-mingw32-strip; fi; \
    "$STRIP" --strip-unneeded /dist/bin/* /dist/lib/*.dll || true

# ddagrab の手動検証用テストスクリプト。bin/ と同階層に置き、ダブルクリック
# (.py が Python に関連付けられている環境) または `python test-ddagrab-record.py`
# で bin/ffmpeg.exe を直接使って H.264/MP4 録画を試せるようにする。
# .py が関連付けられていない環境でも確実にダブルクリック起動できるよう、
# py ランチャー/python コマンドを順に試す .bat ラッパーも同梱する。
COPY scripts/test-ddagrab-record.py /dist/test-ddagrab-record.py
COPY scripts/run-test-ddagrab-record.bat /dist/run-test-ddagrab-record.bat
