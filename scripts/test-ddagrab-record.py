"""
ddagrab (Windows Desktop Duplication) でデスクトップ映像を、wasapi (ネイティブ
avdevice indev) でシステム音声(WASAPIループバック)をキャプチャし、H.264/H.265
映像 + Opus 音声の MP4 として録画するテストスクリプト。

同じフォルダの bin\\ffmpeg.exe を使う。ddagrab は -filter_complex 経由で
入力なしのフィルタグラフとして起動するため、libavdevice (lavfi インデバイス)
を有効化していない最小構成ビルドでもそのまま動く。音声は `-f wasapi -i default`
(patches/wasapi-indev.patch で追加したネイティブ WASAPI ループバック indev)
を ffmpeg の通常の追加入力として渡すだけで、別プロセスやパイプは一切不要。

キャプチャするモニタは --output-idx (列挙順のインデックス、モニタの
抜き差しや再検出で変わりうる) または --output-name (DXGI の DeviceName、
例: \\\\.\\DISPLAY1。ddagrab の output_name オプション、要
patches/ddagrab-output-name.patch 適用ビルド) のどちらかで指定する。
--output-name を指定した場合はそちらが優先される。

コーデックは既定で H.264、--codec h265 で H.265(HEVC) に切り替えられる。
エンコーダは明示しない限り、コーデックごとに nvenc -> amf -> (H.264のみ)
openh264 software の順で自動フォールバックする
(HEVC はこのビルドにソフトウェアエンコーダを含まないため、
 対応するハードウェアエンコーダが無い場合はエラーになる)。

--- 色範囲 (full range / limited range) について ---
ddagrab が出す BGRA は full range (0-255) だが、YUV 系エンコーダは
limited range (16-235) を前提にすることが多く、これを取り違えると
capture -> encode -> decode -> 再生 の経路で色が沈む/褪せる (黒が浮く、
コントラストが変わる) 症状が出る。

  * h264_nvenc / h264_amf / hevc_nvenc / hevc_amf (GPU ハードウェアパス):
    ddagrab が出す D3D11 ハードウェアフレーム (BGRA, full range) を
    hwdownload せず、そのままエンコーダに渡す (GPU->GPU、変換ステップなし)。
    実際の pixel データの range 変換はエンコーダ内部の RGB->YUV 変換に
    任せ、そのフレームが full range であることをビットストリーム/
    コンテナのメタデータ (-color_range pc 等) で明示することで、
    デコード側 (再生プレイヤー) が正しく解釈できるようにする。
    以前は scale_d3d11 フィルタ (D3D11 Video Processor) で GPU 上の
    range 変換を試みたが、環境によっては scale_d3d11 が要求する NV12
    ハードウェアフレームの確保自体が D3D11 の CreateTexture2D で
    E_INVALIDARG になり失敗するケースが確認されたため廃止した。

  * libopenh264 (CPU ソフトウェアエンコーダ):
    CPU 側のフレームが必要なため hwdownload で明示的に落とし、
    swscale ベースの scale フィルタで range 変換 (in_range=full:out_range=tv)
    を行ってから渡す。ハードウェアエンコーダが使えない環境向けのフォールバック。

UAC の同意プロンプト（secure desktop への遷移）を挟んでも録画が継続する
かどうかを確認する目的にも使える。録画中に手動で UAC プロンプトを
発生させる操作（例: 管理者権限が必要な操作を実行する）を行い、録画停止後に
出力ファイルが途切れず再生できるかを確認する。

ダブルクリックで起動した場合は、対話的に録画時間・出力先・コーデック・
エンコーダ・音声有無を確認してから録画を開始する。コマンドライン引数を
渡した場合は非対話的に実行する（引数は下記 --help を参照）。
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ENCODER_PRIORITY = {
    "h264": ["h264_nvenc", "h264_amf", "libopenh264"],
    "h265": ["hevc_nvenc", "hevc_amf"],
}

# GPU ハードウェアパス (hwdownload なし、scale_d3d11 で GPU 上 range 変換)
# を使うエンコーダ。それ以外 (libopenh264) は CPU パス (hwdownload + swscale)。
GPU_PATH_ENCODERS = {"h264_nvenc", "h264_amf", "hevc_nvenc", "hevc_amf"}


def resolve_ffmpeg_path(explicit_path):
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"指定された ffmpeg.exe が見つかりません: {path}")
        return path.resolve()

    script_dir = Path(__file__).resolve().parent
    candidate = script_dir / "bin" / "ffmpeg.exe"
    if candidate.is_file():
        return candidate.resolve()

    raise FileNotFoundError(
        f"ffmpeg.exe が見つかりません: {candidate}\n"
        "--ffmpeg-path で明示的にパスを指定してください。"
    )


def get_available_encoders(ffmpeg_path):
    result = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout + result.stderr


def select_encoder(ffmpeg_path, codec, requested):
    encoder_list = get_available_encoders(ffmpeg_path)
    priority = ENCODER_PRIORITY[codec]

    if requested:
        if re.search(re.escape(requested), encoder_list):
            return requested
        raise ValueError(
            f"指定されたエンコーダ '{requested}' はこのビルドで有効になっていません。"
            "'ffmpeg -encoders' の出力を確認してください。"
        )

    for enc in priority:
        if re.search(enc, encoder_list):
            print(f"エンコーダを自動選択: {enc}")
            return enc

    raise RuntimeError(
        f"利用可能な{codec.upper()}エンコーダが見つかりませんでした "
        f"({' / '.join(priority)})。"
    )


def escape_filter_option_value(value):
    # ffmpeg のフィルタグラフ構文では \ と : と ' が特別な意味を持つため、
    # output_name (例: \\.\DISPLAY1) をそのまま埋め込むと壊れる。
    # バックスラッシュでエスケープする。
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def get_video_filter_complex(output_idx, output_name, framerate, encoder_name):
    if output_name:
        # output_name はモニタの抜き差しや再検出があっても output_idx
        # (単なる列挙順) より安定した識別子 (DXGI DeviceName) で
        # モニタを指定する。output_idx より優先される。
        escaped = escape_filter_option_value(output_name)
        ddagrab = f"ddagrab=output_name='{escaped}':framerate={framerate}"
    else:
        ddagrab = f"ddagrab=output_idx={output_idx}:framerate={framerate}"

    if encoder_name in GPU_PATH_ENCODERS:
        # hwdownload なし、変換フィルタなしでそのままエンコーダに渡す
        # (GPU->GPU ゼロコピー)。full range であることは
        # get_video_encoder_args() 側の -color_range pc で明示する。
        return f"{ddagrab}[vout]"

    # libopenh264 (CPU ソフトウェアエンコーダ) は CPU 側のフレームが必要なため
    # hwdownload で明示的に落とし、scale (swscale) で range 変換してから渡す。
    return (
        f"{ddagrab},hwdownload,format=bgra,"
        f"scale=in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,"
        f"format=yuv420p[vout]"
    )


# GPU パス: ddagrab の生フレーム (BGRA, full range) をそのまま渡すため、
# ビットストリーム/コンテナのメタデータで "full range" であることを明示する
# (-color_range pc)。実際の RGB->YUV 変換はエンコーダ内部に任せる。
GPU_PATH_COLOR_RANGE_ARGS = [
    "-color_range", "pc", "-colorspace", "bt709",
    "-color_primaries", "bt709", "-color_trc", "bt709",
]

# CPU パス: scale フィルタで既に limited range (tv) に変換済みなので、
# そちらのメタデータを明示する。
CPU_PATH_COLOR_RANGE_ARGS = [
    "-color_range", "tv", "-colorspace", "bt709",
    "-color_primaries", "bt709", "-color_trc", "bt709",
]


def get_video_encoder_args(encoder_name):
    if encoder_name == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "8M"] + GPU_PATH_COLOR_RANGE_ARGS
    if encoder_name == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-b:v", "8M"] + GPU_PATH_COLOR_RANGE_ARGS
    if encoder_name == "libopenh264":
        return ["-c:v", "libopenh264", "-b:v", "8M"] + CPU_PATH_COLOR_RANGE_ARGS
    if encoder_name == "hevc_nvenc":
        return ["-c:v", "hevc_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "8M"] + GPU_PATH_COLOR_RANGE_ARGS
    if encoder_name == "hevc_amf":
        return ["-c:v", "hevc_amf", "-quality", "balanced", "-b:v", "8M"] + GPU_PATH_COLOR_RANGE_ARGS
    raise ValueError(f"未対応のエンコーダです: {encoder_name}")


def get_audio_input_args(device_name):
    # patches/wasapi-indev.patch で追加したネイティブ WASAPI ループバック
    # indev。device_name 省略時は "default" でシステムのデフォルト再生
    # デバイスをそのままループバック録音する。サンプルレート/チャンネル数は
    # デバイスの mix format に従うため指定不要 (共有モードでは変更できない)。
    return ["-f", "wasapi", "-i", device_name or "default"]


def get_audio_encoder_args():
    return ["-c:a", "libopus", "-b:a", "128k", "-application", "audio"]


def prompt_int(message, default):
    raw = input(f"{message} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"数値を入力してください。デフォルト値 {default} を使用します。")
        return default


def prompt_str(message, default):
    raw = input(f"{message} [{default}]: ").strip()
    return raw if raw else default


def prompt_bool(message, default):
    default_label = "y" if default else "n"
    raw = input(f"{message} (y/n) [{default_label}]: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


def run_interactive_prompts(args):
    print("=== ddagrab 録画テスト (対話モード) ===")
    print("Enter キーのみで [] 内のデフォルト値を使用します。\n")

    args.duration = prompt_int("録画時間 (秒)", args.duration)
    output_name_input = prompt_str(
        "モニタのデバイス名 (例: \\\\.\\DISPLAY1、空欄で index 指定を使う)",
        args.output_name or "",
    )
    if output_name_input:
        args.output_name = output_name_input
    else:
        args.output_idx = prompt_int("モニタ index (0=プライマリ)", args.output_idx)
    args.framerate = prompt_int("フレームレート (fps)", args.framerate)
    args.codec = prompt_str("コーデック (h264 / h265)", args.codec)

    encoder_default = args.encoder if args.encoder else "自動選択"
    encoder_input = prompt_str(
        f"エンコーダ ({' / '.join(ENCODER_PRIORITY[args.codec])} / 空欄で自動選択)",
        encoder_default,
    )
    if encoder_input and encoder_input != "自動選択":
        args.encoder = encoder_input

    args.with_audio = prompt_bool("システム音声も録音する (WASAPI ループバック + Opus)", args.with_audio)

    output_default = str(args.output_path) if args.output_path else "(自動生成)"
    output_input = prompt_str("出力ファイルパス (空欄で自動生成)", output_default)
    if output_input and output_input != "(自動生成)":
        args.output_path = Path(output_input)

    print()
    return args


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="ddagrab で H.264/H.265 + Opus 音声 + MP4 録画するテストスクリプト"
    )
    parser.add_argument("--ffmpeg-path", dest="ffmpeg_path", default=None)
    parser.add_argument("--output-path", dest="output_path", type=Path, default=None)
    parser.add_argument("--duration", type=int, default=30, help="録画時間 (秒)")
    parser.add_argument(
        "--output-idx", dest="output_idx", type=int, default=0, help="ddagrab の output_idx"
    )
    parser.add_argument(
        "--output-name",
        dest="output_name",
        default=None,
        help=r"ddagrab の output_name (例: \\.\DISPLAY1)。指定時は --output-idx より優先される",
    )
    parser.add_argument("--framerate", type=int, default=30)
    parser.add_argument(
        "--codec",
        choices=list(ENCODER_PRIORITY.keys()),
        default="h264",
        help="録画するコーデック (省略時は h264)",
    )
    parser.add_argument(
        "--encoder",
        default=None,
        help="使用するエンコーダを明示する場合に指定 (省略時はコーデックに応じて自動選択)",
    )
    parser.add_argument(
        "--with-audio",
        dest="with_audio",
        action="store_true",
        default=False,
        help="wasapi indev でシステム音声も録音し、Opus で MP4 に格納する",
    )
    parser.add_argument(
        "--audio-device",
        dest="audio_device",
        default=None,
        help="wasapi indev に渡すデバイス ID (省略時はシステムのデフォルト再生デバイス)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="対話プロンプトを出さずに即座に実行する",
    )
    return parser.parse_args(argv)


def main():
    argv = sys.argv[1:]
    args = parse_args(argv)

    # 引数なしでダブルクリック起動された場合は対話モードにする。
    if not argv and not args.non_interactive:
        args = run_interactive_prompts(args)

    if args.codec not in ENCODER_PRIORITY:
        raise ValueError(f"未対応のコーデックです: {args.codec} (h264 / h265 のみ対応)")

    if args.encoder and args.encoder not in ENCODER_PRIORITY[args.codec]:
        raise ValueError(
            f"エンコーダ '{args.encoder}' はコーデック '{args.codec}' に対応していません。"
            f"対応エンコーダ: {' / '.join(ENCODER_PRIORITY[args.codec])}"
        )

    ffmpeg_path = resolve_ffmpeg_path(args.ffmpeg_path)
    print(f"使用する ffmpeg.exe: {ffmpeg_path}")

    output_path = args.output_path
    if not output_path:
        # カレントディレクトリではなく、このスクリプト自身のあるフォルダを
        # 基準にする。.bat ラッパー経由 (特に UNC パス上) で起動された場合、
        # 呼び出し元プロセスのカレントディレクトリが意図しない場所
        # (UNC パスを避けて C:\Windows 等) になっていることがあるため。
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = Path(__file__).resolve().parent / f"ddagrab-test-{timestamp}.mp4"
    output_path = output_path.resolve()

    selected_encoder = select_encoder(ffmpeg_path, args.codec, args.encoder)
    video_filter_complex = get_video_filter_complex(
        args.output_idx, args.output_name, args.framerate, selected_encoder
    )
    video_encoder_args = get_video_encoder_args(selected_encoder)

    print()
    print("=== ddagrab 録画テスト ===")
    if args.output_name:
        print(f"  モニタ       : {args.output_name}")
    else:
        print(f"  モニタ index : {args.output_idx}")
    print(f"  フレームレート: {args.framerate} fps")
    print(f"  録画時間     : {args.duration} 秒")
    print(f"  コーデック   : {args.codec}")
    print(f"  エンコーダ   : {selected_encoder}")
    print(f"  音声        : {'あり (WASAPI ループバック + Opus)' if args.with_audio else 'なし'}")
    print(f"  出力先       : {output_path}")
    print()
    print("録画中にUACの同意プロンプト（例:管理者権限が必要な操作の実行）を")
    print("手動で発生させると、secure desktop 遷移からの復旧パッチの動作を確認できます。")
    print()

    # 音声ありの場合、wasapi indev を最初の入力 (0番) として追加し、
    # -filter_complex の ddagrab は入力を取らないフィルタグラフのまま
    # 2番目の入力として扱われる。libavdevice の wasapi indev
    # (patches/wasapi-indev.patch) がシステムのデフォルト再生デバイスを
    # WASAPI ループバックでそのまま読む。
    ffmpeg_args = [str(ffmpeg_path), "-hide_banner"]

    if args.with_audio:
        # wasapi indev を先に -i しておくことで、後続の -filter_complex
        # (ddagrab、入力を取らないフィルタグラフ) が入力 0 番として続き、
        # -map で "0:a"(wasapi) / "[vout]"(ddagrab) の両方を参照できる。
        ffmpeg_args += get_audio_input_args(args.audio_device)

    ffmpeg_args += ["-filter_complex", video_filter_complex]
    map_args = ["-map", "[vout]", "-map", "0:a"] if args.with_audio else ["-map", "[vout]"]

    ffmpeg_args += map_args + video_encoder_args
    if args.with_audio:
        ffmpeg_args += get_audio_encoder_args()
    ffmpeg_args += ["-t", str(args.duration), "-y", str(output_path)]

    print("実行コマンド:")
    print(f"  {' '.join(ffmpeg_args)}")
    print()

    result = subprocess.run(ffmpeg_args, check=False)

    if result.returncode != 0:
        print()
        print(f"ffmpeg が異常終了しました (exit code: {result.returncode})。")
        return result.returncode

    if not output_path.is_file():
        print()
        print(f"録画は正常終了しましたが、出力ファイルが見つかりません: {output_path}")
        return 1

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print()
    print("=== 録画完了 ===")
    print(f"  出力ファイル: {output_path}")
    print(f"  サイズ      : {size_mb:.2f} MB")
    print()
    print("動画の長さ・フレーム欠損の有無を確認するには ffprobe があれば以下を実行:")
    print(
        f'  ffprobe -v error -show_entries format=duration '
        f'-of default=noprint_wrappers=1 "{output_path}"'
    )
    return 0


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except Exception as exc:  # noqa: BLE001 - トップレベルで捕捉して表示するため
        print()
        print(f"エラーが発生しました: {exc}")
        exit_code = 1
    finally:
        # ダブルクリック起動時にコンソールが即座に閉じて結果が見えなくなる
        # のを防ぐため、実行結果を確認できるよう待機する。
        input("\n終了するには Enter キーを押してください...")
    sys.exit(exit_code)
