# ddagrab_vp9_tcp

`ddagrab`（Windows画面キャプチャ）→ `libvpx_vp9`エンコード → TCP送信、という一連の流れを実演するサンプルです。あわせて、このリポジトリのパッチ（`patches/idr-control-socket.patch`）で追加した `-idr_control_socket` を使い、5秒ごとに外部からIDR（キーフレーム）を強制するデモを行います。

## 構成

- `ffmpeg` CLIを子プロセスとして起動（TCPクライアント側）: `ddagrab` でキャプチャし、`libvpx_vp9` でエンコードし、`-f mpegts tcp://127.0.0.1:47890` に送信
- Rustプログラム自身はTCPサーバー（受信側）として待ち受け、受信したバイト列を `out.ts` に書き出す
- 別スレッドで5秒ごとに `-idr_control_socket` （Unix domain socket / Windows named pipe）に接続し、`force_idr\n` を送信

macOS/Linuxで動かす場合は `src/main.rs` の `spawn_ffmpeg()` 内で `avfoundation`/`xcbgrab` に自動的に切り替わりますが、動作確認は主にWindows（`ddagrab`）を前提にしています。

## 前提条件

- このリポジトリでビルドした `ffmpeg`（`libvpx_vp9` エンコーダーと `-idr_control_socket` オプション対応版、`patches/idr-control-socket.patch` 適用済み）が `PATH` に通っていること
- Rust / Cargo がインストールされていること

## 実行方法

```sh
cargo run --release
```

Ctrl+Cで終了すると、子プロセスの`ffmpeg`も終了し、`out.ts`に録画結果が残ります。

## 検証について

**検証には `ffprobe` が必要です。** このプロジェクトのビルド設定は最小構成のため、`ffmpeg`バイナリのみを生成し `ffprobe` は含まれていません（`--disable-ffprobe` が設定されています）。検証を行う場合は、別途フル版FFmpeg（Homebrew/apt/公式ビルド等）から `ffprobe` を用意し、`PATH` に通してください。

```sh
# 例 (macOS, Homebrew)
brew install ffmpeg

# 例 (Debian/Ubuntu)
sudo apt-get install ffmpeg
```

`ffprobe` が用意できたら、`test.py` で自動検証できます:

```sh
python3 test.py
```

`test.py`は以下を確認します:
1. `out.ts`の映像コーデックが`vp9`であること
2. 通常のGOP境界（`-g 300`、約10秒@30fps）以外のタイミングでもIフレームが出現していること（`-idr_control_socket`による強制IDRが機能している証拠）
