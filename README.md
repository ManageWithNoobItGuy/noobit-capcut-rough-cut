# noobit-capcut-rough-cut 🎬✂️

**Skill ให้ AI ตัด Rough Cut คลิปภาษาไทยใน CapCut ให้อัตโนมัติ สำหรับมือใหม่**
ตัดช่วงเงียบ ตัดคำพูดผิด ตัดพูดซ้ำ ตัดคำติดปาก แล้วสร้าง **Project ใหม่ใน CapCut** ให้เปิดตัดต่อต่อได้ทันที (project เดิมไม่ถูกแตะ)

ทำโดยช่อง **[บริหารงานแบบคนไอที (noobitguy)](https://www.youtube.com/@noobitguy)** ใช้วิธีตัดแบบเดียวกับที่ผมใช้ตัดคลิปจริงในช่อง

> *English summary: an AI-agent skill (Claude Code, Codex, Antigravity) that rough-cuts Thai speech in a CapCut desktop project on macOS. It installs its own dependencies (ffmpeg, whisper.cpp, the large-v3 model), transcribes locally, removes pauses, stumbles, false starts, repeated takes and filler words, trims whole off-topic blocks when the clip must fit a target length, and writes a new CapCut project next to the original. Nothing is rendered.*

---

## ✨ ทำอะไรได้บ้าง

- **ตัดช่วงเงียบ** ให้คลิปกระชับแบบคลิปสั้นสายสอน (เลือกได้ว่าจะกระชับมาก หรือเว้นจังหวะหายใจ)
- **ตัดพูดผิดแล้วพูดใหม่** เก็บเฉพาะรอบสุดท้ายที่พูดจบสมบูรณ์
- **ตัดพูดค้าง คำซ้ำ** เช่น "วิธีสร้าง… วิธีการสร้าง", "แต่พอผม แต่ผมคิดว่า"
- **ตัดเสียงอึกอัก** เอ่อ อืม อ่า อื้ม เสียงหายใจ
- **ตัดคำติดปาก** "ซึ่ง" / "แล้วก็" ที่ขึ้นต้นประโยค (ถ้าตัดแล้วประโยคยังรู้เรื่อง)
- **คุมความยาว** บอกได้ว่าอยากได้คลิปไม่เกินกี่นาที ถ้ายังเกิน AI จะตัดส่วนที่ไม่จำเป็นทั้งก้อน เช่น ช่วงรอโหลด หรือพูดซ้ำความเดิม
- **ไม่ Render** สร้างเป็น project CapCut ใหม่ ทุกจุดตัดยังแก้กลับได้ใน CapCut
- **ตรวจรอยต่อทุกจุด** ด้วยการถอดเสียงซ้ำ แล้วสรุปเป็นรายงานว่าตัดอะไรไปบ้าง ตรงไหนควรเปิดฟัง
- **ติดตั้งโปรแกรมที่ต้องใช้ให้เอง** (ffmpeg, Whisper) ถอดเสียงไทย **ในเครื่องของเราเอง** ไม่เสียค่า API

## 📋 ขั้นตอนที่ AI จะพาทำ (มีเช็กลิสต์บอกตลอดว่าถึงขั้นไหนแล้ว)

```
✅ 1. เช็กและติดตั้งโปรแกรมที่ต้องใช้
✅ 2. ถามความยาวคลิปที่ต้องการ
▶️ 3. เลือก Project ใน CapCut และปิด CapCut
⬜ 4. วิเคราะห์เสียงและถอดเสียงภาษาไทย
⬜ 5. อ่านบทพูดและเลือกจุดตัด
⬜ 6. สร้าง Project ใหม่ใน CapCut
⬜ 7. ตรวจรอยต่อทุกจุด
⬜ 8. ส่งมอบงานและสรุปผล
```

## 💻 สิ่งที่ต้องมี

| | |
|---|---|
| เครื่อง | **Mac** (macOS) พื้นที่ว่างอย่างน้อย ~5 GB |
| CapCut | เวอร์ชัน Desktop สำหรับ Mac |
| AI Agent | [Claude Code](https://claude.com/claude-code) (แนะนำ) หรือ Codex / Antigravity |
| อื่นๆ | ffmpeg, whisper.cpp และโมเดลเสียงภาษาไทย → **skill ติดตั้งให้เอง** |

⚠️ ยังไม่รองรับ Windows เพราะ CapCut บน Windows เข้ารหัสไฟล์ project ไว้ อ่านไม่ได้

---

## 🚀 Step 1: ติดตั้ง Skill

**วิธีที่ 1: ให้ AI ติดตั้งให้ (ง่ายที่สุด)**

เปิด Claude Code แล้วพิมพ์:

```
ช่วยติดตั้ง skill จาก https://github.com/ManageWithNoobItGuy/noobit-capcut-rough-cut ให้หน่อย
```

**วิธีที่ 2: ติดตั้งเองผ่าน Terminal**

```bash
git clone https://github.com/ManageWithNoobItGuy/noobit-capcut-rough-cut.git
```

```bash
cd noobit-capcut-rough-cut && ./install.sh
```

- `./install.sh` คัดลอก skill ไปที่ `~/.claude/skills/noobit-capcut-rough-cut` แล้วเช็กว่าโปรแกรมครบไหม
- `./install.sh --all` ติดตั้งให้ Codex และ Antigravity ด้วย
- `./install.sh --deps` ติดตั้ง ffmpeg, whisper.cpp และโหลดโมเดลภาษาไทย (3 GB) ไว้ก่อนเลย
  (ถ้าไม่ใส่ AI จะติดตั้งให้ตอนใช้งานครั้งแรก)

> 💡 ถ้าเครื่องยังไม่มี **Homebrew** (ตัวช่วยลงโปรแกรมบน Mac) AI จะให้คำสั่ง 1 บรรทัดมาวางใน Terminal
> เพราะต้องใส่รหัสผ่านเครื่อง ตอนพิมพ์รหัสจะไม่มีตัวอักษรขึ้น เป็นเรื่องปกติครับ

## 🎞️ Step 2: เตรียม Project ใน CapCut

1. เปิด CapCut → **New project** (สร้างโปรเจกต์ใหม่)
2. Import คลิปที่อัดมา แล้ว **ลากลง Timeline** (คลิปเดียวบน track หลักคือแบบปกติ)
3. ยังไม่ต้องใส่ข้อความ เพลง หรือเอฟเฟกต์ (ให้ตัด rough cut ก่อน)
4. จำชื่อ project ไว้ (ชื่อที่เห็นในหน้าแรกของ CapCut เช่น `1122`)
5. **ปิด CapCut** (Cmd+Q) ก่อนให้ AI สร้าง project ใหม่

## ✂️ Step 3: สั่งตัด

พิมพ์ใน Claude Code:

```
/noobit-capcut-rough-cut ฝากตัด rough cut คลิปใน CapCut ให้หน่อย
```

หรือพิมพ์ธรรมดาก็ได้ เช่น *"ช่วยตัดคำผิดใน project CapCut ชื่อ 1122 ให้หน่อย ไม่เกิน 3 นาที"*

AI จะถาม 2 เรื่อง:
1. **อยากให้คลิปยาวไม่เกินกี่นาที** (หรือไม่จำกัด ตัดแค่คำผิดกับช่วงเงียบ)
2. **ชื่อ project ใน CapCut** ที่จะตัด (AI จะลิสต์ชื่อให้เลือก) แล้วเตือนให้ปิด CapCut

จากนั้นรอได้เลย การถอดเสียงใช้เวลาประมาณเท่าความยาวคลิป (คลิป 5 นาที ≈ 5 นาที)
ครั้งแรกต้องโหลดโมเดลภาษาไทย 3 GB ด้วย อาจใช้เวลาเพิ่ม 5–30 นาทีตามความเร็วเน็ต

## 📥 Step 4: เปิดดูผลใน CapCut

1. เปิด CapCut → จะเห็น project ใหม่ชื่อ **`<ชื่อเดิม> rough cut v1`** (project เดิมยังอยู่ครบ)
2. เปิดฟังตรงจุดที่รายงานบอกว่า ⚠️ ควรเช็ก
3. ไม่ชอบตรงไหน แก้เองใน CapCut ได้เลย หรือบอก AI ให้แก้ แล้วตัดเป็น v2
4. ใส่ข้อความ เพลง เอฟเฟกต์ต่อได้ตามสบาย

รายงานสรุปอยู่ที่ `~/Movies/noobit-rough-cut/<ชื่อ project>/<ชื่อ>_rough_cut_v1_report.md`
บอกความยาวก่อน/หลังตัด, ทุกจุดที่ตัด และเวลาในคลิปใหม่ที่ควรเปิดฟัง

---

## 🤖 สำหรับ AI Agent (Installation instructions for AI agents)

If a user asks you to install this skill, do exactly this (macOS):

```bash
git clone --depth 1 https://github.com/ManageWithNoobItGuy/noobit-capcut-rough-cut.git /tmp/noobit-capcut-rough-cut
```

```bash
sh /tmp/noobit-capcut-rough-cut/install.sh
```

- Codex / Antigravity users: run `install.sh --all` instead (copies to `~/.codex/skills` and `~/.gemini/antigravity/skills` too).
- Other agents: copy `SKILL.md`, `scripts/` and `references/` into your agent's skills folder as `noobit-capcut-rough-cut/`.
- The skill entry point is `SKILL.md`. It drives an 8-step workflow with `python3 scripts/ncr.py` (stdlib only).
- Dependencies are installed on first use by `python3 scripts/ncr.py doctor --install`
  (Homebrew `ffmpeg` + `whisper-cpp`, and `ggml-large-v3.bin` 3.1 GB into `~/models/`).
  If Homebrew itself is missing, the command exits with code 2 and prints the official installer line:
  the user must run that in Terminal (it needs their password). Do not try to run it for them.
- Never quit CapCut on the user's behalf: ask them to quit it before `build`.
- After installing, tell the user (in Thai) how to start: `/noobit-capcut-rough-cut ฝากตัด rough cut คลิปใน CapCut ให้หน่อย`

---

## 🧰 เบื้องหลังการทำงาน

| เครื่องมือ | หน้าที่ |
|---|---|
| **AI Agent** | คุยกับเรา อ่านบทพูด แล้วตัดสินใจว่าตัดตรงไหน |
| **FFmpeg** | แยกเสียง วัดระดับเสียง หาช่วงเงียบ |
| **Whisper (large-v3)** | ถอดเสียงภาษาไทยพร้อมเวลาของแต่ละคำ ทำงานในเครื่องเรา |
| **`scripts/ncr.py`** | อ่าน/เขียน project CapCut, หาจุดตัดที่เงียบที่สุด, ตรวจรอยต่อ, ทำรายงาน |

<details>
<summary>คำสั่งของ <code>ncr.py</code> (ปกติ AI เป็นคนเรียกให้เอง)</summary>

```bash
python3 scripts/ncr.py steps 3                     # แสดงเช็กลิสต์ 8 ขั้น (ขั้นที่ 3 กำลังทำ)
python3 scripts/ncr.py doctor --install            # เช็ก + ติดตั้ง ffmpeg, whisper.cpp, โมเดล
python3 scripts/ncr.py projects                    # ลิสต์ project ใน CapCut + CapCut เปิดอยู่ไหม
python3 scripts/ncr.py capcut                      # เช็กว่าปิด CapCut แล้วหรือยัง
python3 scripts/ncr.py prepare "1122" --max-min 3  # แยกเสียง หาช่วงเงียบ ถอดเสียง
python3 scripts/ncr.py words CLIP 60:75            # คำพร้อมเวลา + ช่วงเงียบ
python3 scripts/ncr.py dip CLIP 147.8:148.9        # จุดที่เงียบที่สุดสำหรับตัด
python3 scripts/ncr.py spot CLIP 30 34             # ถอดเสียงช่วงสั้นซ้ำ (หาคำซ้ำ)
python3 scripts/ncr.py fit CLIP 10.2 11.0 --tail "นะครับ" --head "วิธีการ"
python3 scripts/ncr.py fillers --verify --emit f.json   # หา "ซึ่ง/แล้วก็" ต้นวลีที่ตัดได้
python3 scripts/ncr.py estimate                    # ความยาวที่จะได้ เทียบกับเป้าหมาย
python3 scripts/ncr.py build                       # สร้าง project ใหม่ "<ชื่อ> rough cut v1"
python3 scripts/ncr.py qa                          # ถอดเสียงตรวจรอยต่อทุกจุด
python3 scripts/ncr.py compare "1122 rough cut v1" # เทียบกับที่เราแก้เองใน CapCut
```

ไฟล์ทำงานอยู่ที่ `~/Movies/noobit-rough-cut/<ชื่อ project>/.ncr/`
ตัวแปรที่ปรับได้: `NCR_DRAFTS` (โฟลเดอร์ project CapCut), `NCR_HOME`, `NCR_WHISPER_MODEL`, `NCR_WHISPER_BIN`
</details>

## 🎛️ ปรับให้เป็นสไตล์ของคุณ

- **`references/cutting-rules.md`** กฎการตัดทั้งหมด เช่น คำไหนตัด คำไหนเก็บ ตัดเนื้อหาอะไรก่อนเมื่อคลิปยาวเกิน
- **`PROFILES` ใน `scripts/ncr.py`** ความยาวช่วงเงียบที่ตัด และช่องว่างที่เหลือตรงรอยต่อ (`tight` / `relaxed`)
- หรือบอก AI ตรงๆ เช่น *"ครั้งหน้าเว้นจังหวะให้มากกว่านี้หน่อย"* แล้วให้แก้ skill ให้

## ⚠️ ข้อจำกัด

- **macOS เท่านั้น** และ CapCut ที่เก็บ project เป็นไฟล์ JSON ปกติ
- ตัดเฉพาะคลิปบน **track หลัก** ของ Timeline ของบน track อื่น (ข้อความ เพลง) จะอยู่ตำแหน่งเดิม จึงควรตัดก่อนใส่ของพวกนี้
- คลิปที่ปรับความเร็ว (speed) จะไม่ถูกตัด
- ถอดเสียง **ภาษาไทย** เท่านั้น
- AI ยังพลาดได้บ้าง เช่น เหลือเศษคำที่รอยต่อ ให้เปิดฟังตรงจุด ⚠️ ในรายงานก่อน Export ทุกครั้ง

## 🙌 ติดตามช่อง

ถ้า skill นี้มีประโยชน์ ฝากกด ⭐ ให้ repo และติดตามช่องได้ที่

- YouTube: https://www.youtube.com/@noobitguy
- Website: https://noobitguy.one
- Facebook: https://www.facebook.com/ManageWithNoobITguy
- TikTok: https://www.tiktok.com/@noobitguy

ติดปัญหาหรือมีไอเดีย เปิด [Issue](https://github.com/ManageWithNoobItGuy/noobit-capcut-rough-cut/issues) ได้เลยครับ

เครื่องมืออื่นในชุดเดียวกัน: [noobit-vdo-editor](https://github.com/ManageWithNoobItGuy/noobit-vdo-editor) (ตัด Rough Cut ใน DaVinci Resolve)
