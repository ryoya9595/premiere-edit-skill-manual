# Claude Code 向け手順書：YouTubeカット編集スキル（Premiere）を作る

> この手順書は Claude Code が読むためのものです。ユーザーと会話しながら、上から順に進めてください。
> 配布元：https://ryoya9595.github.io/premiere-edit-skill-manual/

## 1. ゴール

ユーザーのPCに、YouTube長尺動画のラフカットを作るスキル `yt-premiere-edit` を作り、**ユーザーのPremiereで実際に動作確認するところまで**終わらせる。

完成したスキルができること：
- 撮影した動画から、無音の間と言い直しをカットしたシーケンスをPremiereに作る
- 字幕（SRT）とYouTubeチャプター（Premiereのマーカーつき）を作る
- カットはPremiereのタイムライン上の普通のクリップなので、ユーザーがあとから自由に直せる

作らないもの：テロップのデザイン、BGM、効果音、ズームなどの演出（ユーザーがPremiereで足す部分）

## 2. 守ること

- **インストール・レジストリ変更・設定ファイル変更の前に、何をするかを説明してユーザーの了承を取る**
- 元の動画ファイルは上書き・移動・削除しない。作業ファイルは動画と同じ場所の `<動画名>_edit` フォルダに置く
- `.env` や認証情報のファイルは読まない
- 最初の動作確認は **1〜2分の短い動画** で行う
- 「できた」と言う前に「7. 動作確認チェックリスト」を実際に確認する
- この手順書は Windows を前提に書いている。Mac の場合はコマンドを読み替える（`python` → `python3`、パス区切り、`%USERPROFILE%` → `~` など）

## 3. 仕組み（なぜこの作り方なのか）

```
動画(mp4)
 ├─ ① transcribe.py … faster-whisperで文字起こし（単語ごとの時刻つき）
 ├─ ② make_edit.py plan … FFmpegで無音を検出 → edit_plan.json（カット計画）
 ├─ ③ Claude が文字起こしを読み、言い直し・NGを edit_plan.json に追記／チャプターを決める
 ├─ ④ make_edit.py build … カット済みシーケンスのXML＋字幕SRT＋チャプター
 ├─ ⑤ make_edit.py preview … 確認用のカット後動画（軽量）＋2秒ごとのコマ一覧
 └─ ⑥ Premiereに読み込む（MCPで自動 → ダメなら手動で「ファイル > 読み込み」）
```

判断の理由（変えるときはこの理由を踏まえること）：
- **カットはMCPでタイムラインを直接いじらず、XMLで作る。** `premiere-pro-mcp` のREADMEに、Premiere 26.x ではリップル削除などの編集操作がエラーを出さずに無視されることがあると書かれている。XML（Final Cut Pro 7 XML / xmeml v5）ならPremiereが標準で読み込めて、結果が毎回同じになる
- **XMLの書き方は auto-editor（Premiere向け書き出しの実績があるOSS）に合わせている。** 特にステレオ音声は「A1/A2の2トラックに分けて、`premiereTrackType="Stereo"`＋`currentExplodedTrackIndex`」で書かないと片側の音が出ないことがある
- **MCPの役割は「読み込み・確認・字幕トラック作成」に絞る。** `import_fcp_xml` / `get_sequence_structure` / `import_media` / `create_caption_track`
- **無音の詰め方の既定値**：0.45秒以上の間を0.2秒に詰める（`--min-silence 0.45 --pad 0.1`）。言い直しは後のテイクを採用
- CapCutは対象外（CapCut 6以降は下書きファイルが暗号化されていて外から作れない）。CapCutで使いたいと言われたら、`make_edit.py` の preview と同じ区間でフル解像度・高画質の mp4 を書き出し（`scale` を外し `-crf 18` など）、字幕SRTと一緒にCapCutに読み込んでもらう

参考スクリプトの状態：テスト用の日本語動画（無音と言い直し入り）で、文字起こし→カット計画→XML/SRT/チャプター→確認動画まで動作確認済み。確認動画を文字起こしし直して、言い直しが消えていることも確認した。**ただしPremiereへの実際の読み込みは、配布元では未確認。** このユーザーのPCで最初に確認し、問題があれば直すこと。

## 4. フェーズA：環境の確認（読むだけ・変更なし）

PowerShellで確認し、結果をユーザーに一覧で報告する。足りないものがあれば、入れ方を説明して了承を取ってから入れる。

```powershell
node -v; npm -v; python --version; ffmpeg -version | Select-Object -First 1; ffprobe -version | Select-Object -First 1
python -c "import faster_whisper, ctranslate2; print('faster-whisper', faster_whisper.__version__, 'cuda devices', ctranslate2.get_cuda_device_count())"
claude --version
```

| 必要なもの | 目安 | ない場合 |
|---|---|---|
| Premiere Pro | 2020〜2026 | ユーザーにCreative Cloudから入れてもらう |
| Node.js | 20.19以上 | `winget install OpenJS.NodeJS.LTS` |
| Python | 3.10以上 | `winget install Python.Python.3.12` |
| FFmpeg / ffprobe | PATHが通っている | `winget install Gyan.FFmpeg` |
| faster-whisper | Pythonから import できる | `python -m pip install faster-whisper` |
| NVIDIA GPU | あれば速い（なくてもCPUで動くが遅い） | CPUの場合は `--model medium` などに下げる |

- `faster_whisper` が別のPython（仮想環境など）に入っている場合は、それを探して**そのPythonのパス**をスキルで使う
- Premiereのバージョンは「ヘルプ > Premiere Pro について」でユーザーに見てもらう

## 5. フェーズB：Premiere MCP の導入（要了承）

ユーザーに次のように説明し、了承を得てから実行する：
「無料のオープンソース `premiere-pro-mcp`（Adobe公式ではありません）を入れて、Premiereに橋渡しの拡張機能を入れます。署名なしの拡張機能を許可する設定（PlayerDebugMode）がレジストリに書かれます」

```powershell
# 1. 本体（最新版を確認してからバージョンを固定する）
npm view premiere-pro-mcp version
npm install -g premiere-pro-mcp@<確認したバージョン>
premiere-pro-mcp --version

# 2. Premiereを完全に終了してから、橋渡しの拡張機能を入れる
premiere-pro-mcp --install-cep
premiere-pro-mcp --doctor

# 3. Claude Code に登録する設定を表示（ファイルは書き換えない）
premiere-pro-mcp --print-client-config claude
```

- 3の出力を元に `claude mcp add` で **user スコープ**に登録する。Windowsで `premiere-pro-mcp` をそのまま起動できない場合は `cmd /c premiere-pro-mcp` にするか、`node "<npmのグローバルフォルダ>\premiere-pro-mcp\dist\index.js"` を直接指定する
  - 例：`claude mcp add premiere-pro -s user -- cmd /c premiere-pro-mcp`
- 登録したら、ユーザーに **Claude Code の再起動** をお願いする（MCPはセッション開始時に読み込まれる）。再起動後は「手順書のフェーズBの接続確認から続けて」と言ってもらう
- ユーザーにPremiereを起動 → 何かプロジェクトを開く → **ウィンドウ > エクステンション > MCP for Adobe Premiere Pro** を開いて、「Running」と出ているか見てもらう
- 読むだけの接続確認：MCPツール `verify_premiere_connection`（変更はしない）

MCPでつまずいた時：

| 症状 | 対処 |
|---|---|
| エクステンションのメニューに出ない | `premiere-pro-mcp --diagnose-cep`。`reg query "HKCU\SOFTWARE\Adobe\CSXS.12" /v PlayerDebugMode` が `REG_SZ 1` か（DWORDは不可）。Premiereを全部終了して `--install-cep` をやり直す |
| Signature verification failed | 最新版を入れ直し → Premiereを完全終了 → `--install-cep` → 再起動 |
| タイムアウトする | パネルが Running か確認。環境変数 `PREMIERE_TIMEOUT_MS=60000` |
| UXP関連のツールが401エラー | UXPは試験版。このスキルでは使わない（CEPだけで足りる） |
| どうしてもMCPが動かない | **MCPなしでもスキルは使える**。XMLとSRTを手動で読み込む運用にする |

## 6. フェーズC：スキルを作る

### 6-1. ファイルをダウンロードする

```powershell
$base = "https://ryoya9595.github.io/premiere-edit-skill-manual/files"
$dir  = "$env:USERPROFILE\.claude\skills\yt-premiere-edit"
New-Item -ItemType Directory -Force "$dir\scripts" | Out-Null
Invoke-WebRequest "$base/transcribe.py"      -OutFile "$dir\scripts\transcribe.py"
Invoke-WebRequest "$base/make_edit.py"       -OutFile "$dir\scripts\make_edit.py"
Invoke-WebRequest "$base/SKILL_template.md"  -OutFile "$dir\SKILL.md"
Get-ChildItem -Recurse $dir
```

- すでに `yt-premiere-edit` がある場合は、上書きする前にユーザーに確認する（バックアップを取る）
- ダウンロードしたら中身を読み、何をするコードかをユーザーに短く説明する

### 6-2. SKILL.md を仕上げる

- `SKILL.md` の `<PYTHON>` を、フェーズAで確認した faster-whisper が使えるPythonのパス（または `python`）に置き換える
- `<SKILL_DIR>` を実際のスキルフォルダのパスに置き換える
- ユーザーの好み（字幕の文字数、残す間の長さなど）を聞いていれば、編集ルールと既定値に反映する

## 7. フェーズD：動作確認（1〜2分の短い動画で）

ユーザーに短い動画を1本選んでもらい、SKILL.md の手順どおりに通す。以下を **全部確認してから** 完成と報告する。

| # | 確認すること | 見る場所 |
|---|---|---|
| 1 | 文字起こしがGPUで動いた（ログに `device=cuda`） | transcribe の出力 |
| 2 | XMLがPremiereで開ける。エラーやメディアオフライン（赤い画面）が出ない | Premiere |
| 3 | シーケンスのクリップ数が build_report.json の「クリップ数」と同じ | get_sequence_structure / 目視 |
| 4 | 音が左右両方から出て、映像と音がズレていない | Premiereで再生（ユーザーに聞く） |
| 5 | シーケンスの解像度・フレームレートが元動画と同じ | シーケンス設定 |
| 6 | 字幕がセリフと合っている（動画の後半でもズレない） | Premiereで再生 |
| 7 | チャプターのマーカーが話題の頭にある | タイムラインのマーカー |
| 8 | 元の動画ファイルが変わっていない | ファイルの更新日時 |

問題が出た時の直し方：

| 症状 | 見るところ・直し方 |
|---|---|
| XMLを開くとメディアオフライン | `<pathurl>` のパス。日本語・スペース入りのパスで失敗するなら、`file://localhost/D:/...` 形式（日本語はURLエンコード）に変えて試す |
| 片側しか音が出ない／音が二重 | 音声トラックの書き方（ステレオはA1/A2に分ける）。元動画の音声チャンネル数を ffprobe で確認 |
| 映像と音が少しずつズレる | スマホ撮影の可変フレームレート。元動画を固定フレームレートに変換したコピーを作ってから使う（元ファイルは残す） |
| 字幕が後半ほどズレる | edit_plan.json の fps_num / fps_den が元動画と合っているか |
| 言葉の頭や語尾が切れる | `--pad` を 0.15〜0.2 に。`--noise` を -40 に |
| 間が残りすぎ | `--min-silence` を 0.35、`--pad` を 0.08 に |
| マーカーが出ない | Premiereのバージョンによっては読み込まれない。チャプターは txt を使えば問題なし |

直したら **スクリプトとSKILL.mdの両方に反映** し、同じ短い動画でもう一度チェックリストを通す。

## 8. 完成後にユーザーへ伝えること

- 使い方：「この動画を編集して：D:\...\撮影.mp4」
- Premiereで開いたあとの仕上げ（テロップ・BGM・サムネ）はユーザーがやる部分
- 好みの調整は話しかけて直し、「スキルに反映して」と言えば次回からも同じになる
- `premiere-pro-mcp` は頻繁に更新される。不具合が出たら `premiere-pro-mcp --check-update`。更新前はPremiereを完全に終了する
- 不要になったら：`premiere-pro-mcp --uninstall-cep` → `npm uninstall -g premiere-pro-mcp` → `claude mcp remove premiere-pro -s user`

---
参考：premiere-pro-mcp（MIT）https://github.com/leancoderkavy/premiere-pro-mcp ／ XMLの構造は auto-editor https://github.com/WyattBlue/auto-editor の Premiere 書き出しを参考
