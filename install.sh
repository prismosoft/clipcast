#!/bin/bash
set -e

# ClipCast Installer
# Sets up Python venv, installs dependencies, and creates global CLI commands.
# Usage: ./install.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🎬 ClipCast Installer"
echo "======================"
echo "   Directory: $SCRIPT_DIR"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v python3.12 &>/dev/null && ! command -v python3 &>/dev/null; then
    echo "❌ Python 3.10+ not found. Install Python first: https://python.org"
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "❌ FFmpeg not found. Install it first:"
    echo "   macOS:  brew install ffmpeg"
    echo "   Ubuntu: sudo apt install ffmpeg"
    echo "   Windows: https://ffmpeg.org/download.html"
    exit 1
fi

if ! command -v git &>/dev/null; then
    echo "❌ Git not found. Install git first."
    exit 1
fi

echo "   ✅ Python found"
echo "   ✅ FFmpeg found"
echo "   ✅ Git found"
echo ""

# Set up Python venv
if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "📦 Virtual environment already exists, skipping creation."
else
    echo "📦 Creating Python virtual environment..."

    # Try uv first (faster), fall back to python -m venv
    if command -v uv &>/dev/null; then
        echo "   Using uv (fast)..."
        uv venv --python 3.12 "$SCRIPT_DIR/.venv" 2>/dev/null || uv venv "$SCRIPT_DIR/.venv"
    else
        echo "   Using python -m venv..."
        python3 -m venv "$SCRIPT_DIR/.venv"
    fi
fi

# Install dependencies
echo ""
echo "📦 Installing Python dependencies..."
if command -v uv &>/dev/null; then
    uv pip install --python "$SCRIPT_DIR/.venv/bin/python" -r "$SCRIPT_DIR/requirements.txt"
else
    "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi

echo "   ✅ Dependencies installed"
echo ""

# Set up .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "📝 .env already exists, skipping."
else
    echo "📝 Creating .env from template..."
    cp "$SCRIPT_DIR/.env.sample" "$SCRIPT_DIR/.env"
    echo "   ⚠️  Edit $SCRIPT_DIR/.env and add your GOOGLE_API_KEY"
    echo "       Get one at: https://aistudio.google.com/apikey"
fi
echo ""

# Create global CLI commands
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

# clipcast (clipping command)
cat > "$BIN_DIR/clipcast" << EOF
#!/bin/bash
# clipcast — AI Auto-Clipper (long video → short clips)
# Usage: clipcast --url "https://youtube.com/watch?v=..." --clips 5
#        clipcast --help
CLIPCAST_DIR="$SCRIPT_DIR"
exec "\$CLIPCAST_DIR/.venv/bin/python" "\$CLIPCAST_DIR/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/clipcast"

# clipcast-audio (audio2video command)
cat > "$BIN_DIR/clipcast-audio" << EOF
#!/bin/bash
# clipcast-audio — Audio to B-roll video with subtitles
# Usage: clipcast-audio --audio "song.mp3" --ratio 9:16
#        clipcast-audio --help
CLIPCAST_DIR="$SCRIPT_DIR"
cd "\$CLIPCAST_DIR" && exec "\$CLIPCAST_DIR/.venv/bin/python" "\$CLIPCAST_DIR/audio2video.py" "\$@"
EOF
chmod +x "$BIN_DIR/clipcast-audio"

echo "🔧 Global commands installed:"
echo "   clipcast       → $BIN_DIR/clipcast"
echo "   clipcast-audio  → $BIN_DIR/clipcast-audio"
echo ""

# Verify PATH
if echo "$PATH" | tr ':' '\n' | grep -q "$BIN_DIR"; then
    echo "   ✅ $BIN_DIR is in PATH"
else
    echo "   ⚠️  $BIN_DIR is NOT in PATH. Add this to your shell profile:"
    echo "       export PATH=\"$BIN_DIR:\$PATH\""
fi
echo ""

# Verify commands work
echo "🧪 Verifying installation..."
if "$BIN_DIR/clipcast" --help &>/dev/null; then
    echo "   ✅ clipcast works"
else
    echo "   ⚠️  clipcast --help failed — check the venv setup"
fi

if "$BIN_DIR/clipcast-audio" --help &>/dev/null; then
    echo "   ✅ clipcast-audio works"
else
    echo "   ⚠️  clipcast-audio --help failed — check the venv setup"
fi
echo ""

echo "=============================="
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "   1. Edit $SCRIPT_DIR/.env and add your GOOGLE_API_KEY"
echo "      Get one at: https://aistudio.google.com/apikey"
echo ""
echo "   2. (Optional) Add PEXELS_API_KEY for B-roll footage"
echo "      Get one at: https://www.pexels.com/api/"
echo ""
echo "   3. Try it:"
echo "      clipcast --help"
echo "      clipcast-audio --help"
echo ""
echo "   4. Clip a video:"
echo "      clipcast --url \"https://youtube.com/watch?v=VIDEO_ID\" --clips 5 --whisper-device cpu --whisper-compute-type int8"
echo ""
echo "   5. Audio to video:"
echo "      clipcast-audio --audio \"song.mp3\" --ratio 9:16"
echo ""