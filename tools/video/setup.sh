#!/bin/sh
# One-time setup per cloud session for the watch skill (.claude/skills/watch) and tools/video/speech.py.
# Installs yt-dlp, Deno (YouTube player JS) and sherpa-onnx (offline Whisper) into a private venv,
# then writes the watch config so its first-run wizard is skipped. Safe to run again.
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CACHE="${MEMEBOT_VIDEO_CACHE:-$HOME/.cache/memebot-video}"
VENV="$CACHE/venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q --disable-pip-version-check -U "yt-dlp[default,curl-cffi]" deno numpy "sherpa-onnx==2.0.1"

PATH="$VENV/bin:$PATH"
export PATH
for tool in ffmpeg ffprobe yt-dlp deno; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool" >&2; exit 2; }
done

# auto = Gemini when GEMINI_API_KEY is set in the environment, otherwise local frames.
# Speech fallback none: the WhisperX/Groq/OpenAI hosts are blocked here; use tools/video/speech.py instead.
python3 "$REPO/.claude/skills/watch/scripts/setup.py" --engine auto --backend none --detail balanced

echo "yt-dlp $(yt-dlp --version), $(deno --version | head -1)"
if [ -n "${GEMINI_API_KEY:-}" ]; then echo "Gemini key: present (YouTube links work)"; else echo "Gemini key: absent (local engine only)"; fi
echo "Next: PATH=\"$VENV/bin:\$PATH\" python3 $REPO/.claude/skills/watch/scripts/watch.py <file-or-url> --question \"...\""
echo "Speech: $VENV/bin/python $REPO/tools/video/speech.py <file> --language de"
