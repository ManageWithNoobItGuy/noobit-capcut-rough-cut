#!/bin/sh
# Install the noobit-capcut-rough-cut skill.
# Usage:  ./install.sh           -> ~/.claude/skills/noobit-capcut-rough-cut (Claude Code)
#         ./install.sh --all     -> also Codex (~/.codex/skills) and Antigravity (~/.gemini/antigravity/skills)
#         ./install.sh --deps    -> also install ffmpeg + whisper.cpp + the Thai model (3 GB) right away
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
NAME="noobit-capcut-rough-cut"
DESTS="$HOME/.claude/skills"
DEPS=0
for a in "$@"; do
  case "$a" in
    --all)  DESTS="$DESTS $HOME/.codex/skills $HOME/.gemini/antigravity/skills" ;;
    --deps) DEPS=1 ;;
  esac
done
for DEST in $DESTS; do
  [ "$SRC" = "$DEST/$NAME" ] && continue
  mkdir -p "$DEST/$NAME"
  rm -rf "$DEST/$NAME/scripts" "$DEST/$NAME/references"
  cp "$SRC/SKILL.md" "$DEST/$NAME/"
  cp -R "$SRC/scripts" "$SRC/references" "$DEST/$NAME/"
  rm -rf "$DEST/$NAME/scripts/__pycache__"
  echo "installed -> $DEST/$NAME"
done
echo
if [ "$DEPS" = 1 ]; then
  python3 "$SRC/scripts/ncr.py" doctor --install
else
  python3 "$SRC/scripts/ncr.py" doctor || echo "(ไม่เป็นไรครับ ตอนใช้งานครั้งแรก AI จะติดตั้งตัวที่ขาดให้เอง หรือสั่ง ./install.sh --deps)"
fi
