---
name: yt-premiere-edit
description: 撮影したYouTube動画(mp4等)を文字起こしし、無音の間と言い直しをカットしたPremiereのシーケンス(XML)・字幕SRT・YouTubeチャプターを作ってPremiereに読み込む。「この動画を編集して」「カット編集」「ジェットカット」「Premiereで編集」「字幕つけて」「チャプター作って」で発動。
---

# YouTube動画 → Premiere カット編集

## 編集ルール（最優先）
1. 発言の意味を変えない。迷ったら残す
2. 言い直しは「後のテイク」を採用し、前のテイクを消す
3. 無音は 0.45秒以上の間を 0.2秒に詰める（pad=0.1）
4. 元の動画ファイルは触らない。作業は <動画名>_edit フォルダで行う
5. 派手さより見やすさ。演出はユーザーがPremiereで足す

## 手順
1. 動画のパスを確認する。作業フォルダ = 動画と同じ場所の「<動画名>_edit」
2. 文字起こし：
   <PYTHON> "<SKILL_DIR>\scripts\transcribe.py" "<動画>" --work "<作業フォルダ>" --prompt "<固有名詞をカンマ区切りで>"
   - 固有名詞（商品名・人名・サービス名）が分かっていれば --prompt に入れる。分からなければ省略
3. カット計画：
   <PYTHON> "<SKILL_DIR>\scripts\make_edit.py" plan "<動画>" --work "<作業フォルダ>"
4. transcript.txt を全部読み、edit_plan.json を編集する：
   - manual_removals：言い直し・言い間違い・撮り直しの前のテイク・「今のカットで」等の指示部分。{"start": 秒, "end": 秒, "reason": "理由と該当セリフ"}
     - 言い直しは「前のテイクの開始 〜 後のテイクの開始の直前」を消す。単語の時刻は transcript.json の words を見る
   - chapters：話題の切れ目ごとに {"start": 元動画の秒, "title": "短い見出し"}。最初は動画の頭から
   - 固有名詞の誤変換は transcript.json の words[].word を直す（字幕に反映される）
5. ユーザーに確認する：元の尺 → カット後の尺の見込み、言い直しとして消す箇所の一覧（時刻＋セリフ）、チャプター案。OKが出るまで build しない
6. 書き出し：
   <PYTHON> "<SKILL_DIR>\scripts\make_edit.py" build --work "<作業フォルダ>"
   <PYTHON> "<SKILL_DIR>\scripts\make_edit.py" preview --work "<作業フォルダ>"
   - output\確認用_コマ一覧.jpg を見て、変な切れ方がないか確認する
7. Premiereに読み込む（MCPが使える時）：
   - verify_premiere_connection（読むだけ）
   - import_fcp_xml（path = output\<名前>.xml、project_path = 作業フォルダ\<名前>.prproj）
   - get_sequence_structure で、クリップ数が build_report.json と一致するか確認
   - import_media で SRT を読み込み → create_caption_track で字幕トラックにする
   - MCPが使えない時は下の「手動で読み込む」をユーザーに案内する
8. 完了報告：作ったファイル、カット数、カット後の尺、YouTube概要欄に貼るチャプター（output\<名前>_チャプター.txt の中身）

## 手動で読み込む
- Premiere：ファイル > 読み込み → output\<名前>.xml → カット済みシーケンスができる
- 字幕：SRTをプロジェクトパネルに読み込み → タイムラインにドラッグ → キャプショントラックとして追加
- チャプター：シーケンスのマーカーとして入っている

## 調整できる値
- plan のオプション：--noise（無音とみなす音量dB。既定 -35、環境音が大きい部屋なら -30）／--min-silence（既定 0.45）／--pad（既定 0.1）
- edit_plan.json の settings：caption_max_chars（字幕1枚の目安文字数。既定 18）／use_fillers（true で「えー」等も切る）／use_auto_silence（false で無音カットをしない）
- ユーザーから好みの指示が出て「スキルに反映して」と言われたら、このSKILL.mdの編集ルールや既定値を更新する
