FROM debian:bookworm-slim

ARG ARCH=amd64

RUN dpkg --add-architecture arm64 && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    yasm \
    nasm \
    git \
    curl \
    ca-certificates \
    libva-dev \
    libxcb1-dev \
    libxcb-shm0-dev \
    libxcb-xfixes0-dev \
    libdrm-dev \
    gcc-aarch64-linux-gnu \
    g++-aarch64-linux-gnu \
    crossbuild-essential-arm64 \
    libva-dev:arm64 \
    libdrm-dev:arm64 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# NVIDIA NVENC headers (amd64 only, header-only package)
RUN git clone --depth 1 https://github.com/FFmpeg/nv-codec-headers.git /tmp/nv-codec-headers \
    && make -C /tmp/nv-codec-headers install \
    && rm -rf /tmp/nv-codec-headers

# openh264 (BSD-licensed H.264 software encoder; used as a fallback encoder
# on every platform, and as the only encoder on arm64 where no hardware
# H.264/H.265 encoder is realistically cross-buildable/available)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y meson ninja-build && rm -rf /var/lib/apt/lists/*

RUN printf '%s\n' \
      "[binaries]" \
      "c = 'aarch64-linux-gnu-gcc'" \
      "cpp = 'aarch64-linux-gnu-g++'" \
      "ar = 'aarch64-linux-gnu-ar'" \
      "strip = 'aarch64-linux-gnu-strip'" \
      "pkg-config = 'pkg-config'" \
      "[host_machine]" \
      "system = 'linux'" \
      "cpu_family = 'aarch64'" \
      "cpu = 'aarch64'" \
      "endian = 'little'" \
      > /tmp/aarch64-cross.ini

RUN set -eux; \
    git clone --depth 1 --branch v2.6.0 https://github.com/cisco/openh264.git /tmp/openh264; \
    cd /tmp/openh264; \
    if [ "$ARCH" = "arm64" ]; then \
      meson setup build --cross-file /tmp/aarch64-cross.ini --prefix=/usr/aarch64-linux-gnu --libdir=lib; \
    else \
      meson setup build --prefix=/usr; \
    fi; \
    ninja -C build install; \
    cd /build && rm -rf /tmp/openh264 /tmp/aarch64-cross.ini

# Intel oneVPL (libvpl) for QSV — Ubuntu 22.04's apt package (2022.1.0) is
# older than the >= 2.6 FFmpeg requires, so build it from source.
RUN git clone --depth 1 --branch v2.13.0 https://github.com/intel/libvpl.git /tmp/libvpl \
    && cmake -S /tmp/libvpl -B /tmp/libvpl/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/libvpl/build -j"$(nproc)" \
    && cmake --install /tmp/libvpl/build \
    && rm -rf /tmp/libvpl

# AMD AMF headers (header-only)
RUN git clone --depth 1 https://github.com/GPUOpen-LibrariesAndSDKs/AMF.git /tmp/AMF \
    && mkdir -p /usr/include/AMF \
    && cp -r /tmp/AMF/amf/public/include/* /usr/include/AMF/ \
    && rm -rf /tmp/AMF

# libopus (BSD-licensed) for Opus audio encode/decode. Uses the release
# tarball (ships a pre-generated ./configure) rather than a git clone of the
# tag, which would need autoreconf (autoconf/automake/libtool + a network
# fetch) to produce configure.
RUN set -eux; \
    curl -L -o /tmp/opus.tar.gz https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz; \
    mkdir /tmp/opus; \
    tar -xzf /tmp/opus.tar.gz -C /tmp/opus --strip-components=1; \
    rm /tmp/opus.tar.gz; \
    cd /tmp/opus; \
    mkdir build-amd64; \
    (cd build-amd64 && ../configure --prefix=/usr --disable-shared --enable-static --disable-doc --disable-extra-programs --with-pic && make -j"$(nproc)" && make install); \
    mkdir build-arm64; \
    (cd build-arm64 && CFLAGS="-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0" ../configure --host=aarch64-linux-gnu --prefix=/usr/aarch64-linux-gnu --disable-shared --enable-static --disable-doc --disable-extra-programs --with-pic && make -j"$(nproc)" && make install); \
    cd /build && rm -rf /tmp/opus

# libvpx (BSD-licensed) for VP9 software encode. Uses the git tag directly --
# unlike opus, libvpx's repo ships a pre-generated ./configure so no
# autoreconf step is needed. Built as a static lib (--disable-shared): it's a
# BSD build-time codec dependency, not something subject to the LGPL
# shared-linking requirement that governs ffmpeg's own libs, so there's no
# runtime .so to ship alongside the ffmpeg binary (unlike openh264).
RUN set -eux; \
    git clone --depth 1 --branch v1.15.0 https://github.com/webmproject/libvpx.git /tmp/libvpx; \
    cd /tmp/libvpx; \
    mkdir build-amd64; \
    (cd build-amd64 && ../configure --target=x86_64-linux-gcc --prefix=/usr --disable-shared --enable-static --disable-examples --disable-unit-tests --disable-tools --disable-docs --enable-vp9 --disable-vp8 --enable-pic && make -j"$(nproc)" && make install); \
    mkdir build-arm64; \
    (cd build-arm64 && CROSS=aarch64-linux-gnu- ../configure --target=arm64-linux-gcc --prefix=/usr/aarch64-linux-gnu --disable-shared --enable-static --disable-examples --disable-unit-tests --disable-tools --disable-docs --enable-vp9 --disable-vp8 --enable-pic && make -j"$(nproc)" && make install); \
    cd /build && rm -rf /tmp/libvpx

COPY ffmpeg-src/ /build/

# Apply source patches to ffmpeg-src before configuring. Patches are kept
# outside the ffmpeg-src submodule and re-applied fresh on every build so
# they survive the daily automated submodule version bumps (see
# .github/workflows/check-ffmpeg-release.yml); if upstream changes enough to
# break a patch, fail the build loudly here rather than silently shipping
# unpatched behavior.
#
# Only idr-control-socket.patch applies here: the ddagrab/wasapi patches
# touch Windows-only (DXGI/WASAPI) code and are applied in
# docker/windows/Dockerfile instead.
COPY patches/idr-control-socket.patch /tmp/idr-control-socket.patch
RUN cd /build && \
    (git apply --check /tmp/idr-control-socket.patch 2>/tmp/patch-check.log && \
     git apply /tmp/idr-control-socket.patch && \
     echo "idr-control-socket.patch applied successfully") || \
    (echo "FATAL: idr-control-socket.patch failed to apply -- upstream ffmpeg-src/fftools likely changed. Manual patch rebase required." >&2; \
     cat /tmp/patch-check.log >&2; exit 1)

# ---------------------------------------------------------------------------
# configure flags — edit below to add/remove features for the Linux build.
#
# Minimal build: H.264/H.265 hardware encode only, no audio, no software
# decoders. Input is expected to be raw video (e.g. from x11grab/kmsgrab
# screen capture) piped straight into a hardware encoder.
#
# No -flto: linking libswscale as a shared object with LTO enabled fails
# ("relocation ... can not be used when making a shared object; recompile
# with -fPIC") because LTO recompiles its x86 NASM-derived C fallback/data
# objects without -fPIC awareness. Same underlying issue as the Windows
# build, just surfacing as a PIC/relocation error here instead of an
# undefined-reference one.
# ---------------------------------------------------------------------------
RUN set -eux; \
    COMMON_FLAGS=" \
      --prefix=/dist \
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
      --disable-avdevice \
      --enable-pthreads \
      --enable-protocol=file \
      --enable-protocol=pipe \
      --enable-protocol=tcp \
      --enable-protocol=udp \
      --enable-protocol=rtmp \
      --enable-protocol=rtp \
      --enable-demuxer=rawvideo \
      --enable-decoder=rawvideo \
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
      --enable-libopus \
      --enable-encoder=libopus \
      --enable-decoder=libopus \
      --enable-libvpx \
      --enable-encoder=libvpx_vp9 \
      --extra-cflags=\"-Os -ffunction-sections -fdata-sections\" \
      --extra-ldflags=\"-Wl,--gc-sections\" \
      --extra-libs=\"-lm\" \
    "; \
    if [ "$ARCH" = "amd64" ]; then \
      eval ./configure $COMMON_FLAGS \
        --target-os=linux \
        --arch=x86_64 \
        --enable-avdevice \
        --enable-indev=xcbgrab \
        --enable-indev=kmsgrab \
        --enable-ffnvcodec \
        --enable-vaapi \
        --enable-libvpl \
        --enable-amf \
        --enable-libopenh264 \
        --enable-encoder=h264_nvenc \
        --enable-encoder=hevc_nvenc \
        --enable-encoder=h264_vaapi \
        --enable-encoder=hevc_vaapi \
        --enable-encoder=h264_qsv \
        --enable-encoder=hevc_qsv \
        --enable-encoder=h264_amf \
        --enable-encoder=hevc_amf \
        --enable-encoder=libopenh264; \
    elif [ "$ARCH" = "arm64" ]; then \
      export PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/aarch64-linux-gnu/lib/pkgconfig; \
      export PKG_CONFIG_PATH=; \
      eval ./configure $COMMON_FLAGS \
        --target-os=linux \
        --arch=aarch64 \
        --cross-prefix=aarch64-linux-gnu- \
        --enable-cross-compile \
        --pkg-config=pkg-config \
        --enable-avdevice \
        --enable-indev=kmsgrab \
        --enable-vaapi \
        --enable-libopenh264 \
        --enable-encoder=h264_vaapi \
        --enable-encoder=hevc_vaapi \
        --enable-encoder=libopenh264; \
    else \
      echo "Unsupported ARCH: $ARCH" >&2; exit 1; \
    fi

RUN make -j"$(nproc)" && make install

RUN set -eux; \
    if [ "$ARCH" = "amd64" ]; then STRIP=strip; else STRIP=aarch64-linux-gnu-strip; fi; \
    "$STRIP" --strip-unneeded /dist/bin/* /dist/lib/*.so* || true
