#!/bin/bash
set -e

# ClipCast Interactive Installer
# Sets up Python venv, installs dependencies, creates global CLI commands,
# optionally installs agent skills, and configures API keys.
# Usage: ./install.sh         (interactive)
#        ./install.sh --yes   (non-interactive, everything default)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NONINTERACTIVE=false

if [ "$1" = "--yes" ] || [ "$1" = "-y" ]; then
    NONINTERACTIVE=true
fi

# --- Helpers ---

prompt_yesno() {
    local prompt="$1"
    local default_yes="${2:-true}"
    if $NONINTERACTIVE; then
        echo "$prompt → yes (non-interactive)"
        return 0
    fi
    local hint
    if $default_yes; then
        hint="Y/n"
    else
        hint="y/N"
    fi
    printf "%s [%s] " "$prompt" "$hint"
    read -r answer
    case "$answer" in
        [yY]*) return 0 ;;
        [nN]*) return 1 ;;
        "")    $default_yes && return 0 || return 1 ;;
        *)    $default_yes && return 0 || return 1 ;;
    esac
}

prompt_input() {
    local prompt="$1"
    local varname="$2"
    if $NONINTERACTIVE; then
        echo "$prompt → (skipped, non-interactive)"
        eval "$varname=''"
        return
    fi
    printf "%s " "$prompt"
    read -r answer
    eval "$varname='$answer'"
}

# --- Banner ---

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║                                              ║"
echo "  ║          🎬  ClipCast Installer             ║"
echo "  ║     AI Auto-Clipper & Audio-to-Video        ║"
echo "  ║                                              ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
echo "  This installer will:"
echo "    1. Check prerequisites (Python, FFmpeg, Git)"
echo "    2. Create a Python virtual environment"
echo "    3. Install Python dependencies"
echo "    4. Set up .env with your API keys"
echo "    5. Install global CLI commands (clipcast, clipcast-audio)"
echo "    6. Optionally install agent skills (npx skills)"
echo ""
if ! $NONINTERACTIVE; then
    if prompt_yesno "Continue with installation?" true; then
        echo ""
    else
        echo "Installation cancelled."
        exit 0
    fi
fi

# --- Step 1: Prerequisites ---

echo "━━━ Step 1/6: Checking prerequisites ━━━"

PASS=true

if command -v python3.12 &>/dev/null; then
    PYVER=$(python3.12 --version)
    echo "   ✅ Python: $PYVER"
elif command -v python3 &>/dev/null; then
    PYVER=$(python3 --version)
    PYMAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
    PYMINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
    if [ "$PYMAJOR" -ge 3 ] && [ "$PYMINOR" -ge 10 ]; then
        echo "   ✅ Python: $PYVER"
    else
        echo "   ❌ Python 3.10+ required, found $PYVER"
        PASS=false
    fi
else
    echo "   ❌ Python not found. Install: https://python.org"
    PASS=false
fi

if command -v ffmpeg &>/dev/null; then
    echo "   ✅ FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "   ❌ FFmpeg not found."
    echo "      macOS:  brew install ffmpeg"
    echo "      Ubuntu: sudo apt install ffmpeg"
    PASS=false
fi

if command -v git &>/dev/null; then
    echo "   ✅ Git: $(git --version)"
else
    echo "   ❌ Git not found."
    PASS=false
fi

if [ "$PASS" = false ]; then
    echo ""
    echo "❌ Prerequisites not met. Fix the issues above and re-run."
    exit 1
fi

echo ""

# --- Step 2: Python venv ---

echo "━━━ Step 2/6: Python virtual environment ━━━"

if [ -d "$SCRIPT_DIR/.venv" ]; then
    if prompt_yesno "   .venv already exists. Recreate it?" false; then
        rm -rf "$SCRIPT_DIR/.venv"
        echo "   Recreating..."
    else
        echo "   Keeping existing .venv"
        SKIP_VENV_CREATE=true
    fi
fi

if [ "${SKIP_VENV_CREATE:-false}" != "true" ]; then
    if command -v uv &>/dev/null; then
        echo "   Using uv (fast)..."
        uv venv --python 3.12 "$SCRIPT_DIR/.venv" 2>/dev/null || uv venv "$SCRIPT_DIR/.venv"
    else
        echo "   Using python -m venv..."
        python3 -m venv "$SCRIPT_DIR/.venv"
    fi
    echo "   ✅ Virtual environment created"
fi
echo ""

# --- Step 3: Install dependencies ---

echo "━━━ Step 3/6: Installing Python dependencies ━━━"

if command -v uv &>/dev/null; then
    echo "   Installing with uv..."
    uv pip install --python "$SCRIPT_DIR/.venv/bin/python" -r "$SCRIPT_DIR/requirements.txt"
else
    echo "   Installing with pip..."
    "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip
    "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi
echo "   ✅ Dependencies installed"
echo ""

# --- Step 4: .env setup ---

echo "━━━ Step 4/6: API key configuration ━━━"

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.sample" "$SCRIPT_DIR/.env"
    echo "   📝 Created .env from template"
else
    echo "   📝 .env already exists"
fi

# Offer to set API keys interactively
if ! $NONINTERACTIVE; then
    echo ""
    echo "   You can set your API keys now (or edit .env later)."
    echo ""

    current_key=$(grep "^GOOGLE_API_KEY=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d'=' -f2-)
    if [ -z "$current_key" ] || [ "$current_key" = "your-gemini-api-key-here" ]; then
        if prompt_yesno "   Set GOOGLE_API_KEY now? (required for both commands)" true; then
            prompt_input "   Paste your Gemini API key:" GEMINI_KEY
            if [ -n "$GEMINI_KEY" ]; then
                sed -i.bak "s|GOOGLE_API_KEY=.*|GOOGLE_API_KEY=$GEMINI_KEY|" "$SCRIPT_DIR/.env"
                rm -f "$SCRIPT_DIR/.env.bak"
                echo "   ✅ GOOGLE_API_KEY saved to .env"
            else
                echo "   ⚠️  No key entered. Edit .env manually later."
            fi
        fi
    else
        echo "   ✅ GOOGLE_API_KEY already set"
    fi

    current_pexels=$(grep "^PEXELS_API_KEY=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d'=' -f2-)
    if [ -z "$current_pexels" ] || [ "$current_pexels" = "your-pexels-api-key-here" ]; then
        if prompt_yesno "   Set PEXELS_API_KEY now? (needed for B-roll footage)" false; then
            prompt_input "   Paste your Pexels API key:" PEXELS_KEY
            if [ -n "$PEXELS_KEY" ]; then
                sed -i.bak "s|PEXELS_API_KEY=.*|PEXELS_API_KEY=$PEXELS_KEY|" "$SCRIPT_DIR/.env"
                rm -f "$SCRIPT_DIR/.env.bak"
                echo "   ✅ PEXELS_API_KEY saved to .env"
            fi
        fi
    fi

    current_hf=$(grep "^HF_TOKEN=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d'=' -f2-)
    if [ -z "$current_hf" ] || [ "$current_hf" = "your-hf-token-here" ]; then
        if prompt_yesno "   Set HF_TOKEN now? (needed for podcast split-screen)" false; then
            prompt_input "   Paste your HuggingFace token:" HF_KEY
            if [ -n "$HF_KEY" ]; then
                sed -i.bak "s|HF_TOKEN=.*|HF_TOKEN=$HF_KEY|" "$SCRIPT_DIR/.env"
                rm -f "$SCRIPT_DIR/.env.bak"
                echo "   ✅ HF_TOKEN saved to .env"
            fi
        fi
    fi
fi
echo ""

# --- Step 5: Global CLI commands ---

echo "━━━ Step 5/6: Installing global CLI commands ━━━"

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

echo "   ✅ clipcast      → $BIN_DIR/clipcast"
echo "   ✅ clipcast-audio → $BIN_DIR/clipcast-audio"

# Check PATH
if echo "$PATH" | tr ':' '\n' | grep -q "$BIN_DIR"; then
    echo "   ✅ $BIN_DIR is in PATH"
else
    echo "   ⚠️  $BIN_DIR is NOT in PATH."
    # Try to add it automatically
    SHELL_PROFILE=""
    if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
        SHELL_PROFILE="$HOME/.zshrc"
    elif [ -n "$BASH_VERSION" ] || [ "$SHELL" = "/bin/bash" ]; then
        SHELL_PROFILE="$HOME/.bashrc"
    fi
    if [ -n "$SHELL_PROFILE" ] && prompt_yesno "   Add $BIN_DIR to $SHELL_PROFILE?" true; then
        echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$SHELL_PROFILE"
        echo "   ✅ Added to $SHELL_PROFILE — restart your shell or run: source $SHELL_PROFILE"
    else
        echo "   Add manually: export PATH=\"$BIN_DIR:\$PATH\""
    fi
fi

# Verify commands work
echo ""
echo "   Verifying..."
if "$BIN_DIR/clipcast" --help &>/dev/null; then
    echo "   ✅ clipcast works"
else
    echo "   ⚠️  clipcast --help failed"
fi
if "$BIN_DIR/clipcast-audio" --help &>/dev/null; then
    echo "   ✅ clipcast-audio works"
else
    echo "   ⚠️  clipcast-audio --help failed"
fi
echo ""

# --- Step 6: Agent skills ---

echo "━━━ Step 6/6: Agent skills (optional) ━━━"

if command -v npx &>/dev/null; then
    echo "   npx found — skills can be installed."

    SKILLS_SCOPE=""
    if prompt_yesno "   Install ClipCast skills for AI agents?" true; then
        if prompt_yesno "   Install globally (user-level) or project-level?" true; then
            SKILLS_SCOPE="-g"
            SCOPE_LABEL="global"
        else
            SKILLS_SCOPE=""
            SCOPE_LABEL="project"
        fi

        echo "   Installing $SCOPE_LABEL skills..."
        npx skills add prismosoft/clipcast --all $SKILLS_SCOPE -y 2>&1 || {
            echo "   ⚠️  Skills installation failed. You can install manually later:"
            echo "      npx skills add prismosoft/clipcast -g --all -y"
        }
        echo "   ✅ Skills installed ($SCOPE_LABEL)"
    else
        echo "   Skipped. Install later with:"
        echo "      npx skills add prismosoft/clipcast -g --all -y"
    fi
else
    echo "   ⚠️  npx not found — skills installation skipped."
    echo "   Install Node.js to use agent skills: https://nodejs.org"
    echo "   Then run: npx skills add prismosoft/clipcast -g --all -y"
fi
echo ""

# --- Done ---

echo "  ╔══════════════════════════════════════════════╗"
echo "  ║          ✅  Installation Complete!          ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
echo "  Commands:"
echo "    clipcast --help          Clip long videos into shorts"
echo "    clipcast-audio --help    Turn audio into B-roll videos"
echo ""
echo "  Quick test:"
echo "    clipcast --url \"https://youtube.com/watch?v=...\" --clips 2 \\"
echo "      --whisper-device cpu --whisper-compute-type int8 --no-broll"
echo ""
echo "    clipcast-audio --audio \"song.mp3\" --ratio 9:16"
echo ""
if ! $NONINTERACTIVE; then
    echo "  API keys:"
    grep -q "your-gemini-api-key-here\|your-pexels-api-key-here" "$SCRIPT_DIR/.env" 2>/dev/null && \
        echo "    ⚠️  Some API keys still set to defaults. Edit $SCRIPT_DIR/.env"
fi
echo ""