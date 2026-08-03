#!/usr/bin/env python3
"""Verification script for the ddagrab_vp9_tcp example.

Runs the example for a fixed duration, then uses ffprobe to check:
  1. out.ts's video codec is vp9.
  2. I-frames appear at points other than the natural GOP boundary
     (-g 300, ~10s @ 30fps), evidence that -idr_control_socket forced
     extra keyframes (the example sends a force_idr request every 5s).

Requires ffprobe on PATH -- NOT included in this project's minimal ffmpeg
build (--disable-ffprobe). Install a full FFmpeg build separately, e.g.:
    brew install ffmpeg          # macOS
    sudo apt-get install ffmpeg  # Debian/Ubuntu
"""

import csv
import io
import shutil
import subprocess
import sys
import time
from pathlib import Path

RUN_SECONDS = 20
OUT_FILE = Path(__file__).parent / "out.ts"
IDR_INTERVAL_S = 5
NATURAL_GOP_S = 10  # -g 300 @ 30fps
TOLERANCE_S = 1.5


def require_ffprobe():
    if shutil.which("ffprobe") is None:
        print(
            "ERROR: ffprobe not found on PATH.\n"
            "This project's ffmpeg build is minimal and does not include ffprobe "
            "(--disable-ffprobe). Install a full FFmpeg build separately, e.g.:\n"
            "  brew install ffmpeg          # macOS\n"
            "  sudo apt-get install ffmpeg  # Debian/Ubuntu\n",
            file=sys.stderr,
        )
        sys.exit(1)


def run_example():
    print(f"Running example for {RUN_SECONDS}s...")
    proc = subprocess.Popen(
        ["cargo", "run", "--release"],
        cwd=Path(__file__).parent,
    )
    try:
        time.sleep(RUN_SECONDS)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def check_codec():
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=nk=1:nw=1",
            str(OUT_FILE),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    codec = result.stdout.strip()
    print(f"Detected video codec: {codec}")
    if codec != "vp9":
        print(f"FAIL: expected codec 'vp9', got '{codec}'", file=sys.stderr)
        sys.exit(1)
    print("PASS: video codec is vp9")


def check_forced_idr():
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "frame=pict_type,pkt_pts_time",
            "-of", "csv=p=0",
            str(OUT_FILE),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    i_frame_times = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) < 2:
            continue
        pict_type, pts_time = row[0], row[1]
        if pict_type == "I":
            try:
                i_frame_times.append(float(pts_time))
            except ValueError:
                continue

    print(f"I-frames detected at: {i_frame_times}")

    if not i_frame_times:
        print("FAIL: no I-frames found in output", file=sys.stderr)
        sys.exit(1)

    forced = [
        t for t in i_frame_times
        if abs((t % NATURAL_GOP_S)) > TOLERANCE_S
        and abs((t % NATURAL_GOP_S) - NATURAL_GOP_S) > TOLERANCE_S
    ]

    if forced:
        for t in forced:
            print(f"PASS: forced IDR detected at {t:.2f}s (off natural GOP boundary)")
    else:
        print(
            "FAIL: no I-frames found off the natural GOP boundary -- "
            "-idr_control_socket forcing does not appear to be working",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    require_ffprobe()
    run_example()

    if not OUT_FILE.exists() or OUT_FILE.stat().st_size == 0:
        print(f"FAIL: {OUT_FILE} was not created or is empty", file=sys.stderr)
        sys.exit(1)

    check_codec()
    check_forced_idr()
    print("All checks passed.")


if __name__ == "__main__":
    main()
