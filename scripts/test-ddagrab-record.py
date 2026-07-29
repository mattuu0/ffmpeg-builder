"""
ddagrab (Windows Desktop Duplication) でデスクトップをキャプチャし、
H.264/H.265 + MP4 として録画するテストスクリプト。

同じフォルダの bin\\ffmpeg.exe を使い、ddagrab -> H.264/H.265 エンコード ->
MP4 の録画パスを手動検証する。ddagrab は -filter_complex 経由で入力なしの
フィルタグラフとして起動するため、libavdevice (lavfi インデバイス) を
有効化していない最小構成ビルドでもそのまま動く。

コーデックは既定で H.264、--codec h265 で H.265(HEVC) に切り替えられる。
エンコーダは明示しない限り、コーデックごとに nvenc -> amf -> (H.264のみ)
openh264 software の順で自動フォールバックする
(HEVC はこのビルドにソフトウェアエンコーダを含まないため、
 対応するハードウェアエンコーダが無い場合はエラーになる)。

UAC の同意プロンプト（secure desktop への遷移）を挟んでも録画が継続する
かどうかを確認する目的にも使える。録画中に手動で UAC プロンプトを
発生させる操作（例: 管理者権限が必要な操作を実行する）を行い、録画停止後に
出力ファイルが途切れず再生できるかを確認する。

ダブルクリックで起動した場合は、対話的に録画時間・出力先・コーデック・
エンコーダを確認してから録画を開始する。コマンドライン引数を渡した場合は
非対話的に実行する（引数は下記 --help を参照）。
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


def get_filter_complex(output_idx, framerate, encoder_name):
    ddagrab = f"ddagrab=output_idx={output_idx}:framerate={framerate}"

    # h264_nvenc/h264_amf/hevc_nvenc/hevc_amf は ddagrab が出す D3D11
    # ハードウェアフレームをそのままエンコードできるため、GPU->CPU->GPU の
    # 余計な転送を避けて hwdownload を挟まない。libopenh264 (ソフトウェア
    # エンコーダ) は CPU 側のフレームが必要なため hwdownload で明示的に落とす。
    if encoder_name == "libopenh264":
        return f"{ddagrab},hwdownload,format=bgra,format=yuv420p[out]"
    return f"{ddagrab}[out]"


def get_encoder_args(encoder_name):
    if encoder_name == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "8M"]
    if encoder_name == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-b:v", "8M"]
    if encoder_name == "libopenh264":
        return ["-c:v", "libopenh264", "-b:v", "8M"]
    if encoder_name == "hevc_nvenc":
        return ["-c:v", "hevc_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "8M"]
    if encoder_name == "hevc_amf":
        return ["-c:v", "hevc_amf", "-quality", "balanced", "-b:v", "8M"]
    raise ValueError(f"未対応のエンコーダです: {encoder_name}")


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


def run_interactive_prompts(args):
    print("=== ddagrab 録画テスト (対話モード) ===")
    print("Enter キーのみで [] 内のデフォルト値を使用します。\n")

    args.duration = prompt_int("録画時間 (秒)", args.duration)
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

    output_default = str(args.output_path) if args.output_path else "(自動生成)"
    output_input = prompt_str("出力ファイルパス (空欄で自動生成)", output_default)
    if output_input and output_input != "(自動生成)":
        args.output_path = Path(output_input)

    print()
    return args


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="ddagrab で H.264/H.265 + MP4 録画するテストスクリプト"
    )
    parser.add_argument("--ffmpeg-path", dest="ffmpeg_path", default=None)
    parser.add_argument("--output-path", dest="output_path", type=Path, default=None)
    parser.add_argument("--duration", type=int, default=30, help="録画時間 (秒)")
    parser.add_argument(
        "--output-idx", dest="output_idx", type=int, default=0, help="ddagrab の output_idx"
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
    filter_complex = get_filter_complex(args.output_idx, args.framerate, selected_encoder)
    encoder_args = get_encoder_args(selected_encoder)

    print()
    print("=== ddagrab 録画テスト ===")
    print(f"  モニタ index : {args.output_idx}")
    print(f"  フレームレート: {args.framerate} fps")
    print(f"  録画時間     : {args.duration} 秒")
    print(f"  コーデック   : {args.codec}")
    print(f"  エンコーダ   : {selected_encoder}")
    print(f"  出力先       : {output_path}")
    print()
    print("録画中にUACの同意プロンプト（例:管理者権限が必要な操作の実行）を")
    print("手動で発生させると、secure desktop 遷移からの復旧パッチの動作を確認できます。")
    print()

    # -filter_complex で ddagrab を入力なしのフィルタグラフとして起動する。
    # libavdevice の lavfi インデバイス (-f lavfi -i "ddagrab=...") と等価だが、
    # avdevice を有効化していない最小構成ビルドでもそのまま動く。
    ffmpeg_args = (
        [
            str(ffmpeg_path),
            "-hide_banner",
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
        ]
        + encoder_args
        + [
            "-t",
            str(args.duration),
            "-y",
            str(output_path),
        ]
    )

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
