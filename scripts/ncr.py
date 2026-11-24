#!/usr/bin/env python3
"""noobit-capcut-rough-cut (ncr) - rough-cut a CapCut project for Thai speech.

Removes pauses, stumbles, false starts, repeated takes and filler words, then writes a NEW
CapCut project "<name> rough cut vN" next to the original (the original is never touched).

Pipeline:
  doctor --install -> projects -> prepare NAME --max-min N -> (read transcript, write edits.json)
  -> estimate -> build -> qa -> [user finishes in CapCut] -> compare (optional)

Requires: macOS, python3 (stdlib only), ffmpeg, whisper-cli (whisper.cpp) + ggml-large-v3.bin.
`doctor --install` installs the missing ones (Homebrew + a 3 GB model download).
"""
import argparse, copy, json, os, platform, re, shutil, subprocess, sys, time, uuid

# Homebrew is often missing from PATH in non-login shells (agents, IDEs)
for _p in ("/opt/homebrew/bin", "/usr/local/bin"):
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _p

# ---------------------------------------------------------------- settings
SPEECH_DB = -35.0       # RMS above this = sound (speech / click)
CLICK = 0.15            # sound blip <= this between two pauses = keyboard/mouse click
MIN_KEEP = 0.20         # never keep a sliver shorter than this (audible click)
LAG = 0.3               # whisper DTW word times run ~0.3 s late
BLIP_MAX, BLIP_GAP = 0.7, 0.3   # a sound island this short, between pauses this long, with no words = อื้ม/breath
PROFILES = {            # padding left around speech at every join (s) + pauses longer than min_sil get trimmed
    "tight":   dict(before=0.03, after=0.04, min_sil=0.18),   # shorts / screen tutorials (fast, TikTok-like)
    "relaxed": dict(before=0.05, after=0.08, min_sil=0.40),   # talking head with natural breathing room
}
HALLUCINATIONS = ["โปรดติดตามตอนต่อไป", "ขอบคุณที่รับชม", "ซับไตเติ้ล", "Subtitles by"]
# hum/hesitation sounds as whisper spells them: อื้ม, อืม, เอ่อ, อ่า, ฮึ ... (อ/ห/ฮ/ม + vowel/tone marks only)
FILLER_RE = re.compile(r"^(?:[เแ]?อ[ัาิีึืุู็่้๊๋ะำ]*[มอ]?[่้]?|[หฮ][ึืุ][่้]?[มอ]?)+$")

MODEL_FILE = "ggml-large-v3.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"
MODEL_BYTES = 3095033483
MODEL_HOME = os.path.expanduser("~/models")
MODEL_CANDIDATES = [os.environ.get("NCR_WHISPER_MODEL"), os.environ.get("NVE_WHISPER_MODEL"),
                    os.path.join(MODEL_HOME, MODEL_FILE), "~/.cache/whisper/" + MODEL_FILE,
                    "~/.cache/hyperframes/whisper/models/" + MODEL_FILE,
                    "/opt/homebrew/share/whisper-cpp/" + MODEL_FILE, "/usr/local/share/whisper-cpp/" + MODEL_FILE]
WHISPER_BIN = os.environ.get("NCR_WHISPER_BIN", "whisper-cli")
THREADS = str(min(8, os.cpu_count() or 4))

DRAFTS = os.path.expanduser(os.environ.get("NCR_DRAFTS", "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"))
HOME_DIR = os.path.expanduser(os.environ.get("NCR_HOME", "~/Movies/noobit-rough-cut"))
DRAFT_FILES = ("draft_info.json", "draft_content.json")
US = 1_000_000

STEPS = [
    "เช็กและติดตั้งโปรแกรมที่ต้องใช้",
    "ถามความยาวคลิปที่ต้องการ",
    "เลือก Project ใน CapCut และปิด CapCut",
    "วิเคราะห์เสียงและถอดเสียงภาษาไทย",
    "อ่านบทพูดและเลือกจุดตัด",
    "สร้าง Project ใหม่ใน CapCut",
    "ตรวจรอยต่อทุกจุด",
    "ส่งมอบงานและสรุปผล",
]


def die(msg, code=1):
    print(f"ncr: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def tc(sec):
    sec = max(0.0, float(sec))
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def uid():
    return str(uuid.uuid4()).upper()


def safe(name):
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "project"


# ---------------------------------------------------------------- work dir
class Project:
    def __init__(self, work):
        self.work = os.path.abspath(work)
        self.path = os.path.join(self.work, "project.json")
        self.data = json.load(open(self.path, encoding="utf-8")) if os.path.exists(self.path) else {}

    def save(self):
        os.makedirs(self.work, exist_ok=True)
        json.dump(self.data, open(self.path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def f(self, name):
        return os.path.join(self.work, name)

    def edits(self):
        p = self.f("edits.json")
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"profiles": {}, "edits": {}}

    @property
    def out_dir(self):
        return os.path.dirname(self.work)


def work_for(name):
    return os.path.join(HOME_DIR, safe(name), ".ncr")


def find_work(args):
    name = getattr(args, "project", None)
    if not name:
        last = os.path.join(HOME_DIR, ".last")
        if os.path.exists(last):
            name = open(last, encoding="utf-8").read().strip()
    if not name:
        die("no project prepared yet - run `ncr.py prepare NAME` first")
    p = Project(work_for(name))
    if not p.data:
        die(f"project '{name}' is not prepared - run `ncr.py prepare \"{name}\"` first")
    return p


# ---------------------------------------------------------------- CapCut drafts
def draft_file(d):
    for n in DRAFT_FILES:
        fp = os.path.join(d, n)
        if os.path.exists(fp):
            return fp
    return None


def draft_dir(x):
    if os.path.isdir(x) and draft_file(x):
        return os.path.abspath(x)
    d = os.path.join(DRAFTS, x)
    if draft_file(d):
        return d
    die(f"CapCut project not found: '{x}' (looked in {DRAFTS}) - run `ncr.py projects` to see the names")


def load_draft(d):
    fp = draft_file(d)
    try:
        return json.load(open(fp, encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        die(f"{fp} is not plain JSON (this CapCut version encrypts its projects) - this skill cannot read it")


def mats_by_id(d):
    out = {}
    for k, v in d["materials"].items():
        if isinstance(v, list):
            for x in v:
                if isinstance(x, dict) and "id" in x:
                    out[x["id"]] = (k, x)
    return out


def main_video_track(d):
    vt = [t for t in d["tracks"] if t["type"] == "video"]
    if not vt:
        die("this project has no video track - import the clip into the timeline first")
    return max(vt, key=lambda t: len(t["segments"]) if t.get("flag", 0) == 0 else -1)


def capcut_running():
    if platform.system() != "Darwin":
        return False
    r = run(["pgrep", "-f", "CapCut.app/Contents/MacOS/CapCut$"])
    return bool(r.stdout.strip())


def clone(D, b, start_us, dur_us, src=None):
    """Copy a segment + its material + referenced materials into draft D with new ids."""
    idmap = {}

    def new(old):
        idmap.setdefault(old, uid())
        return idmap[old]
    k, m = b["material"]
    m2 = copy.deepcopy(m); m2["id"] = new(m["id"])
    D["materials"].setdefault(k, []).append(m2)
    for rk, rm in b["refs"]:
        r2 = copy.deepcopy(rm); r2["id"] = new(rm["id"])
        D["materials"].setdefault(rk, []).append(r2)
    s = copy.deepcopy(b["segment"])
    s["id"] = uid(); s["material_id"] = m2["id"]
    s["extra_material_refs"] = [new(r) for r in s.get("extra_material_refs", [])]
    s["target_timerange"] = dict(start=int(start_us), duration=int(dur_us))
    if src is not None:
        s["source_timerange"] = src
    return s, m2


def draft_items(d):
    """Video segments on the main track -> [{seg, stem, path, src_in, src_out}] (+ skipped ones)."""
    by = mats_by_id(d)
    items, skipped = [], []
    for i, s in enumerate(main_video_track(d)["segments"]):
        k, m = by.get(s["material_id"], (None, {}))
        path = m.get("path")
        if k != "videos" or not path or not os.path.exists(path):
            skipped.append((i, path)); continue
        if (s.get("speed") or 1.0) != 1.0:
            skipped.append((i, f"{path} (speed {s.get('speed')}x)")); continue
        stem = safe(os.path.splitext(os.path.basename(path))[0])
        sr = s["source_timerange"]
        items.append(dict(seg=i, stem=stem, path=path, src_in=sr["start"] / US, src_out=(sr["start"] + sr["duration"]) / US,
                          size=f"{m.get('width')}x{m.get('height')}"))
    return items, skipped


# ---------------------------------------------------------------- audio analysis
def load_rms(p, stem):
    return [tuple(map(float, l.split())) for l in open(p.f(f"{stem}.rms"))]


def load_sil(p, stem, click=True):
    """Pauses as [(start, end)], merging pieces split by tiny gaps or short clicks."""
    out, st = [], None
    for l in open(p.f(f"{stem}.sil")):
        m = re.search(r"silence_start: (-?[\d.]+)", l)
        if m: st = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", l)
        if m and st is not None:
            e = float(m.group(1))
            gap = st - out[-1][1] if out else 9
            if out and (gap < 0.03 or (click and gap <= CLICK and e - st >= 0.3 and out[-1][1] - out[-1][0] >= 0.3)):
                out[-1] = (out[-1][0], e)
            else:
                out.append((st, e))
            st = None
    return out


def analyse_audio(p, stem, media):
    wav = p.f(f"{stem}.wav")
    if not os.path.exists(wav):
        r = run(["ffmpeg", "-v", "error", "-y", "-i", media, "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav])
        if r.returncode: die(f"ffmpeg failed on {media}: {r.stderr[-300:]}")
    r = run(["ffmpeg", "-nostats", "-i", wav, "-af", f"silencedetect=noise={SPEECH_DB}dB:d=0.12", "-f", "null", "-"])
    open(p.f(f"{stem}.sil"), "w").write("\n".join(l for l in r.stderr.splitlines() if "silence_" in l))
    raw = p.f(f"{stem}.rmsraw")
    run(["ffmpeg", "-nostats", "-i", wav, "-af",
         f"asetnsamples=800,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file={raw}",
         "-f", "null", "-"])
    out, t = [], None
    for l in open(raw):
        m = re.search(r"pts_time:([\d.]+)", l)
        if m: t = float(m.group(1))
        m = re.search(r"RMS_level=(.+)", l)
        if m: out.append((t, float(m.group(1)) if "inf" not in m.group(1) else -120.0))
    open(p.f(f"{stem}.rms"), "w").write("".join(f"{a:.3f}\t{b:.1f}\n" for a, b in out))
    os.remove(raw)


def quiet_runs(rms, a, b, min_len=0.12):
    out, st, last = [], None, None
    for t, v in rms:
        if t < a or t > b: continue
        if v <= SPEECH_DB:
            st = t if st is None else st; last = t
        else:
            if st is not None and last - st + 0.05 >= min_len: out.append((st, last + 0.05))
            st = None
    if st is not None and last - st + 0.05 >= min_len: out.append((st, last + 0.05))
    return out


# ---------------------------------------------------------------- transcription (whisper.cpp)
def find_model(arg=None):
    for c in [arg] + MODEL_CANDIDATES:
        if c and os.path.exists(os.path.expanduser(c)):
            return os.path.expanduser(c)
    return None


def whisper_model(arg=None):
    m = find_model(arg)
    if not m: die(f"{MODEL_FILE} not found - run `ncr.py doctor --install`")
    return m


def whisper(wav, out_prefix, model, dtw=True):
    cmd = [WHISPER_BIN, "-m", model, "-f", wav, "--language", "th", "--output-json-full", "-of", out_prefix, "-t", THREADS]
    if dtw:  # flash attention silently disables DTW -> must pass -nfa
        cmd += ["--dtw", "large.v3", "-nfa"]
    r = run(cmd)
    if r.returncode and dtw:  # DTW sometimes asserts on tiny segments -> retry without word timing
        return whisper(wav, out_prefix, model, dtw=False)
    return r.returncode == 0


def whisper_text(model, wav):
    return run([WHISPER_BIN, "-m", model, "-f", wav, "--language", "th", "-nt", "-t", THREADS]).stdout


def plan_chunks(sil, dur, size=300.0):
    """~5 min chunks split in the middle of long pauses."""
    big = [(a, b) for a, b in sil if b - a > 1.0]
    cuts, t = [0.0], size
    while t < dur - 120 and big:
        a, b = min(big, key=lambda x: abs((x[0] + x[1]) / 2 - t))
        c = max(a, b - 0.3)
        if c <= cuts[-1] + 30: break
        cuts.append(round(c, 2)); t = c + size
    cuts.append(dur)
    return list(zip(cuts, cuts[1:]))


def transcribe(p, stem, model):
    sil = load_sil(p, stem, click=False)
    dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                     p.f(f"{stem}.wav")]).stdout.strip())
    lead = sil[0][1] - 0.3 if sil and sil[0][0] <= 0.05 and sil[0][1] > 2 else 0.0   # whisper hallucinates on silence
    chunks = [(max(a, lead) if i == 0 else a, b) for i, (a, b) in enumerate(plan_chunks(sil, dur))]
    words, segs = [], []
    for i, (a, b) in enumerate(chunks):
        cw, cj = p.f(f"{stem}.c{i}.wav"), p.f(f"{stem}.c{i}")
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-to", str(b), "-i", p.f(f"{stem}.wav"), cw])
        print(f"  {stem}: ถอดเสียงช่วงที่ {i + 1}/{len(chunks)} ({a:.0f}-{b:.0f} วิ)", flush=True)
        if not whisper(cw, cj, model) or not os.path.exists(cj + ".json"):
            print(f"  ! whisper failed on chunk {i}", flush=True); continue
        d = json.load(open(cj + ".json", encoding="latin-1"))
        for s in d["transcription"]:
            toks = []
            for t in s.get("tokens", []):
                if t["text"].startswith("[_"): continue
                x = t.get("t_dtw", -1)
                tt = (x / 100 if x >= 0 else t["offsets"]["from"] / 1000) + a   # t_dtw unit = 10 ms
                toks.append((round(tt, 2), t["text"]))
            text = b"".join(t.encode("latin-1") for _, t in toks).decode("utf-8", "replace").strip()
            if not toks or any(h in text for h in HALLUCINATIONS): continue
            if all(any(sa + 0.3 < tt < sb - 0.3 for sa, sb in sil if sb - sa > 2) for tt, _ in toks): continue
            words += toks
            segs.append((toks[0][0], text))
        for f in (cw, cj + ".json"):
            if os.path.exists(f): os.remove(f)
    json.dump(dict(words=words, segments=segs), open(p.f(f"{stem}.words.json"), "w"))
    write_transcript(p, stem)


def load_words(p, stem):
    fp = p.f(f"{stem}.words.json")
    if not os.path.exists(fp): return [], []
    d = json.load(open(fp))
    return [(t, s.encode("latin-1")) for t, s in d["words"]], d["segments"]


def write_transcript(p, stem):
    _, segs = load_words(p, stem)
    ev = [(a, f"   ~~ pause {a:.2f}-{b:.2f} ({b - a:.1f}s)") for a, b in load_sil(p, stem) if b - a >= 0.7]
    prev = None
    for t, txt in segs:
        if txt == prev: continue
        prev = txt
        ev.append((t, f"{t:8.1f} {txt}"))
    open(p.f(f"{stem}.transcript.txt"), "w", encoding="utf-8").write("\n".join(x for _, x in sorted(ev)) + "\n")


def snippet(p, model, stem, a, b):
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", p.f(f"{stem}.wav"), p.f("edge.wav")])
    return " ".join(whisper_text(model, p.f("edge.wav")).split())


# ---------------------------------------------------------------- cut planning
def onset(sil, t, back=0.8, fwd=0.6):
    c = [e for s, e in sil if t - back <= e <= t + fwd]
    return min(c, key=lambda e: abs(e - t)) if c else t


def profile_of(p, ed, stem):
    return PROFILES[ed.get("profiles", {}).get(stem) or p.data.get("profile", "tight")]


def plan_item(p, it, ed):
    """-> (removed ranges [a, b, type, note], kept ranges [[a, b]], content-cut points [(t, note, check)])"""
    stem = it["stem"]
    prof = profile_of(p, ed, stem)
    sil = load_sil(p, stem)
    a0, a1 = it["src_in"], it["src_out"]
    removes, points = [], []
    edits = ed.get("edits", {}).get(stem, [])
    # {"from", "to", "keep": true} shields a range from pause trimming (e.g. a result playing on screen in silence)
    protect = [(x["from"], x["to"]) for x in edits if x.get("keep")]
    free = lambda s, e: not any(s < pb and e > pa for pa, pb in protect)
    for s, e in sil:
        if e - s > prof["min_sil"] and free(s, e):
            removes.append([a0 if s <= a0 + 0.01 else s + prof["after"], a1 if e >= a1 - 0.01 else e - prof["before"],
                            "silence", f"{e - s:.1f}s"])
    for x in edits:
        if x.get("keep"): continue
        a, b = x["from"], x["to"]
        if x.get("snap", False): a, b = onset(sil, a), onset(sil, b)
        removes.append([a, b, x.get("type", "cut"), x.get("note", "")])
        if x.get("type") != "blip":
            points.append((b, x.get("note", ""), x.get("check", 0)))
    removes = sorted([[max(a, a0), min(b, a1), t, n] for a, b, t, n in removes if min(b, a1) > max(a, a0)])
    merged = []
    for r in removes:
        if merged and r[0] <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], r[1])
            if r[2] != "silence": merged[-1][2:] = r[2:]
        else:
            merged.append(list(r))
    keeps, cur = [], a0
    for a, b, *_ in merged:
        if a - cur > 0.001: keeps.append([cur, a])
        cur = max(cur, b)
    if a1 - cur > 0.001: keeps.append([cur, a1])
    rms = load_rms(p, stem)
    tight = []
    for s, e in keeps:   # leave only before/after padding of silence around speech at every join
        loud = [t for t, v in rms if s <= t < e and v > SPEECH_DB]
        if not free(s, e):
            tight.append([s, e]); continue
        if loud:
            s2 = max(s, loud[0] - prof["before"])
            e2 = min(e, loud[-1] + 0.05 + prof["after"])
            if e2 - s2 >= MIN_KEEP: tight.append([s2, e2])
    return merged, tight, points


def find_blips(p, stem, edits, model_needed=True):
    """Short sounds between two pauses that are not words (อื้ม, breath, lip smack); each is re-transcribed alone."""
    sil = load_sil(p, stem)
    taken = [(e["from"], e["to"]) for e in edits]
    cache_f = p.f(f"{stem}.blips.json")
    cache = json.load(open(cache_f, encoding="utf-8")) if os.path.exists(cache_f) else {}
    model, out = None, []
    for (a0, a1), (b0, b1) in zip(sil, sil[1:]):
        if b0 - a1 > BLIP_MAX or a1 - a0 < BLIP_GAP or b1 - b0 < BLIP_GAP: continue
        if any(f <= a1 and b0 <= t for f, t in taken): continue
        key = f"{a1:.2f}-{b0:.2f}"
        if key not in cache:
            if not model_needed: continue
            model = model or whisper_model()
            cache[key] = snippet(p, model, stem, max(0, a1 - 0.05), b0 + 0.05)
        txt = cache[key]
        toks = [t for t in re.split(r"[\s\W_]+", txt) if t]
        if toks and not all(FILLER_RE.match(t) for t in toks) and not any(h in txt for h in HALLUCINATIONS):
            continue
        out.append({"from": round(a1 - 0.02, 2), "to": round(b0 + 0.02, 2), "type": "blip",
                    "note": f"เสียงสั้น {b0 - a1:.2f} วิ «{txt or '-'}» (อื้ม/หายใจ)"})
    json.dump(cache, open(cache_f, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return out


def estimate(p, ed, with_blips=False):
    total, rows = 0.0, []
    for it in p.data["items"]:
        e2 = copy.deepcopy(ed)
        if with_blips:
            e2.setdefault("edits", {}).setdefault(it["stem"], []).extend(
                find_blips(p, it["stem"], ed.get("edits", {}).get(it["stem"], []), model_needed=False))
        merged, keeps, _ = plan_item(p, it, e2)
        kept = sum(b - a for a, b in keeps)
        by = {}
        for a, b, t, n in merged: by[t] = by.get(t, 0) + (b - a)
        rows.append((it, kept, by)); total += kept
    return total, rows


# ---------------------------------------------------------------- commands: setup
def cmd_steps(args):
    print("📋 ขั้นตอนการทำงาน")
    for i, s in enumerate(STEPS, 1):
        mark = "✅" if i < args.current else ("▶️" if i == args.current else "⬜")
        print(f"{mark} {i}. {s}")


def check_tools():
    rows = []
    rows.append(("macOS", platform.system() == "Darwin", platform.mac_ver()[0] or platform.system()))
    rows.append(("Python 3.8+", sys.version_info >= (3, 8), sys.version.split()[0]))
    rows.append(("Homebrew", bool(shutil.which("brew")), shutil.which("brew") or "-"))
    for t in ("ffmpeg", "ffprobe", WHISPER_BIN):
        rows.append((t, bool(shutil.which(t)), shutil.which(t) or "-"))
    m = find_model()
    rows.append((f"Whisper model ({MODEL_FILE}, 3 GB)", bool(m), m or "-"))
    rows.append(("CapCut projects folder", os.path.isdir(DRAFTS), DRAFTS))
    return rows


def print_rows(rows):
    for name, ok, info in rows:
        print(f"{'✅' if ok else '❌'} {name:36s} {info}")


def download_model():
    os.makedirs(MODEL_HOME, exist_ok=True)
    dst = os.path.join(MODEL_HOME, MODEL_FILE)
    part = dst + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    free = shutil.disk_usage(MODEL_HOME).free
    if free < MODEL_BYTES - have + 500_000_000:
        die(f"พื้นที่ดิสก์ไม่พอ: ต้องการ ~{(MODEL_BYTES - have) / 1e9 + 0.5:.1f} GB เหลือ {free / 1e9:.1f} GB")
    print(f"⬇️  กำลังดาวน์โหลด Whisper model (~3.1 GB) ไปที่ {dst}\n   (ดาวน์โหลดต่อจากเดิมได้ถ้าเน็ตหลุด แค่สั่งใหม่อีกครั้ง)", flush=True)
    r = subprocess.run(["curl", "-L", "--fail", "-C", "-", "--retry", "3", "--progress-bar", "-o", part, MODEL_URL]) \
        if have != MODEL_BYTES else subprocess.CompletedProcess([], 0)
    if r.returncode not in (0, 33) or not os.path.exists(part):
        die("ดาวน์โหลด model ไม่สำเร็จ - ลองสั่ง `ncr.py doctor --install` ใหม่อีกครั้ง")
    size = os.path.getsize(part)
    if size != MODEL_BYTES:
        die(f"ไฟล์ model ไม่ครบ ({size} / {MODEL_BYTES} bytes) - สั่ง `ncr.py doctor --install` ใหม่เพื่อโหลดต่อ")
    os.replace(part, dst)
    print(f"✅ model พร้อมใช้: {dst}")


def cmd_doctor(args):
    rows = check_tools()
    print("🔎 เช็กโปรแกรมที่ต้องใช้\n")
    print_rows(rows)
    bad = {n for n, ok, _ in rows if not ok}
    if not bad:
        print("\nพร้อมใช้งานครบแล้ว ✅"); return
    if "macOS" in bad:
        die("skill นี้รองรับเฉพาะ macOS (CapCut บน Windows เข้ารหัสไฟล์ project ไว้ อ่านไม่ได้)", 3)
    if "CapCut projects folder" in bad:
        print(f"\n! ไม่เจอโฟลเดอร์ project ของ CapCut: {DRAFTS}\n  ติดตั้ง CapCut (https://www.capcut.com) แล้วสร้าง project อย่างน้อย 1 อันก่อน"
              "\n  หรือถ้าย้ายที่เก็บ project ไว้ ให้ตั้ง NCR_DRAFTS=/path/to/com.lveditor.draft")
    if not args.install:
        print("\nสั่ง `ncr.py doctor --install` เพื่อติดตั้งตัวที่ขาดให้อัตโนมัติ"); sys.exit(1)
    pkgs = []
    if bad & {"ffmpeg", "ffprobe"}: pkgs.append("ffmpeg")
    if WHISPER_BIN in bad: pkgs.append("whisper-cpp")
    if pkgs:
        if not shutil.which("brew"):
            print("\n❗ ต้องติดตั้ง Homebrew ก่อน (ต้องใส่รหัสผ่านเครื่อง จึงต้องให้ผู้ใช้รันเองใน Terminal):\n\n"
                  '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"\n\n'
                  "ติดตั้งเสร็จแล้วสั่ง `ncr.py doctor --install` อีกครั้ง")
            sys.exit(2)
        print(f"\n📦 brew install {' '.join(pkgs)}", flush=True)
        r = subprocess.run(["brew", "install"] + pkgs)
        if r.returncode: die("brew install ไม่สำเร็จ - ดูข้อความ error ด้านบน")
    if not find_model():
        download_model()
    rows = check_tools()
    print("\n🔎 เช็กอีกรอบ\n"); print_rows(rows)
    if all(ok for n, ok, _ in rows): print("\nพร้อมใช้งานครบแล้ว ✅")
    else: sys.exit(1)


def cmd_projects(args):
    if not os.path.isdir(DRAFTS): die(f"CapCut projects folder not found: {DRAFTS}")
    out = []
    for name in os.listdir(DRAFTS):
        d = os.path.join(DRAFTS, name)
        fp = draft_file(d) if os.path.isdir(d) else None
        if not fp: continue
        dur = 0
        mp = os.path.join(d, "draft_meta_info.json")
        if os.path.exists(mp):
            try: dur = json.load(open(mp, encoding="utf-8")).get("tm_duration", 0) / US
            except ValueError: pass
        out.append((os.path.getmtime(fp), name, dur))
    if not out: die("ยังไม่มี project ใน CapCut - เปิด CapCut สร้าง project แล้ววางคลิปลง timeline ก่อน")
    out.sort(reverse=True)
    print(f"Project ใน CapCut (ล่าสุดอยู่บน) - {DRAFTS}\n")
    for mt, name, dur in out[:args.limit]:
        tag = "  (ผลลัพธ์จาก skill นี้)" if re.search(r" rough cut v\d+$", name) else ""
        print(f"  {name:32s} {tc(dur):>8s}   แก้ล่าสุด {time.strftime('%Y-%m-%d %H:%M', time.localtime(mt))}{tag}")
    print(f"\nCapCut ตอนนี้: {'🔴 เปิดอยู่' if capcut_running() else '🟢 ปิดแล้ว'}")


def cmd_capcut(args):
    if capcut_running():
        print("🔴 CapCut ยังเปิดอยู่ - ต้องปิด CapCut ก่อน (Cmd+Q) ไม่อย่างนั้นตอนปิด CapCut จะเขียนทับรายการ project และ project ใหม่จะหาย")
        sys.exit(1)
    print("🟢 CapCut ปิดแล้ว พร้อมสร้าง project ใหม่")


# ---------------------------------------------------------------- commands: analysis
def cmd_prepare(args):
    dd = draft_dir(args.draft); d = load_draft(dd)
    name = os.path.basename(dd)
    items, skipped = draft_items(d)
    for i, path in skipped:
        print(f"  ! คลิปที่ {i + 1} บน timeline ใช้ไม่ได้ ({path}) - จะคงไว้ตามเดิมไม่ตัด")
    if not items: die("ไม่เจอคลิปวิดีโอบน track หลักที่ไฟล์ต้นฉบับยังอยู่ในเครื่อง")
    main = main_video_track(d)
    others = [t for t in d["tracks"] if t is not main and t.get("segments")]
    if others:
        kinds = ", ".join(sorted({t["type"] for t in others}))
        print(f"  ! project นี้มีของบน track อื่นอยู่แล้ว ({kinds}) - project ใหม่จะคงไว้ที่ตำแหน่งเวลาเดิม ซึ่งจะไม่ตรงกับคลิปที่ตัดแล้ว"
              "\n    แนะนำให้ตัด rough cut ก่อนใส่ข้อความ เพลง หรือเอฟเฟกต์")
    p = Project(args.work or work_for(name))
    media = {}
    for it in items:
        media.setdefault(it["stem"], dict(path=it["path"], size=it["size"]))
    old_max = p.data.get("max_min")
    p.data = dict(draft=dd, draft_name=name, fps=d.get("fps") or 30, items=items, media=media,
                  max_min=args.max_min if args.max_min is not None else old_max, profile=args.profile,
                  draft_sig=[(it["seg"], round(it["src_in"], 3), round(it["src_out"], 3)) for it in items])
    p.save()
    os.makedirs(HOME_DIR, exist_ok=True)
    open(os.path.join(HOME_DIR, ".last"), "w", encoding="utf-8").write(name)
    for stem, m in media.items():
        print(f"- {stem}: {m['size']} -> วิเคราะห์เสียง", flush=True)
        analyse_audio(p, stem, m["path"])
    if not args.no_transcribe:
        model = whisper_model(args.model)
        for stem in media:
            if args.force or not os.path.exists(p.f(f"{stem}.words.json")):
                transcribe(p, stem, model)
    ed = p.edits()
    ed.setdefault("profiles", {}); ed.setdefault("edits", {})
    for stem in media:
        ed["profiles"].setdefault(stem, args.profile); ed["edits"].setdefault(stem, [])
    json.dump(ed, open(p.f("edits.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    raw = sum(it["src_out"] - it["src_in"] for it in items)
    est, _ = estimate(p, ed)
    print(f"\nwork dir: {p.work}\ntranscript: {', '.join(p.f(s + '.transcript.txt') for s in media)}\nedits: {p.f('edits.json')}")
    print(f"ความยาวเดิม {tc(raw)} -> ถ้าตัดแค่ช่วงเงียบ ~{tc(est)}" +
          (f" | เป้าหมาย ≤ {p.data['max_min']:g} นาที" if p.data.get("max_min") else ""))


def cmd_estimate(args):
    p = find_work(args); ed = p.edits()
    total, rows = estimate(p, ed, with_blips=True)
    raw = sum(it["src_out"] - it["src_in"] for it in p.data["items"])
    for it, kept, by in rows:
        print(f"  {it['stem']}: {tc(it['src_out'] - it['src_in'])} -> {tc(kept)}  " +
              " ".join(f"{k}:{v:.0f}s" for k, v in sorted(by.items())))
    print(f"รวม {tc(raw)} -> ~{tc(total)}")
    mx = p.data.get("max_min")
    if mx:
        over = total - mx * 60
        print(f"เป้าหมาย ≤ {mx:g} นาที: " + (f"✅ ผ่าน (เหลือที่ว่าง {tc(-over)})" if over <= 0 else
                                            f"❌ ยาวเกิน {tc(over)} - ต้องตัดเนื้อหาออกเพิ่ม (ดู references/cutting-rules.md §4)"))


def cmd_words(args):
    p = find_work(args)
    W, _ = load_words(p, args.clip)
    sil = load_sil(p, args.clip)
    for rng in args.ranges:
        a, b = map(float, rng.split(":"))
        ev = [(x, t) for x, t in W if a <= x <= b] + \
             [(s, f" [pause {s:.2f}-{e:.2f}] ".encode()) for s, e in sil if a <= s <= b and e - s >= 0.15]
        out, last = b"", -9
        for x, t in sorted(ev, key=lambda z: z[0]):
            if not t.startswith(b" [pause") and x - last >= 0.8:
                out += f"|{x:.1f}|".encode(); last = x
            out += t
        print(f"== {args.clip} {rng}\n" + out.decode("utf-8", "replace"))


def cmd_dip(args):
    p = find_work(args)
    rows = load_rms(p, args.clip)
    for w in args.ranges:
        a, b = map(float, w.split(":"))
        seg = [(t, v) for t, v in rows if a <= t <= b]
        if len(seg) < 3: print(f"{w}: too short"); continue
        i = min(range(len(seg) - 2), key=lambda k: sum(v for _, v in seg[k:k + 3]))
        avg = sum(v for _, v in seg[i:i + 3]) / 3
        verdict = "CLEAN" if avg < -40 else ("weak" if avg < SPEECH_DB else "none")
        print(f"{w}: dip {seg[i + 1][0]:.2f} ({avg:.1f} dB, {verdict})  " + " ".join(f"{v:.0f}" for _, v in seg))


def cmd_spot(args):
    p = find_work(args)
    tmp = p.f("spot.wav")
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(args.start), "-to", str(args.end), "-i", p.f(f"{args.clip}.wav"), tmp])
    r = run([WHISPER_BIN, "-m", whisper_model(), "-f", tmp, "--language", "th", "-t", THREADS])
    print(r.stdout.strip() or "(no speech)")


def char_times(W):
    """whisper byte-pieces [(t, bytes)] -> (text, per-char start time)."""
    buf, tm = b"", []
    for t, b in W: buf += b; tm += [t] * len(b)
    chars, ct, i = [], [], 0
    while i < len(buf):
        c = buf[i]; n = 1 if c < 0x80 else 2 if c >> 5 == 6 else 3 if c >> 4 == 14 else 4 if c >> 3 == 30 else 1
        chars.append(buf[i:i + n].decode("utf-8", "replace")); ct.append(tm[i]); i += n
    return "".join(chars), ct


def find_fillers(p, stem, words):
    """Habitual connectors that open a phrase (after a pause / ending particle) and can go without changing the meaning."""
    W, _ = load_words(p, stem); rms = load_rms(p, stem)
    text, ct = char_times(W)
    res = []

    def dip(lo, hi):
        seg = [(t, v) for t, v in rms if lo <= t <= hi]
        if len(seg) < 3: return None, 0.0
        i = min(range(len(seg) - 2), key=lambda k: sum(v for _, v in seg[k:k + 3]))
        return seg[i + 1][0], sum(v for _, v in seg[i:i + 3]) / 3
    for m in re.finditer("|".join(map(re.escape, words)), text):
        s, e = m.span()
        t0 = ct[s] - LAG
        nxt = next((ct[k] for k in range(e, len(ct)) if ct[k] > ct[s]), ct[s] + 0.6)
        t1 = nxt - LAG
        pre = [r for r in quiet_runs(rms, t0 - 0.9, t0 + 0.2) if t0 - 0.45 <= r[1] <= t0 + 0.2]
        after_particle = re.search(r"(ครับ|คะ|ค่ะ|นะ|เนาะ|เนอะ|นั่นเอง|เลย|แล้ว)\s*$", text[max(0, s - 8):s])
        if pre: start, a0 = pre[-1][1], -60.0
        elif after_particle: start, a0 = dip(t0 - 0.3, t0 + 0.12)
        else: continue          # mid-phrase connector: the meaning usually depends on it
        if start is None: continue
        end, avg = dip(t1 - 0.2, t1 + 0.3)
        if end is None: continue
        avg = max(avg, a0)
        if end - start < 0.15 or end - start > 1.0: continue
        q = "CLEAN" if avg < -40 else ("weak" if avg < SPEECH_DB else "none")
        res.append(dict(stem=stem, word=m.group(0), start=round(start, 2), end=round(end, 2), q=q, db=round(avg, 1),
                        ctx=text[max(0, s - 18):s].replace("\n", " ") + "【" + m.group(0) + "】" + text[e:e + 26].replace("\n", " ")))
    return res


def join_audio(p, stem, a, b, out, pad):
    run(["ffmpeg", "-v", "error", "-y", "-i", p.f(f"{stem}.wav"), "-filter_complex",
         f"[0:a]atrim={max(0, a - pad):.3f}:{a:.3f},asetpts=N/SR/TB[x];[0:a]atrim={b:.3f}:{b + pad:.3f},asetpts=N/SR/TB[y];[x][y]concat=n=2:v=0:a=1[o]",
         "-map", "[o]", out])


def verify_cut(p, model, stem, word, t0, after, before="", pad=1.4):
    """Try cuts between RMS minima around t0, transcribe the joined audio, accept the first one where the filler is
    gone, the next words survive and the ending particle before it survives (whisper word times are too rough)."""
    rms = load_rms(p, stem)
    seg = [(t, v) for t, v in rms if t0 - 0.7 <= t <= t0 + 1.0]
    mins = [seg[i][0] for i in range(1, len(seg) - 1) if seg[i][1] <= seg[i - 1][1] and seg[i][1] <= seg[i + 1][1]]
    lo, hi = (0.12, 0.55) if word == "ซึ่ง" else (0.22, 0.8)
    pairs = sorted([(a, b) for a in mins for b in mins if lo <= b - a <= hi],
                   key=lambda ab: abs(ab[0] - (t0 - 0.1)) + 0.3 * abs(ab[1] - ab[0] - (lo + hi) / 2))
    nxt = re.sub(r"\s+", "", after)[:5]
    prv = re.sub(r"\s+", "", before)[-3:]
    w = p.f("sim.wav")
    for a, b in pairs[:8]:
        join_audio(p, stem, a, b, w, pad)
        tx = "".join(whisper_text(model, w).split())
        i = tx.rfind(nxt[:3])
        forms = [word] + (["แล้วก", "และก็", "แล้วค็"] if word == "แล้วก็" else [])
        if i < 0 or any(f in tx[max(0, i - len(f) - 3):i] for f in forms): continue
        if prv and prv not in tx[max(0, i - 10):i]: continue
        return a, b, tx
    return None


def cmd_fillers(args):
    p = find_work(args)
    stems = args.clips or list(p.data.get("media", {}))
    allr = []
    model = whisper_model() if args.verify else None
    for st in stems:
        if not os.path.exists(p.f(f"{st}.words.json")): continue
        r = find_fillers(p, st, args.words)
        if args.verify:
            for x in r:
                v = verify_cut(p, model, st, x["word"].replace("และก็", "แล้วก็"), x["start"], x["ctx"].split("】")[1], x["ctx"].split("【")[0])
                if v: x["start"], x["end"], x["q"], x["heard"] = round(v[0], 2), round(v[1], 2), "VERIFIED", v[2]
                else: x["q"] = "none"
        allr += r
        print(f"== {st}: {len(r)} candidates ({sum(x['q'] in ('CLEAN', 'VERIFIED') for x in r)} usable)")
        for x in r:
            print(f"  {x['start']:8.2f}-{x['end']:7.2f} {x['q']:8s} {x['db']:6.1f}dB  {x['ctx']}" +
                  (f"\n{'':20s}heard after cut: …{x['heard'][-60:]}" if x.get("heard") else ""), flush=True)
    ok = [x for x in allr if x["q"] in ("CLEAN", "VERIFIED")]
    print(f"\ntotal {len(allr)} phrase-opening fillers, usable {len(ok)} (~{sum(x['end'] - x['start'] for x in ok):.0f}s)")
    if args.emit:
        out = {}
        for x in allr:
            if x["q"] == "none": continue
            e = {"from": x["start"], "to": x["end"], "type": "filler", "note": f"ตัดคำติดปาก '{x['word']}' ต้นวลี"}
            if x["q"] != "CLEAN": e["check"] = 1
            out.setdefault(x["stem"], []).append(e)
        json.dump(out, open(args.emit, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"wrote {args.emit} - read every ctx, drop the ones whose sentence needs the word, then merge into edits.json")


def cmd_fit(args):
    """When `dip` says weak/none: try FROM/TO pairs at RMS minima, transcribe each joined result and keep the ones
    where TAIL still ends the kept part and HEAD starts the next."""
    p = find_work(args)
    model = whisper_model()
    rms = load_rms(p, args.clip)

    def mins(t):
        seg = [(x, v) for x, v in rms if t - args.span <= x <= t + args.span]
        m = [seg[i] for i in range(1, len(seg) - 1) if seg[i][1] <= seg[i - 1][1] and seg[i][1] <= seg[i + 1][1]]
        return [x for x, v in sorted(m, key=lambda z: z[1])[:args.n]] or [t]
    norm = lambda s: re.sub(r"\s+", "", s)
    tail, head = norm(args.tail or ""), norm(args.head or "")
    w, res = p.f("fit.wav"), []
    for a in mins(args.start):
        for b in mins(args.end):
            if b - a < 0.1: continue
            join_audio(p, args.clip, a, b, w, 1.6)
            tx = " ".join(whisper_text(model, w).split())
            t = norm(tx)
            i = t.rfind(tail[-3:]) if tail else -1
            ok_t = not tail or i >= 0
            after = t[i + 3:] if i >= 0 else t
            ok_h = not head or head[:4] in after[:6]
            dup = bool(head) and t.count(head[:4]) > 1 or any(norm(d) in after for d in (args.drop or []))
            res.append((ok_t + ok_h - dup, a, b, tx, ok_t, ok_h, dup))
    res.sort(key=lambda r: (-r[0], r[2] - r[1]))
    for score, a, b, tx, ok_t, ok_h, dup in res[:8]:
        print(f"{'OK ' if score == 2 else '?  '} from {a:.2f} to {b:.2f}  tail:{'y' if ok_t else 'n'} "
              f"head:{'y' if ok_h else 'n'}{' DUP' if dup else ''}  «{tx}»", flush=True)
    print('Pick an OK line whose text reads naturally, put from/to in edits.json with "check": 1.')


# ---------------------------------------------------------------- build
def cmd_build(args):
    p = find_work(args); ed = p.edits()
    if capcut_running() and not args.force:
        die("🔴 CapCut ยังเปิดอยู่ - ปิด CapCut ก่อน (Cmd+Q) แล้วสั่งใหม่ (CapCut เขียนทับรายการ project ตอนปิด project ใหม่จะหาย)", 4)
    src_dir = p.data["draft"]; D = load_draft(src_dir)
    items_now, _ = draft_items(D)
    if [(it["seg"], round(it["src_in"], 3), round(it["src_out"], 3)) for it in items_now] != [tuple(x) for x in p.data["draft_sig"]]:
        die("project ต้นฉบับถูกแก้ไขหลังจาก prepare - สั่ง `ncr.py prepare` ใหม่ก่อน")
    fps = float(D.get("fps") or 30)
    fr = lambda sec: int(round(sec * fps))
    us = lambda frames: int(round(frames * US / fps))
    by = mats_by_id(D)
    vt = main_video_track(D)
    old_segs = vt["segments"]
    items = {it["seg"]: it for it in p.data["items"]}
    new_segs, report, tl = [], [], 0
    for i, seg in enumerate(old_segs):
        it = items.get(i)
        if it is None:   # unusable segment: pass through
            s = copy.deepcopy(seg); n = fr(seg["target_timerange"]["duration"] / US)
            s["target_timerange"] = dict(start=us(tl), duration=us(n)); new_segs.append(s); tl += n; continue
        blips = [] if args.no_blips else find_blips(p, it["stem"], ed.get("edits", {}).get(it["stem"], []))
        ed2 = copy.deepcopy(ed)
        ed2.setdefault("edits", {}).setdefault(it["stem"], []).extend(blips)
        if blips: print(f"  {it['stem']}: ตัดเสียงอื้ม/หายใจ {len(blips)} จุด")
        merged, keeps, points = plan_item(p, it, ed2)
        k, vmat = by[seg["material_id"]]
        rep = dict(clip=os.path.basename(it["path"]), stem=it["stem"], raw=it["src_out"] - it["src_in"],
                   keeps=keeps, removes=merged, cuts=[], blips=len(blips))
        owner = {}   # each content cut is reported at the start of the first kept piece after it
        for b, note, chk in points:
            kk = next((j for j, (s0, e0) in enumerate(keeps) if e0 > b + 0.05), None)
            if kk is not None: owner.setdefault(kk, []).append((b, note, chk))
        for j, (s0, e0) in enumerate(keeps):
            n = fr(e0 - s0)
            if n < 1: continue
            b = dict(segment=seg, material=[k, vmat],
                     refs=[list(by[r]) for r in dict.fromkeys(seg.get("extra_material_refs", [])) if r in by])
            s, _ = clone(D, b, us(tl), us(n), src=dict(start=int(round(s0 * US)), duration=us(n)))
            new_segs.append(s)
            for bpt, note, chk in owner.get(j, []):
                rep["cuts"].append(dict(tc=tc(tl / fps), src=round(bpt, 2), note=note, check=chk))
            tl += n
        rep["kept"] = sum(e - s for s, e in keeps)
        report.append(rep)
    old_ids = {r for s in old_segs for r in [s["material_id"]] + s.get("extra_material_refs", [])}
    vt["segments"] = new_segs
    used = {r for t in D["tracks"] for s in t["segments"] for r in [s["material_id"]] + s.get("extra_material_refs", [])}
    for kk, v in D["materials"].items():
        if isinstance(v, list):
            D["materials"][kk] = [x for x in v if not (isinstance(x, dict) and x.get("id") in old_ids and x["id"] not in used)]
    total = tl / fps
    D["duration"] = us(tl)
    D["update_time"] = int(time.time())

    # ---- write a NEW project folder
    name = args.name or f"{p.data['draft_name']} rough cut v{args.version}"
    dst = os.path.join(DRAFTS, name)
    if os.path.exists(dst):
        if not args.overwrite: die(f"มี project ชื่อ '{name}' อยู่แล้ว - ใช้ --version {args.version + 1} หรือ --overwrite")
        shutil.rmtree(dst)
    shutil.copytree(src_dir, dst)
    meta_p = os.path.join(dst, "draft_meta_info.json")
    meta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
    proj_p = os.path.join(dst, "Timelines", "project.json")
    proj = json.load(open(proj_p, encoding="utf-8")) if os.path.exists(proj_p) else {}
    old_ids2 = [x for x in (D.get("id"), meta.get("draft_id"), proj.get("id")) if x]
    swap = {o: uid() for o in old_ids2}
    D["id"] = swap.get(D.get("id"), uid())
    body = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    tdir = os.path.join(dst, "Timelines")
    for o, n2 in swap.items():
        if os.path.isdir(os.path.join(tdir, o)): os.rename(os.path.join(tdir, o), os.path.join(tdir, n2))
    for root_, _, files in os.walk(dst):          # swap ids everywhere (project.json, layout, meta, ...)
        for fn in files:
            fp = os.path.join(root_, fn)
            if fn.endswith((".jpg", ".png", ".mp4", ".wav")): continue
            try: txt = open(fp, encoding="utf-8").read()
            except (UnicodeDecodeError, IsADirectoryError): continue
            new = txt
            for o, n2 in swap.items(): new = new.replace(o, n2)
            if new != txt: open(fp, "w", encoding="utf-8").write(new)
    dname = os.path.basename(draft_file(src_dir))
    targets = [dname, dname + ".bak", "template-2.tmp"]
    for base in [dst, os.path.join(tdir, D["id"])]:
        for x in targets:
            fp = os.path.join(base, x)
            if os.path.exists(fp): open(fp, "w", encoding="utf-8").write(body)
    mini = os.path.join(tdir, D["id"], "attachment", "patch", "mini_draft.json")
    if os.path.exists(mini): os.remove(mini)   # cached preview of the uncut timeline
    now = int(time.time() * US)
    new_draft_id = swap.get(meta.get("draft_id"), uid())
    if os.path.exists(meta_p):
        meta = json.load(open(meta_p, encoding="utf-8"))
        meta.update(draft_fold_path=dst, draft_name=name, draft_id=new_draft_id, tm_duration=us(tl),
                    tm_draft_create=now, tm_draft_modified=now)
        json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False)
    rp = os.path.join(DRAFTS, "root_meta_info.json")   # CapCut's project list (backup first)
    if os.path.exists(rp):
        shutil.copy2(rp, rp + ".ncr-backup")
        root = json.load(open(rp, encoding="utf-8"))
        store = root.setdefault("all_draft_store", [])
        tmpl = next((e for e in store if e.get("draft_fold_path") == src_dir), store[0] if store else {})
        store[:] = [e for e in store if e.get("draft_fold_path") != dst]
        e = copy.deepcopy(tmpl)
        e.update(draft_fold_path=dst, draft_id=new_draft_id, draft_name=name, tm_duration=us(tl),
                 draft_json_file=os.path.join(dst, dname), draft_cover=os.path.join(dst, "draft_cover.jpg"),
                 tm_draft_create=now, tm_draft_modified=now)
        store.insert(0, e)
        root["draft_ids"] = root.get("draft_ids", 0) + 1
        json.dump(root, open(rp, "w", encoding="utf-8"), ensure_ascii=False)

    json.dump(dict(fps=fps, name=name, report=report), open(p.f("plan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rpt = os.path.join(p.out_dir, f"{safe(name)}_report.md")
    write_report(rpt, name, report, total, p.data.get("max_min"))
    raw = sum(r["raw"] for r in report)
    print(f"✅ สร้าง project ใหม่ใน CapCut: {name}\n   {tc(raw)} -> {tc(total)} ({len(new_segs)} ช่วง)\n   รายงาน: {rpt}")


def write_report(path, name, report, total, max_min):
    L = [f"# รายงาน Rough Cut - {name}", "", f"เปิด CapCut แล้วเลือก project **{name}** (project เดิมไม่ถูกแก้)", "",
         "| คลิป | ก่อนตัด | หลังตัด | ตัดช่วงเงียบ | ตัดคำผิด/พูดซ้ำ/เนื้อหา |", "|---|---|---|---|---|"]
    for r in report:
        by = {}
        for a, b, t, n in r["removes"]: by[t] = by.get(t, 0) + (b - a)
        L.append(f"| {r['clip']} | {tc(r['raw'])} | **{tc(r['kept'])}** | {tc(by.get('silence', 0))} | "
                 f"{tc(sum(v for k, v in by.items() if k != 'silence'))} |")
    goal = ""
    if max_min:
        goal = f" (เป้าหมาย ≤ {max_min:g} นาที " + ("✅)" if total <= max_min * 60 + 0.5 else "⚠️ ยังยาวกว่าเป้าหมาย)")
    L += ["", f"ความยาวรวม **{tc(total)}**{goal}"]
    chk = [c for r in report for c in r["cuts"] if c["check"]]
    L += ["", "## ⚠️ จุดที่ควรเปิดฟังใน CapCut", "", "| เวลาในคลิปใหม่ | เรื่อง |", "|---|---|"]
    L += [f"| {c['tc']} | {c['note']} |" for c in chk] or ["| - | ไม่มี |"]
    L += ["", "## รายการที่ตัดออกทั้งหมด", "", "| เวลาในคลิปใหม่ | เรื่อง |", "|---|---|"]
    L += [f"| {c['tc']} | {c['note']}{' ⚠️' if c['check'] else ''} |" for r in report for c in r["cuts"]]
    blips = sum(r.get("blips", 0) for r in report)
    if blips: L += ["", f"และตัดเสียงอื้ม/หายใจสั้นๆ อีก {blips} จุด"]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


# ---------------------------------------------------------------- qa
def cut_audio(p, stem, keeps):
    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keeps)
    out = p.f(f"qa_{stem}.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", p.f(f"{stem}.wav"), "-af", f"aselect='{expr}',asetpts=N/SR/TB", out])
    m, c = [], 0.0
    for s, e in keeps: m.append((c, s, e)); c += e - s
    return out, m


def cmd_qa(args):
    """Re-transcribe around every content cut (6 s window + 1.5 s edges) and check for repeated words at joins."""
    p = find_work(args)
    if not os.path.exists(p.f("plan.json")): die("run `ncr.py build` first")
    plan = json.load(open(p.f("plan.json"), encoding="utf-8"))
    model = whisper_model(); ed = p.edits()
    norm = lambda s: re.sub(r"[\s\W_]+", "", s.lower())
    by_stem = {}
    for r in plan["report"]: by_stem.setdefault(r["stem"], []).extend(r["keeps"])
    flags = []
    for stem, keeps in by_stem.items():
        ks = sorted(keeps)
        wav, m = cut_audio(p, stem, ks)
        print(f"== {stem}")
        rms = load_rms(p, stem)
        for x in ed.get("edits", {}).get(stem, []):
            if x.get("keep"): continue
            pos = next((cs for cs, s, e in m if s >= x["to"] - 0.6), None)
            if pos is None: continue
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(max(0, pos - 3.5)), "-t", "6", "-i", wav, p.f("spot.wav")])
            print(f"[{x['from']:.1f}] {x.get('note', '')[:50]}\n    >> {' '.join(whisper_text(model, p.f('spot.wav')).split())}", flush=True)
            kb = next((k for k in reversed(ks) if k[0] < x["from"] and k[1] <= x["to"] + 0.05), None)
            ka = next((k for k in ks if k[1] > x["to"] + 0.05 and k[0] >= x["from"] - 0.05), None)
            if kb and x["from"] - kb[1] > 1.5: kb = None
            if ka and ka[0] - x["to"] > 1.5: ka = None
            edge = lambda a, b: snippet(p, model, stem, a, b) if b - a > 0.15 else ""
            tail = edge(max(kb[0], kb[1] - 1.5), kb[1]) if kb else ""
            head = edge(ka[0], min(ka[1], ka[0] + 1.5)) if ka else ""
            print(f"    edge: …{tail} ‖ {head}…", flush=True)
            fm = re.match(r"\s*(ซึ่ง|แล้วก็|และก็)", head)
            if fm: print(f"    ⚠ head opens with '{fm.group(1)}': cut it too if the sentence stands without it", flush=True)
        # duplicate-word check: whisper merges "ทั้ง ‖ ทั้ง" in long windows, so transcribe 0.7 s on each side alone
        for (a0, a1), (b0, b1) in zip(ks, ks[1:]):
            if b0 - a1 < 0.6: continue
            tail = norm(snippet(p, model, stem, max(a0, a1 - 0.7), a1))
            head = norm(snippet(p, model, stem, b0, min(b1, b0 + 0.7)))
            if any(h in tail + head for h in HALLUCINATIONS): continue
            dup = next((k for k in (6, 5, 4, 3, 2) if len(tail) >= k and len(head) >= k and tail[-k:] == head[:k]), 0)
            if dup:
                flags.append(f"  dup? {a1:.2f}‖{b0:.2f}  …{tail[-8:]} ‖ {head[:8]}…  (move from/to to the pause before the repeated word)")
        g = []   # pause stats from RMS (what the listener hears)
        for k, (a, b) in enumerate(ks):
            for s, e in quiet_runs(rms, a, b, 0.1):
                if s > a + 0.01 and e < b - 0.01: g.append(e - s)
            if k + 1 < len(ks):
                t = next((e - s for s, e in quiet_runs(rms, a, b, 0.0) if e >= b - 0.01), 0.0)
                h = next((e - s for s, e in quiet_runs(rms, *ks[k + 1], 0.0) if s <= ks[k + 1][0] + 0.01), 0.0)
                if t + h >= 0.1: g.append(t + h)
        if g:
            g.sort(); n = len(g)
            prof = ed.get("profiles", {}).get(stem) or p.data.get("profile", "tight")
            tgt = "median ≈ 0.10-0.13, p95 ≤ 0.20" if prof == "tight" else "median ≈ 0.15, p95 ≤ 0.37"
            print(f"  pauses ({prof}): n={n} median={g[n // 2]:.2f}s p95={g[int(n * .95)]:.2f}s >0.30s: {sum(x > 0.3 for x in g)}  (target {tgt})")
    print("\nduplicate-word check:" + ("\n" + "\n".join(flags) if flags else " clean"))


# ---------------------------------------------------------------- compare
def cmd_compare(args):
    """Diff the user's own revised CapCut project against our last build - to learn their taste."""
    p = find_work(args)
    plan = json.load(open(p.f("plan.json"), encoding="utf-8"))
    d = load_draft(draft_dir(args.revised))
    items, _ = draft_items(d)

    def norm(iv):
        out = []
        for a, b in sorted(iv):
            if out and a <= out[-1][1] + 0.03: out[-1][1] = max(out[-1][1], b)
            else: out.append([a, b])
        return out

    def sub(A, B):
        res = []
        for a, b in A:
            cur = [[a, b]]
            for c, e in B:
                nxt = []
                for x, y in cur:
                    if e <= x or c >= y: nxt.append([x, y]); continue
                    if c > x: nxt.append([x, c])
                    if e < y: nxt.append([e, y])
                cur = nxt
            res += cur
        return [(x, y) for x, y in res if y - x >= 0.06]
    ours = {}
    for r in plan["report"]: ours.setdefault(r["stem"], []).extend(r["keeps"])
    for stem in ours:
        v1 = norm(ours[stem])
        v2 = norm([[i["src_in"], i["src_out"]] for i in items if i["stem"] == stem])
        if not v2: continue
        W, _ = load_words(p, stem); rms = load_rms(p, stem)
        txt = lambda a, b: b"".join(t for x, t in W if a <= x - LAG < b).decode("utf-8", "replace")
        print(f"===== {stem}: ours {sum(b - a for a, b in v1):.1f}s  user {sum(b - a for a, b in v2):.1f}s")
        for label, diff in (("USER CUT MORE", sub(v1, v2)), ("USER RESTORED", sub(v2, v1))):
            for a, b in diff:
                v = [x for t, x in rms if a <= t < b]
                loud = sum(1 for x in v if x > SPEECH_DB) / max(1, len(v))
                kind = "speech" if loud > .5 else ("mixed" if loud > .15 else "silence")
                print(f"  {label:13s} {a:8.2f}-{b:8.2f} {b - a:5.2f}s {kind:7s} «{txt(a, b)}»")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="ncr.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--project", help="CapCut project name (default: the last one prepared)")
    ap.add_argument("--work", help=argparse.SUPPRESS)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("steps", help="print the step checklist: steps N (N = current step)")
    a.add_argument("current", type=int, nargs="?", default=1)
    a = sp.add_parser("doctor", help="check tools; --install installs what is missing")
    a.add_argument("--install", action="store_true")
    a = sp.add_parser("projects", help="list CapCut projects (newest first) + whether CapCut is open")
    a.add_argument("--limit", type=int, default=15)
    sp.add_parser("capcut", help="is CapCut running? (exit 1 if open)")
    a = sp.add_parser("prepare", help="read a CapCut project, analyse audio, transcribe (slow: ~1x realtime)")
    a.add_argument("draft"); a.add_argument("--max-min", type=float, help="target max length in minutes")
    a.add_argument("--profile", choices=list(PROFILES), default="tight")
    a.add_argument("--model"); a.add_argument("--no-transcribe", action="store_true")
    a.add_argument("--force", action="store_true", help="re-transcribe even if words exist")
    sp.add_parser("estimate", help="predicted length with the current edits.json vs the target")
    a = sp.add_parser("words", help="words with times + pauses: words CLIP 60:75")
    a.add_argument("clip"); a.add_argument("ranges", nargs="+")
    a = sp.add_parser("dip", help="quietest 150 ms inside ranges (cut points)")
    a.add_argument("clip"); a.add_argument("ranges", nargs="+")
    a = sp.add_parser("spot", help="plain transcription of a source range")
    a.add_argument("clip"); a.add_argument("start", type=float); a.add_argument("end", type=float)
    a = sp.add_parser("fillers", help="find phrase-opening ซึ่ง/แล้วก็ that can be cut")
    a.add_argument("clips", nargs="*"); a.add_argument("--words", nargs="+", default=["ซึ่ง", "แล้วก็", "และก็"])
    a.add_argument("--emit", help="write candidate edits JSON"); a.add_argument("--verify", action="store_true")
    a = sp.add_parser("fit", help="find a cut when dip is weak: fit CLIP FROM TO --tail 'ก่อนตัด' --head 'หลังตัด'")
    a.add_argument("clip"); a.add_argument("start", type=float); a.add_argument("end", type=float)
    a.add_argument("--tail"); a.add_argument("--head"); a.add_argument("--drop", nargs="*")
    a.add_argument("--span", type=float, default=0.4); a.add_argument("--n", type=int, default=4)
    a = sp.add_parser("build", help="write a NEW CapCut project '<name> rough cut vN' + report")
    a.add_argument("--version", type=int, default=1); a.add_argument("--name")
    a.add_argument("--overwrite", action="store_true"); a.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    a.add_argument("--no-blips", action="store_true", help="keep short wordless sounds (อื้ม/breath)")
    sp.add_parser("qa", help="re-transcribe around every cut + duplicate-word check + pause stats")
    a = sp.add_parser("compare", help="diff the user's revised CapCut project vs our last build")
    a.add_argument("revised")
    args = ap.parse_args()
    dict(steps=cmd_steps, doctor=cmd_doctor, projects=cmd_projects, capcut=cmd_capcut, prepare=cmd_prepare,
         estimate=cmd_estimate, words=cmd_words, dip=cmd_dip, spot=cmd_spot, fillers=cmd_fillers, fit=cmd_fit,
         build=cmd_build, qa=cmd_qa, compare=cmd_compare)[args.cmd](args)


if __name__ == "__main__":
    main()
