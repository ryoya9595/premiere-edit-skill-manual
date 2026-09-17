"""カット計画 → Premiere用XML（カット済みシーケンス）＋字幕SRT＋チャプターを作る。

    python make_edit.py plan  "D:\\素材\\撮影.mp4" --work "D:\\素材\\撮影_edit"
    （edit_plan.json の manual_removals / chapters を編集）
    python make_edit.py build --work "D:\\素材\\撮影_edit"
    python make_edit.py preview --work "D:\\素材\\撮影_edit"   （確認用のカット後動画＋コマ一覧）

XMLは Final Cut Pro 7 XML（xmeml v5）。Premiere の「ファイル > 読み込み」で
カット済みのシーケンスとして開ける。構造は auto-editor の Premiere 出力に合わせている。
"""
import argparse
import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape

FILLERS = {"えー", "えーと", "えっと", "あー", "あのー", "あの", "うーん", "んー", "まあ", "えーっと", "そのー"}
STD_RATES = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
             Fraction(50), Fraction(60000, 1001), Fraction(60)]


# ---------------------------------------------------------------- 素材情報
def probe(video: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"ffprobe に失敗しました: {r.stderr}")
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        sys.exit("映像トラックが見つかりません")
    rate_str = v.get("avg_frame_rate")
    raw = Fraction(rate_str if rate_str and rate_str != "0/0" else v["r_frame_rate"])
    fps = min(STD_RATES, key=lambda x: abs(float(x) - float(raw)))  # スマホ撮影の可変フレームレートも標準値に丸める
    width, height = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        width, height = height, width
    return {
        "path": str(video), "duration": float(d["format"]["duration"]),
        "fps_num": fps.numerator, "fps_den": fps.denominator, "width": width, "height": height,
        "audio_channels": int(a["channels"]) if a else 0, "sample_rate": int(a["sample_rate"]) if a else 48000,
    }


def detect_silence(video: Path, noise_db: float, min_sec: float, duration: float) -> list:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn",
                        "-af", f"silencedetect=noise={noise_db}dB:d={min_sec}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append([start, float(m.group(1))])
            start = None
    if start is not None:
        out.append([start, duration])
    return out


# ---------------------------------------------------------------- 区間計算
def union(ranges):
    rs = sorted([list(r) for r in ranges if r[1] > r[0]])
    out = []
    for s, e in rs:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def subtract(ranges, holes):
    out = []
    for s, e in ranges:
        cur = [[s, e]]
        for hs, he in holes:
            nxt = []
            for cs, ce in cur:
                if he <= cs or hs >= ce:
                    nxt.append([cs, ce])
                    continue
                if hs > cs:
                    nxt.append([cs, hs])
                if he < ce:
                    nxt.append([he, ce])
            cur = nxt
        out.extend(cur)
    return out


def load_words(work: Path):
    p = work / "transcript.json"
    if not p.exists():
        return []
    t = json.loads(p.read_text(encoding="utf-8"))
    return [w for s in t["segments"] for w in s["words"]]


# ---------------------------------------------------------------- plan
def cmd_plan(args):
    video = Path(args.video).resolve()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    src = probe(video)
    words = load_words(work)

    sil = detect_silence(video, args.noise, args.min_silence, src["duration"])
    auto = []
    for s, e in sil:
        ps = s if s <= 0.01 else s + args.pad          # 動画の頭の無音はパディングなしで削る
        pe = e if e >= src["duration"] - 0.01 else e - args.pad
        if pe - ps >= args.min_cut:
            auto.append([round(ps, 3), round(pe, 3)])
    # 小声で無音判定された発話は残す（文字起こしに単語がある所は削らない）
    speech = union([[w["start"] - 0.05, w["end"] + 0.05] for w in words])
    auto = [r for r in subtract(auto, speech) if r[1] - r[0] >= args.min_cut]

    fillers = []
    for w in words:
        if w["word"].strip(" 、。,.") in FILLERS:
            fillers.append({"start": w["start"], "end": w["end"], "text": w["word"].strip()})

    plan = {
        "source": src,
        "settings": {"noise_db": args.noise, "min_silence": args.min_silence, "pad": args.pad,
                     "min_cut": args.min_cut, "use_auto_silence": True, "use_fillers": False,
                     "caption_max_chars": 18},
        "auto_removals": [{"start": s, "end": e, "reason": "silence"} for s, e in auto],
        "filler_candidates": fillers,
        "manual_removals": [],
        "chapters": [],
        "sequence_name": video.stem + "_カット済み",
    }
    (work / "edit_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    kept = src["duration"] - sum(e - s for s, e in union(auto))
    print(json.dumps({"元の尺(秒)": round(src["duration"], 1), "無音カット数": len(auto),
                      "カット後の尺(秒・無音のみ)": round(kept, 1), "フィラー候補": len(fillers),
                      "fps": f'{src["fps_num"]}/{src["fps_den"]}', "解像度": f'{src["width"]}x{src["height"]}',
                      "音声ch": src["audio_channels"], "plan": str(work / "edit_plan.json")},
                     ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- build
def timebase(fps: Fraction):
    if fps.denominator == 1001:
        return round(fps.numerator / 1000), "TRUE"
    return int(fps), "FALSE"


def rate_xml(tb, ntsc):
    return f"<rate><timebase>{tb}</timebase><ntsc>{ntsc}</ntsc></rate>"


def path_for_xml(p: str) -> str:
    return escape(str(Path(p).resolve()).replace("\\", "/"))


def fmt_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_chapter(t: float) -> str:
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cmd_build(args):
    work = Path(args.work).resolve()
    plan = json.loads((work / "edit_plan.json").read_text(encoding="utf-8"))
    src, st = plan["source"], plan["settings"]
    fps = Fraction(src["fps_num"], src["fps_den"])
    total_frames = int(round(src["duration"] * fps))

    removals = [[r["start"], r["end"]] for r in plan["manual_removals"]]
    if st.get("use_auto_silence", True):
        removals += [[r["start"], r["end"]] for r in plan["auto_removals"]]
    if st.get("use_fillers"):
        removals += [[f["start"] - 0.03, f["end"] + 0.03] for f in plan["filler_candidates"]]
    rem_frames = union([[max(0, int(round(s * fps))), min(total_frames, int(round(e * fps)))] for s, e in removals])

    keeps, cur = [], 0
    for s, e in rem_frames:
        if s > cur:
            keeps.append([cur, s])
        cur = max(cur, e)
    if cur < total_frames:
        keeps.append([cur, total_frames])
    keeps = [k for k in keeps if k[1] - k[0] >= args.min_keep_frames]  # 数フレームだけ残る破片は捨てる
    if not keeps:
        sys.exit("残る区間がありません。edit_plan.json を見直してください")

    segs, tl = [], 0  # [src_in, src_out, tl_start]（フレーム）
    for a, b in keeps:
        segs.append((a, b, tl))
        tl += b - a
    seq_frames = tl

    def to_tl(t: float, side: str):
        f = t * float(fps)
        for a, b, s in segs:
            if a <= f <= b:
                return (s + (f - a)) / float(fps)
        if side == "start":  # カットされた位置 → 次に残る区間の頭
            nxt = [s for a, b, s in segs if a > f]
            return nxt[0] / float(fps) if nxt else None
        prv = [s + (b - a) for a, b, s in segs if b < f]
        return prv[-1] / float(fps) if prv else None

    def is_kept(t: float):
        f = t * float(fps)
        return any(a <= f < b for a, b, _ in segs)

    out_dir = work / "output"
    out_dir.mkdir(exist_ok=True)
    name = plan.get("sequence_name") or Path(src["path"]).stem

    # ---- XML
    tb, ntsc = timebase(fps)
    stereo = src["audio_channels"] >= 2
    has_audio = src["audio_channels"] > 0
    n = len(segs)
    a_tracks = (2 if stereo else 1) if has_audio else 0
    clip_name = escape(Path(src["path"]).stem)
    file_def = (
        f'<file id="file-1"><name>{clip_name}</name><pathurl>{path_for_xml(src["path"])}</pathurl>'
        f'<timecode><string>00:00:00:00</string><displayformat>NDF</displayformat>{rate_xml(tb, ntsc)}</timecode>'
        f'{rate_xml(tb, ntsc)}<duration></duration><media>'
        f'<video><samplecharacteristics>{rate_xml(tb, ntsc)}<width>{src["width"]}</width>'
        f'<height>{src["height"]}</height><pixelaspectratio>square</pixelaspectratio></samplecharacteristics></video>'
        + (f'<audio><samplecharacteristics><depth>16</depth><samplerate>{src["sample_rate"]}</samplerate>'
           f'</samplecharacteristics><channelcount>{src["audio_channels"]}</channelcount></audio>' if has_audio else "")
        + '</media></file>'
    )
    first = [True]

    def fileref():
        if first[0]:
            first[0] = False
            return file_def
        return '<file id="file-1"/>'

    vx = []
    for j, (a, b, s) in enumerate(segs):
        links = (f'<link><linkclipref>clipitem-{j + 1}</linkclipref><mediatype>video</mediatype>'
                 f'<trackindex>1</trackindex><clipindex>{j + 1}</clipindex></link>')
        for k in range(a_tracks):
            links += (f'<link><linkclipref>clipitem-{n * (k + 1) + j + 1}</linkclipref><mediatype>audio</mediatype>'
                      f'<trackindex>{k + 1}</trackindex><clipindex>{j + 1}</clipindex></link>')
        vx.append(f'<clipitem id="clipitem-{j + 1}"><name>{clip_name}</name><enabled>TRUE</enabled>'
                  f'<start>{s}</start><end>{s + b - a}</end><in>{a}</in><out>{b}</out>{fileref()}'
                  f'<compositemode>normal</compositemode>{links}</clipitem>')

    ax = []
    for k in range(a_tracks):
        attrs = (f'currentExplodedTrackIndex="{k}" totalExplodedTrackCount="{2 if stereo else 1}" '
                 f'premiereTrackType="{"Stereo" if stereo else "Mono"}"')
        items = []
        for j, (a, b, s) in enumerate(segs):
            items.append(f'<clipitem id="clipitem-{n * (k + 1) + j + 1}" premiereChannelType="{"stereo" if stereo else "mono"}">'
                         f'<name>{clip_name}</name><enabled>TRUE</enabled><start>{s}</start><end>{s + b - a}</end>'
                         f'<in>{a}</in><out>{b}</out>{fileref()}'
                         f'<sourcetrack><mediatype>audio</mediatype><trackindex>{k + 1}</trackindex></sourcetrack>'
                         f'</clipitem>')
        oc = f'<outputchannelindex>{k + 1}</outputchannelindex>' if stereo else ""
        ax.append(f'<track {attrs}>{oc}{"".join(items)}</track>')

    chapters = sorted(plan.get("chapters", []), key=lambda c: c["start"])
    markers, chap_lines = [], []
    for c in chapters:
        t = to_tl(float(c["start"]), "start")
        if t is None:
            continue
        if not chap_lines and t > 0:
            t = 0.0  # YouTubeのチャプターは 0:00 始まりが必須
        f = int(round(t * fps))
        markers.append(f'<marker><name>{escape(c["title"])}</name><comment>chapter</comment><in>{f}</in><out>-1</out></marker>')
        chap_lines.append(f"{fmt_chapter(t)} {c['title']}")

    xml = (
        "<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE xmeml>\n"
        f'<xmeml version="5"><sequence explodedTracks="true"><name>{escape(name)}</name>'
        f'<duration>{seq_frames}</duration>{rate_xml(tb, ntsc)}'
        f'<timecode>{rate_xml(tb, ntsc)}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
        f'<media><video><format><samplecharacteristics><width>{src["width"]}</width><height>{src["height"]}</height>'
        f'<pixelaspectratio>square</pixelaspectratio>{rate_xml(tb, ntsc)}</samplecharacteristics></format>'
        f'<track>{"".join(vx)}</track></video>'
        f'<audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth>'
        f'<samplerate>{src["sample_rate"]}</samplerate></samplecharacteristics></format>{"".join(ax)}</audio></media>'
        f'{"".join(markers)}</sequence></xmeml>\n'
    )
    xml_path = out_dir / f"{name}.xml"
    xml_path.write_text(xml, encoding="utf-8")

    # ---- 字幕SRT（カット後の時間軸に合わせる）
    max_chars = int(st.get("caption_max_chars", 18))
    words = [w for w in load_words(work) if is_kept((w["start"] + w["end"]) / 2)]
    cues, buf = [], []

    def flush():
        if not buf:
            return
        text = "".join(w["word"] for w in buf).strip().strip("、。")
        s0, e0 = to_tl(buf[0]["start"], "start"), to_tl(buf[-1]["end"], "end")
        if text and s0 is not None and e0 is not None:
            cues.append([s0, max(e0, s0 + 0.6), text])
        buf.clear()

    def buf_len():
        return len("".join(x["word"] for x in buf).strip())

    # 区切りの優先順: 文末 → 読点（max_charsを超えそうな時）→ 間が空いた所 → どうしても長い時だけ単語の途中
    for wi, w in enumerate(words):
        if buf:
            gap = (to_tl(w["start"], "start") or 0) - (to_tl(buf[-1]["end"], "end") or 0)
            hard = max_chars + 8
            if gap > 0.5 or buf_len() + len(w["word"].strip()) > hard or w["start"] - buf[0]["start"] > 7:
                flush()
        buf.append(w)
        tail = w["word"].strip()
        if tail.endswith(("。", "？", "！", "?", "!")):
            flush()
        elif tail.endswith("、") and buf_len() >= 5:
            rest = 0  # この先、文末までの文字数。1枚に収まるなら読点で切らない
            for x in words[wi + 1:]:
                rest += len(x["word"].strip())
                if x["word"].strip().endswith(("。", "？", "！", "?", "!", "、")):
                    break
            if buf_len() + rest > max_chars:
                flush()
    flush()
    for i in range(len(cues) - 1):  # 次の字幕と重ならないように
        cues[i][1] = min(cues[i][1], cues[i + 1][0])
    srt = "".join(f"{i + 1}\n{fmt_srt(s)} --> {fmt_srt(e)}\n{t}\n\n" for i, (s, e, t) in enumerate(cues) if e > s)
    srt_path = out_dir / f"{name}_字幕.srt"
    srt_path.write_text(srt, encoding="utf-8")

    chap_path = out_dir / f"{name}_チャプター.txt"
    chap_path.write_text("\n".join(chap_lines) + ("\n" if chap_lines else ""), encoding="utf-8")

    report = {
        "元の尺(秒)": round(src["duration"], 1), "カット後の尺(秒)": round(seq_frames / float(fps), 1),
        "クリップ数": n, "字幕数": len(cues), "チャプター数": len(chap_lines),
        "xml": str(xml_path), "srt": str(srt_path), "chapters": str(chap_path),
    }
    (work / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "segments.json").write_text(json.dumps({"fps_num": src["fps_num"], "fps_den": src["fps_den"], "keeps": keeps}),
                                        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- preview（Premiereに入れる前の確認用）
def cmd_preview(args):
    """カット後の軽い確認動画（540p）と、2秒ごとのコマを並べた一覧画像を作る。"""
    work = Path(args.work).resolve()
    plan = json.loads((work / "edit_plan.json").read_text(encoding="utf-8"))
    seg = json.loads((work / "segments.json").read_text(encoding="utf-8"))
    fps = Fraction(seg["fps_num"], seg["fps_den"])
    has_audio = plan["source"]["audio_channels"] > 0
    parts, labels = [], ""
    for i, (a, b) in enumerate(seg["keeps"]):
        s, e = float(a / fps), float(b / fps)
        parts.append(f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS,scale=-2:540[v{i}];")
        labels += f"[v{i}]"
        if has_audio:
            parts.append(f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS[a{i}];")
            labels += f"[a{i}]"
    n = len(seg["keeps"])
    outs = "[v][a]" if has_audio else "[v]"
    graph = "".join(parts) + f"{labels}concat=n={n}:v=1:a={1 if has_audio else 0}{outs}"
    script = work / "preview_filter.txt"  # Windowsのコマンド長制限を避けるためファイルで渡す
    script.write_text(graph, encoding="utf-8")
    out_dir = work / "output"
    out_dir.mkdir(exist_ok=True)
    preview = out_dir / "確認用_カット後.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", plan["source"]["path"],
           "-filter_complex_script", str(script), "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", str(preview)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"確認動画の書き出しに失敗しました: {r.stderr[-2000:]}")
    sheet = out_dir / "確認用_コマ一覧.jpg"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(preview),
                    "-vf", "fps=1/2,scale=320:-2,tile=6x8", "-frames:v", "1", str(sheet)],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(json.dumps({"preview": str(preview), "contact_sheet": str(sheet)}, ensure_ascii=False, indent=1))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("video")
    p.add_argument("--work", required=True)
    p.add_argument("--noise", type=float, default=-35.0, help="この音量(dB)以下を無音とみなす")
    p.add_argument("--min-silence", type=float, default=0.45, help="この秒数以上続く無音をカット対象にする")
    p.add_argument("--pad", type=float, default=0.1, help="発話の前後に残す余白(秒)。0.1なら間が0.2秒に詰まる")
    p.add_argument("--min-cut", type=float, default=0.3)
    p.set_defaults(func=cmd_plan)
    b = sub.add_parser("build")
    b.add_argument("--work", required=True)
    b.add_argument("--min-keep-frames", type=int, default=4)
    b.set_defaults(func=cmd_build)
    v = sub.add_parser("preview")
    v.add_argument("--work", required=True)
    v.set_defaults(func=cmd_preview)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
