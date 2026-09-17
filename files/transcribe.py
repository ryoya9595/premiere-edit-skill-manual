"""動画を faster-whisper で文字起こしして、単語ごとの時刻つきで保存する。

使い方:
    python transcribe.py "D:\\素材\\撮影.mp4" --work "D:\\素材\\撮影_edit"

出力（--work フォルダ）:
    transcript.json  … セグメント＋単語ごとの開始/終了秒（後の工程で使う）
    transcript.txt   … 人が読む用（[開始 - 終了] テキスト）
"""
import argparse
import json
import sys
from pathlib import Path


def fmt(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def load_model(name: str, device: str, compute: str):
    from faster_whisper import WhisperModel

    if device == "auto":
        try:
            return WhisperModel(name, device="cuda", compute_type="float16"), "cuda"
        except Exception as e:  # GPUが使えない環境ではCPUに落とす
            print(f"[info] GPUで起動できなかったのでCPUで実行します: {e}", file=sys.stderr)
            return WhisperModel(name, device="cpu", compute_type="int8"), "cpu"
    return WhisperModel(name, device=device, compute_type=compute), device


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--work", required=True)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="auto", help="auto / cuda / cpu")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--lang", default="ja")
    ap.add_argument("--prompt", default="", help="固有名詞などのヒント（例: Claude, Premiere, RISE）")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)

    model, used = load_model(args.model, args.device, args.compute)
    print(f"[info] model={args.model} device={used}", file=sys.stderr)

    segments, info = model.transcribe(
        str(video),
        language=args.lang,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,  # 同じ文の繰り返し出力（幻覚）を防ぐ
        initial_prompt=args.prompt or None,
    )

    out = {"video": str(video), "language": info.language, "duration": info.duration, "segments": []}
    lines = []
    for i, seg in enumerate(segments):
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word, "prob": round(w.probability, 3)}
            for w in (seg.words or [])
        ]
        text = seg.text.strip()
        out["segments"].append({"id": i, "start": round(seg.start, 3), "end": round(seg.end, 3), "text": text, "words": words})
        lines.append(f"#{i:04d} [{fmt(seg.start)} - {fmt(seg.end)}] {text}")
        print(lines[-1], flush=True)

    (work / "transcript.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "transcript.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[done] {len(out['segments'])} segments -> {work / 'transcript.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
