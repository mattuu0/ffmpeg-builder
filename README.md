# ffmpeg マルチプラットフォームビルド（最小構成）

`ffmpeg` バイナリを Linux / Windows / macOS 向けにビルドするための設定一式。
**H.264/H.265 のハードウェアエンコード専用**の最小構成で、音声コーデック・
ソフトウェアデコーダ・ffprobe/ffplay は一切含めない。すべて共有ライブラリ
(`--enable-shared --disable-static`) でビルドし、静的リンクは行わない。

想定用途: 画面キャプチャ（Windows: ddagrab, Linux: xcbgrab/kmsgrab,
macOS: avfoundation）や raw 映像入力を、ハードウェアエンコーダで
H.264/H.265 にリアルタイムエンコードする。既存の圧縮済み動画を読み込んで
デコード・トランスコードする用途には使えない（デコーダを一切含まないため）。

## リポジトリ構成

このリポジトリ自体は「FFmpegのビルダー」であり、FFmpeg本体のソースコードは
含まない。`ffmpeg-src/` は [FFmpeg公式ミラー](https://github.com/FFmpeg/FFmpeg)
を指す git submodule で、実体のソースはそこにある。

```
docker/       Linux・Windows 向け Dockerfile とビルドラッパー
macos/        macOS 向けネイティブビルドスクリプト (Docker不使用)
.github/      GitHub Actions ワークフロー
ffmpeg-src/   FFmpeg本体ソース (git submodule → github.com/FFmpeg/FFmpeg)
dist/         ビルド成果物の出力先 (gitignore対象)
```

クローン時は submodule も取得する:

```bash
git clone --recurse-submodules <このリポジトリのURL>
# 既にクローン済みの場合
git submodule update --init --recursive
```

FFmpeg側のバージョンを更新したい場合は `ffmpeg-src` 内で任意のタグ/コミットに
チェックアウトし、このリポジトリ側でその参照コミットをコミットし直す
(`git add ffmpeg-src && git commit`)。

## 構成

| プラットフォーム | アーキ | 方式 | 定義ファイル |
|---|---|---|---|
| Linux | amd64, arm64 | Docker (Debian bookworm-slim ベース) | `docker/linux/Dockerfile` |
| Windows | amd64, arm64 | Docker (mingw-w64 / llvm-mingw クロス, Debian bookworm-slim ベース) | `docker/windows/Dockerfile` |
| macOS | arm64 (Apple Silicon) | ネイティブビルド (Docker不使用) | `macos/build.sh` |

Linux/Windows は Docker を使うため、Linux 上の1台のマシンだけで両方ビルドできる。
macOS は Apple のライセンス上 Docker/Linux 上でのクロスビルドを避け、GitHub Actions
の `macos-14` runner (Apple Silicon) 上でネイティブに `configure && make` する。

## ライセンス

LGPL を維持するため、GPL コーデックの libx264/libx265 は使わない。H.264 の
ソフトウェアエンコードが必要な場面（HW エンコーダが使えない環境向けの
フォールバック）には BSD ライセンスの [openh264](https://github.com/cisco/openh264)
(`libopenh264`) を全プラットフォームに同梱している。H.265 のオープンな
ソフトウェアエンコーダ実装は実用的な選択肢が無い（主要実装の x265 は GPL）ため、
H.265 は各プラットフォームのハードウェアエンコーダのみで対応する。

## ローカルでビルドする

```bash
# Linux amd64 / arm64
docker/build.sh linux amd64
docker/build.sh linux arm64

# Windows amd64 / arm64
docker/build.sh windows amd64
docker/build.sh windows arm64
```

成果物は `dist/<platform>/<arch>/bin/`（実行ファイル）と `dist/<platform>/<arch>/lib/`
（共有ライブラリ、Windows は bin と同居）に出力される。

macOS 向けは Apple Silicon Mac 上でのみ実行できる:

```bash
macos/build.sh
```

## GitHub Actions

### ビルド (`build.yml`)

`workflow_dispatch`（手動実行）と `v*` タグ push で起動し、linux(amd64/arm64)・
windows(amd64/arm64)・macos(arm64) の5ジョブをビルドしてそれぞれ
`actions/upload-artifact` でアーティファクトとしてアップロードする。タグ push
の場合はさらに `release` ジョブが全ビルド完了後に成果物を zip 化し、
GitHub Release として自動公開する（バイナリ + `SHA256SUMS.txt`）。

### 自動リリース検知 (`check-ffmpeg-release.yml`)

毎日 UTC 3:00 に実行され、upstream FFmpeg (github.com/FFmpeg/FFmpeg) の
`release/<major>.<minor>` ブランチ（例: `release/7.1`）のうち最もバージョン
番号が大きいものを探し、その最新コミットと現在 `ffmpeg-src` submodule が
指しているコミットを比較する。新しいコミットがあれば（新しい release
ブランチが出た場合も、同じブランチにパッチが積まれた場合も）、submodule
をそのブランチの最新コミットへ更新してコミット・push し、このリポジトリ
側に `v<バージョン番号>`（例: `v7.1`）のタグを打つ。これが `build.yml` の
`push: tags: v*` トリガーとなり、そのバージョンでの自動ビルド・自動リリース
につながる。同じバージョンブランチに新しいコミットが積まれた場合はタグを
上書き（force push）して最新化する。

## GitHub Release の成果物

各プラットフォームにつき2種類の zip が公開される:

- `ffmpeg-<platform>-<arch>.zip` — フル版。`bin/`・`lib/`（共有ライブラリ）に加え
  `include/`（ヘッダ）・`share/`・pkgconfig 等、libav* を使った開発に必要な
  ファイル一式を含む
- `ffmpeg-<platform>-<arch>-binary-only.zip` — `bin/` ディレクトリの中身のみ
  （Windows の `.lib` インポートライブラリは除く）

**注意**: `-binary-only` パッケージは Linux/macOS では単体では実行できない。
`ffmpeg` は `lib/*.so`（Linux）/ `lib/*.dylib`（macOS）に動的リンクされているため、
それらの共有ライブラリが実行時に見つかる場所（フル版から取り出すか、システムの
ライブラリパスに配置）に無いと起動に失敗する。Windows は DLL が `bin/` に
同居しているため `-binary-only` だけで動作する。

## 成果物の検証

各プラットフォームの `dist/<platform>/<arch>/` には `SHA256SUMS.txt` が同梱される
（`docker/build.sh` および `macos/build.sh` が生成）。検証は以下の通り:

```bash
cd dist/linux/amd64
sha256sum -c SHA256SUMS.txt
```

## オプション（configure フラグ）の変更方法

共通化レイヤーは無いので、変更したいプラットフォームの定義ファイルを直接編集する:

- Linux: `docker/linux/Dockerfile` 内の `./configure` ブロック
- Windows: `docker/windows/Dockerfile` 内の `./configure` ブロック
- macOS: `macos/build.sh` 内の `./configure` ブロック

いずれも `--disable-everything` を起点に、必要なプロトコル/デマルチプレクサ/
マルチプレクサ/パーサー/フィルタ/エンコーダを `--enable-*` で個別に足す形に
なっている。音声・字幕・追加コンテナフォーマットなどが必要になった場合は、
該当する `--enable-muxer=`/`--enable-demuxer=`/`--enable-encoder=` 等の行を
追記する。

## ハードウェアエンコーダ・入力キャプチャ

| 機能 | Linux | Windows | macOS |
|---|---|---|---|
| NVIDIA NVENC (h264/hevc) | amd64のみ | amd64のみ | 非対応 (Apple Siliconに非搭載) |
| Intel QSV (h264/hevc, libvpl) | amd64のみ | 非対応（クロスビルド未対応） | 非対応 |
| Intel/AMD VAAPI (h264/hevc) | 対応 (amd64, arm64) | 非対応 | 非対応 |
| AMD AMF (h264/hevc) | amd64のみ | amd64のみ | 非対応 |
| Apple VideoToolbox (h264/hevc) | 非対応 | 非対応 | 対応 |
| openh264 (h264, ソフトウェア) | 全アーキ (フォールバック) | 全アーキ (フォールバック) | 対応 (フォールバック) |
| 画面キャプチャ | xcbgrab (amd64) / kmsgrab (全アーキ) | ddagrab フィルタ (全アーキ) | avfoundation |

ビルド自体は各ベンダーのヘッダファイルのみで完結し、実行時に対応する GPU ドライバ
(NVIDIA ドライバ、Intel メディアドライバ、Mesa の VA-API ドライバ等) が無いと
ハードウェアエンコーダは動作しない。`ffmpeg -encoders` でビルドに含まれる
エンコーダを確認できる。

Linux arm64 は VA-API のヘッダを multiarch (`libva-dev:arm64`) でクロスビルドし、
`h264_vaapi`/`hevc_vaapi` を有効化している。VA-API 自体は元々 Intel/AMD 向けの
API だが、Rockchip など一部の ARM SoC ベンダーが VA-API 互換ドライバを提供して
おり、対応する実機であれば動作する可能性がある（実機未検証、configure/link が
通ることまでの確認）。NVENC/QSV/AMF は arm64 向けのベンダー SDK 自体が
提供されていないため非対応。

## 既知の制約・未検証事項

- Windows 向け Intel QSV (libvpl) のクロスビルドは複雑なため未対応。
- Windows arm64 は Debian の apt に `gcc-mingw-w64-aarch64` が無いため
  [llvm-mingw](https://github.com/mstorsjo/llvm-mingw) を使用している
  (GitHub Releases API から最新版のダウンロード URL を動的に解決)。
- macOS は Apple Silicon (arm64) のみ。Intel Mac (x86_64) 向けは対象外。
- Linux arm64 の VA-API、Windows arm64 ビルドは HW エンコーダの実機検証をして
  いない（configure/link が通ることまでの確認）。
- H.265 (HEVC) のソフトウェアエンコードには非対応（arm64含む全プラットフォーム）。
  必要な場合は GPL の libx265 を組み込む必要があるが、その場合は全体のライセンスが
  GPL になる点に注意。
