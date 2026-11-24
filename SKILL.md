---
name: noobit-capcut-rough-cut
description: Rough-cut a CapCut project with Thai speech for beginners - installs what is missing (ffmpeg, whisper.cpp, Thai model), asks the target length and the CapCut project name, removes pauses, stumbles, false starts, repeated takes, filler words (ซึ่ง/แล้วก็/อ่า/อื้ม) and, if needed, whole off-topic blocks to fit the length, then writes a NEW CapCut project "<name> rough cut v1" next to the original. Use whenever the user wants to ตัด rough cut / ตัดคำผิด / ตัดคำพูดผิด / ตัดช่วงเงียบ / ตัด take ซ้ำ / ตัดคลิปใน CapCut / ตัดต่อ project CapCut, or names a CapCut project to cut, even if they do not say "rough cut".
---

# noobit-capcut-rough-cut

Turns a raw CapCut project (one recording on the main video track) into a tight rough cut, the way the
Thai channel "บริหารงานแบบคนไอที / noobitguy" cuts its clips. Nothing is rendered: the skill writes a **new**
CapCut project the user opens and finishes. The original project is never modified.

- Tool: `scripts/ncr.py` (python3 stdlib only). Run `python3 <skill-dir>/scripts/ncr.py -h`.
- Cutting rules (read before step 5): `references/cutting-rules.md`
- **Talk to the user in Thai**, in plain words: the user is a beginner. Explain what is happening and how long it takes.
- macOS only (CapCut for Windows encrypts its project files).

Below, `NCR` means `python3 <skill-dir>/scripts/ncr.py` with the real absolute path. In zsh, a variable holding a
command with spaces does not split, so define a function instead: `ncr(){ python3 "/abs/path/scripts/ncr.py" "$@"; }`.

## Progress checklist (show it at every step)

There are 8 steps. **At the start of every step run `NCR steps N` and paste its output into your message** so the
user always sees where the work is (command output is not shown to the user by itself). If your agent has a
task/plan/todo tool, mirror the same 8 steps there too.

```
1. เช็กและติดตั้งโปรแกรมที่ต้องใช้
2. ถามความยาวคลิปที่ต้องการ
3. เลือก Project ใน CapCut และปิด CapCut
4. วิเคราะห์เสียงและถอดเสียงภาษาไทย
5. อ่านบทพูดและเลือกจุดตัด
6. สร้าง Project ใหม่ใน CapCut
7. ตรวจรอยต่อทุกจุด
8. ส่งมอบงานและสรุปผล
```

## Step 1 - Check and install the tools

```
NCR doctor --install
```
Checks macOS, Python, Homebrew, ffmpeg/ffprobe, whisper-cli and the Thai speech model (`ggml-large-v3.bin`, 3.1 GB in
`~/models/`), and the CapCut projects folder. With `--install` it runs `brew install ffmpeg whisper-cpp` for what is
missing and downloads the model (resumable).

- The model download is long (3.1 GB, ~5-30 min): run the command **in the background** and tell the user. If it
  fails or the network drops, run it again - it continues where it stopped.
- **Exit code 2 = Homebrew is missing.** Homebrew needs the user's Mac password, so you cannot install it. Show the
  user the one-line installer the command prints, ask them to paste it into the **Terminal** app and press Enter,
  type their Mac password when asked (nothing appears while typing - that is normal), and tell you when it is done.
  Then run `doctor --install` again.
- Exit code 3 = not macOS: stop and explain.
- No CapCut projects folder: ask the user to install CapCut and create one project first.
- Do not continue until the last line says `พร้อมใช้งานครบแล้ว ✅`.

## Step 2 - Ask the target length

Ask (with your question tool if you have one, otherwise in plain text):

- **คลิปที่ตัดเสร็จ อยากให้ยาวไม่เกินกี่นาที?** Offer e.g. 1, 3, 5 นาที and "ไม่จำกัด (ตัดแค่คำผิดกับช่วงเงียบ)".
- **จังหวะการตัด** (optional second question, default first): `tight` = กระชับ (แนะนำ: คลิปสั้น, อัดหน้าจอสอน) /
  `relaxed` = เว้นจังหวะหายใจมากขึ้น (คลิปพูดหน้ากล้องสบายๆ).

## Step 3 - Pick the CapCut project, and close CapCut

```
NCR projects
```
Lists projects (newest first) with their length, and says whether CapCut is open. Ask which project to cut
(offer the top few names as options). Names ending in "rough cut vN" are this skill's own outputs.

Then **alert the user**: "ก่อนสร้าง project ใหม่ ต้องปิดโปรแกรม CapCut ก่อนนะครับ (กด Cmd+Q) เพราะตอนปิด CapCut จะเขียน
รายการ project ทับ ทำให้ project ใหม่หายไป ระหว่างนี้ไม่ต้องเปิด CapCut จนกว่าผมจะบอกครับ"
**Never quit or kill CapCut yourself.** `NCR capcut` checks (exit 1 = still open). Analysis in step 4 only reads,
so it may start while CapCut is still open; only step 6 needs it closed.

If the user has not made a project yet, explain: open CapCut → New project → import the recording → drag it onto
the timeline (one clip on the main track is the normal case) → quit CapCut.

## Step 4 - Analyse and transcribe (slow: about 1x the clip length)

```
NCR prepare "<project name>" --max-min <N> --profile tight     # omit --max-min for "no limit"
```
Run it **in the background**; tell the user roughly how long (≈ the raw clip length, plus ~30 s to load the model).
Work files go to `~/Movies/noobit-rough-cut/<project>/.ncr/`:
`<clip>.transcript.txt` (sentences with source times + long pauses) and `edits.json`.
`prepare` also prints the length if only pauses were removed - compare it with the target.
It warns if the project already has text/music/effects on other tracks (they keep their old times, so a rough
cut should come first); pass that warning on to the user.

## Step 5 - Read the transcript and choose the cuts

Read `references/cutting-rules.md` first, then the whole transcript. Write `edits.json` (source seconds):

1. **Speech cuts** (rules §3): retakes (keep the LAST complete take), false starts, micro-repeats, อ่า/เอ่อ,
   repeated ordinals. Find exact times with `NCR words CLIP a:b`, `NCR dip CLIP a:b` (cut only at a `dip`),
   `NCR spot CLIP a b` (re-listen a short range), and `NCR fit …` when there is no clean dip.
2. **Phrase-opening ซึ่ง/แล้วก็** (rules §3.5): `NCR fillers --verify --emit <work>/fillers.json`, read every ctx
   line, keep only the ones that are safe, merge them into `edits.json`.
3. **Fit the length** (rules §4): `NCR estimate` prints the predicted length (pauses, blips and your edits) against
   the target. If it is over, cut whole off-topic blocks in the order of rules §4 and re-run `estimate` until it fits.
   Never drop a main step of the story; if it cannot fit, tell the user the shortest sensible length and ask.
4. Put `"check": 1` on any cut you are not sure about. Pauses and short อื้ม/breath sounds are removed automatically.

## Step 6 - Build the new CapCut project

```
NCR capcut          # must say CapCut is closed; if not, ask the user to quit it and wait for their word
NCR build           # -> new project "<name> rough cut v1" + report
```
`build` copies the original project to a NEW folder, cuts the main video track, registers the project in CapCut's
list (backup: `root_meta_info.json.ncr-backup`) and writes `<name>_rough_cut_v1_report.md` in the work folder.
It refuses to run while CapCut is open. Use `--version 2` for a new copy, or `--overwrite` to replace v1.

## Step 7 - QA every join

```
NCR qa
```
Read every `edge: …tail ‖ head…` line, the `⚠` lines, the duplicate-word check and the pause stats
(rules §7). Fix `edits.json`, then `NCR build --overwrite` and `NCR qa` again until it is clean.
Make sure CapCut is still closed before each rebuild.

## Step 8 - Hand over (in Thai)

- Tell the user they can open CapCut now → the new project **"<name> rough cut v1"** is on the home screen
  (the original is untouched).
- Length before → after (and vs the target), what kinds of things were cut, which content blocks were cut to fit
  the length (they can put them back in CapCut), and the `check` points worth listening to (timestamps are in the
  new clip; the report lists them all). Give the report path.
- Suggest next steps in CapCut: listen through once, then add captions, music and effects on top.
- Optional: after the user edits the new project themselves, `NCR compare "<their project name>"` shows what they
  cut more or restored. Use it to adjust your choices next time.

## Limits

- macOS + CapCut desktop with plain-JSON projects (`draft_info.json` / `draft_content.json`).
- Only the main video track is cut; clips with speed changes are passed through uncut.
- Thai transcription only (whisper `--language th`).
- Do the rough cut before adding text, music or effects: items on other tracks keep their original times.
