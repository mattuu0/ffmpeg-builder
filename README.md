# ffmpeg マルチプラットフォームビルド（最小構成）

`ffmpeg` バイナリを Linux / Windows / macOS 向けにビルドするための設定一式。
**H.264/H.265 のハードウェアエンコードと Opus 音声エンコード/デコードに絞った**
最小構成で、H.264/HEVC 以外のソフトウェアデコーダ・ffprobe/ffplay は含めない。
すべて共有ライブラリ (`--enable-shared --disable-static`) でビルドし、静的リンク
は行わない。

想定用途: 画面キャプチャ（Windows: ddagrab, Linux: xcbgrab/kmsgrab,
macOS: avfoundation）や raw 映像入力を、ハードウェアエンコーダで
H.264/H.265 にリアルタイムエンコードし、必要に応じて Opus 音声（Windows は
ネイティブ `wasapi` indev によるシステム音声ループバック録音、
`-f wasapi -i default`）を同じ MP4 にまとめる用途。既存の圧縮済み動画を
読み込んでデコード・トランスコードする用途には使えない（H.264/HEVC 以外の
デコーダを含まないため）。

## リポジトリ構成

このリポジトリ自体は「FFmpegのビルダー」であり、FFmpeg本体のソースコードは
含まない。`ffmpeg-src/` は [FFmpeg公式ミラー](https://github.com/FFmpeg/FFmpeg)
を指す git submodule で、実体のソースはそこにある。

```
docker/       Linux・Windows 向け Dockerfile とビルドラッパー
macos/        macOS 向けネイティブビルドスクリプト (Docker不使用)
.github/      GitHub Actions ワークフロー
ffmpeg-src/   FFmpeg本体ソース (git submodule → github.com/FFmpeg/FFmpeg)
patches/      ffmpeg-src に当てるソースパッチ (ビルドのたびに fresh に適用)
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

このリポジトリがビルドする `ffmpeg` バイナリは **LGPL version 2.1 or later**
でビルドされている（全プラットフォームの configure で `--enable-gpl` は
一切指定していない。configure 実行時の出力にも `License: LGPL version 2.1
or later` と表示される）。

LGPL を維持するため、GPL コーデックの libx264/libx265 は使わない。H.264 の
ソフトウェアエンコードが必要な場面（HW エンコーダが使えない環境向けの
フォールバック）には BSD ライセンスの [openh264](https://github.com/cisco/openh264)
(`libopenh264`) を全プラットフォームに同梱している。H.265 のオープンな
ソフトウェアエンコーダ実装は実用的な選択肢が無い（主要実装の x265 は GPL）ため、
H.265 は各プラットフォームのハードウェアエンコーダのみで対応する。

組み込んでいる外部コンポーネントとそのライセンス:

| コンポーネント | ライセンス | 備考 |
|---|---|---|
| openh264 (Cisco) | BSD-2-Clause | H.264 ソフトウェアエンコーダ(フォールバック) |
| libopus (Xiph.Org) | BSD-3-Clause | Opus 音声エンコード/デコード |
| nv-codec-headers | MIT | NVENC 用ヘッダのみ、ライブラリ実体は非搭載 |
| Intel libvpl (oneVPL) | MIT | QSV 用ヘッダ/ローダのみ |
| AMD AMF ヘッダ | MIT | AMF 用ヘッダのみ |
| libva (VA-API) | MIT | ヘッダ/ローダのみ |
| VideoToolbox | Apple OS フレームワーク | macOS のみ、ライセンス対象外 |

いずれも LGPL と両立するライセンスであり、GPL コーデックは含まれない。また
全プラットフォームで `--enable-shared --disable-static`（静的リンクなし）
でビルドしており、LGPL が要求する動的リンクの要件を満たしている。

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

Windows の ddagrab には、UAC の同意プロンプト表示（secure desktop /
Winlogon への遷移）を挟むと `IDXGIOutputDuplication` が無効化され、通常は
キャプチャが致命的に停止してしまう既知の問題がある。このリポジトリでは
`patches/ddagrab-uac-recovery.patch` を Windows ビルド時（`docker/windows/
Dockerfile`）に自動適用し、`DXGI_ERROR_ACCESS_LOST`/`E_ACCESSDENIED`/
`DXGI_ERROR_INVALID_CALL` 検知時に同じデバイス・同じ出力インデックスで
duplication を再構築してキャプチャを継続させる。`ffmpeg-src` は git
submodule のため、パッチは submodule には焼き込まず、ビルドのたびに
`patches/` から適用される（`check-ffmpeg-release.yml` による日次の
submodule 更新後も自動的に当たり直る）。アップストリームの変更でパッチが
当たらなくなった場合はビルドが `FATAL:` メッセージ付きで失敗する。

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

## 既存 FFmpeg (アップストリーム) からの変更点

このリポジトリは configure フラグでの機能選別に加え、`ffmpeg-src/` に対する
ソースパッチ（`patches/`、submodule には焼き込まずビルドのたびに適用）と、
FFmpeg 本体には無い独自ツール（`tools/`）を含む。アップストリームの素の
FFmpeg には無い、このリポジトリ固有の変更・追加は以下の通り。

### Opus 音声対応

全プラットフォームで `libopus`（BSD-3-Clause、`downloads.xiph.org` の
リリース tarball からクロス/ネイティブビルド）を組み込み、`--enable-libopus`
+ `libopus` エンコーダ/デコーダ + `opus` パーサーを有効化。あわせて
`swscale`/`swresample` も全プラットフォームで有効化した（後述の色範囲
修正で GPU 非搭載パス向けに `scale` フィルタが必要になったため）。
MP4/MOV/Matroska/MPEG-TS/FLV への Opus 格納に対応する。

- Windows arm64 (llvm-mingw) 向けには opus のビルドに `--disable-rtcd`
  が必要（ARM NEON のランタイム CPU検出が Windows-on-ARM に未対応でコン
  パイルエラーになるため）。
- opus 単体のビルドでは `_FORTIFY_SOURCE` 起因のリンクエラー
  (`__memcpy_chk` 等) が mingw で発生するため `-D_FORTIFY_SOURCE=0` で
  無効化し、`libm`（`sqrtf`/`cos` 等）を `--extra-libs=-lm` で明示リンク
  している。

### ネイティブ WASAPI ループバック録音 indev (`libavdevice/wasapi.c`)

FFmpeg には Windows 向けの音声入力デバイスが `dshow`（DirectShow）しか無く、
システム音声（スピーカー出力）をそのままループバック録音する標準的な手段が
無い。`patches/wasapi-indev.patch` により `libavdevice/wasapi.c` を新規
追加し、`wasapi` という avdevice indev として登録した。`IAudioClient` の
`AUDCLNT_STREAMFLAGS_LOOPBACK` 経由でデフォルト（または指定した）再生
デバイスの出力を直接キャプチャし、`ffmpeg` の通常の入力
（`-f wasapi -i default`）として扱える。既存の FFmpeg コードは
`libavdevice/alldevices.c`・`libavdevice/Makefile`・`configure` への
数行の登録追加のみで、ロジック自体は新規ファイルに閉じているため、
アップストリームの変更で壊れる可能性は低い
（`scripts/test-ddagrab-record.py --with-audio` 参照）。

以前は `tools/wasapi-loopback/wasapi_loopback.cpp` という別プロセス＋
標準入力パイプ方式のスタンドアロンヘルパーで同じことを実現していたが、
ネイティブ indev 化によりプロセス起動・パイプ同期のオーバーヘッドが無くなり
`ffmpeg` 単体で完結するようになったため、Windows ビルドではこちらは
コンパイル・同梱しなくなった（ソースは参考として残置）。

### ddagrab の UAC (secure desktop) 遷移からの自動復旧

アップストリームの `ddagrab` は、UAC の同意プロンプト表示（secure desktop /
Winlogon への遷移）で `IDXGIOutputDuplication` が無効化されると
`AcquireNextFrame`/`ReleaseFrame` が `DXGI_ERROR_ACCESS_LOST`/
`E_ACCESSDENIED`/`DXGI_ERROR_INVALID_CALL` を返し、キャプチャが致命的に
停止してしまう（フィルタグラフ全体がエラー終了する）既知の問題がある。
`patches/ddagrab-uac-recovery.patch` により、これらのエラーを検知した際に
致命的エラーとして扱わず、同じ D3D11 デバイス・同じ出力（`output_idx` /
本リポジトリで追加した `output_name` のどちらでも）で duplication を
再構築しながら `EAGAIN`（「まだ新しいフレームがない」）を返し続けるように
変更した。デスクトップ切り替え直後は `DuplicateOutput(1)` が一時的に
`E_ACCESSDENIED` で失敗し続けることがあるため、再構築失敗時は短い待機を
挟んで再試行する。これにより、録画中に UAC プロンプトが表示されても
（ユーザーの応答を待つ間も）録画プロセス自体は落ちず、通常のデスクトップに
戻り次第キャプチャが自動的に再開される。

### ddagrab の色範囲（full range / limited range）バグ修正

`ddagrab`（Desktop Duplication）が出力する BGRA は full range (0-255) だが、
これを何も考慮せず YUV 系エンコーダに渡すと limited range (16-235) として
誤って解釈され、キャプチャ → エンコード → デコード → 再生の経路で黒が
浮く/色が沈む（コントラストが変わる）症状が出る。対処は経路によって異なる:

- **GPU ハードウェアエンコードパス** (`h264_nvenc`/`h264_amf`/`hevc_nvenc`/
  `hevc_amf`): `hwdownload` を挟まず GPU 上で完結させるため、`scale_d3d11`
  フィルタ（D3D11 Video Processor 経由の GPU スケーラー）にパッチ
  (`patches/scale_d3d11-colorspace.patch`) を当て、`VideoProcessorSetStream
  ColorSpace`/`VideoProcessorSetOutputColorSpace` で入力(full range, BT.709)・
  出力(studio/limited range, BT.709) のカラースペースを明示設定するように
  変更した。アップストリームの `scale_d3d11` はこれを一切設定せず、
  D3D11 Video Processor のデフォルト解釈に任せていたため範囲が化けていた。
- **CPU ソフトウェアエンコードパス** (`libopenh264`): `hwdownload` で
  CPU側に降ろした後、`swscale` の `scale` フィルタで
  `in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709`
  を明示して正しく変換する。

いずれのパスも、変換後の実データに合わせてビットストリーム/コンテナ側にも
`-color_range`/`-colorspace`/`-color_primaries`/`-color_trc` を明示する
（`scripts/test-ddagrab-record.py` 参照）。

### ddagrab のモニタ指定を安定化する `output_name` オプション

アップストリームの `ddagrab` はキャプチャするモニタを `output_idx`
（`IDXGIAdapter::EnumOutputs` の列挙順インデックス）でしか指定できない。
これはモニタの抜き差しや再検出（スリープ復帰等）で値が変わりうる不安定な
識別子である。`patches/ddagrab-output-name.patch` により `output_name`
オプションを追加し、`DXGI_OUTPUT_DESC.DeviceName`（例: `\\.\DISPLAY1`）に
よるマッチングでモニタを指定できるようにした。`output_idx` は変更しておらず
デフォルトのまま使用可能、`output_name` を指定した場合のみそちらが優先
される（初回のキャプチャ開始時・UAC 復旧後の再キャプチャ開始時の両方で
一貫して適用される）。同一アダプタ内の出力から探すという既存の
`output_idx` と同じ検索スコープであり、別アダプタに繋がるモニタへの対応
範囲拡大は行っていない。

### ビルド設定の変更

- 全プラットフォームで `-flto` を撤回した。LTO を有効にすると `libswscale`
  の x86 アセンブリ由来オブジェクトのリンクに失敗する
  （Windows: undefined reference、Linux: PIC 未対応によるリロケーション
  エラー）ため、削減できるサイズよりリスクが上回ると判断した。



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

## 免責事項

このリポジトリで提供するビルド設定・スクリプト・ビルド成果物（バイナリ）は
現状有姿（as-is）で提供され、いかなる保証もしない。本ソフトウェアの利用に
起因または関連して生じたいかなる損害（直接・間接・特別・付随的・結果的損害を
含むがこれに限らない）についても、作者は一切の責任を負わない。利用は
自己責任で行うこと。
