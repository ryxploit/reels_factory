#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_PATH="$SCRIPT_DIR/.venv"

if [ ! -x "$0" ]; then
  chmod +x "$0" 2>/dev/null || true
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'EOF'
Uso:
  ./run.sh                # verifica/instala deps, crea venv si falta y arranca la app
  ./run.sh --no-setup     # no instala nada automáticamente (fallará si falta algo)

Variables opcionales:
  PYTHON_BIN=python3.11
  REELSFACTORYPRO_FFMPEG=/ruta/a/ffmpeg
  REELSFACTORYPRO_FFPROBE=/ruta/a/ffprobe
EOF
  exit 0
fi

OS_UNAME="$(uname -s 2>/dev/null || echo unknown)"

is_wsl() {
  [ -f /proc/version ] && grep -qi microsoft /proc/version
}

is_git_bash_windows() {
  case "$OS_UNAME" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

is_macos() {
  [ "$OS_UNAME" = "Darwin" ]
}

is_linux() {
  [ "$OS_UNAME" = "Linux" ]
}

log() { printf "%s\n" "$*"; }
die() { printf "%s\n" "$*"; exit 1; }

ensure_homebrew() {
  if ! command -v brew >/dev/null 2>&1; then
    die "❌ Homebrew no está instalado. Instálalo desde https://brew.sh y reintenta."
  fi

  if [ -d "/opt/homebrew/bin" ]; then
    export PATH="/opt/homebrew/bin:$PATH"
  fi
}

ensure_choco() {
  if ! command -v choco >/dev/null 2>&1; then
    die "❌ Chocolatey no está instalado en Windows. Instálalo desde https://chocolatey.org/install y reintenta (Git Bash/WSL)."
  fi
}

ensure_apt() {
  if ! command -v apt-get >/dev/null 2>&1; then
    die "❌ No se encontró apt-get. Si estás en Linux, usa una distro compatible (Ubuntu/Debian) o instala dependencias manualmente."
  fi
}

brew_install_if_missing() {
  local formula="$1"
  if brew list --formula "$formula" >/dev/null 2>&1; then
    return 0
  fi
  log "📦 Instalando $formula..."
  brew install "$formula"
}

apt_install_if_missing() {
  local pkg="$1"
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    return 0
  fi
  log "📦 Instalando $pkg..."
  sudo apt-get update -y
  sudo apt-get install -y "$pkg"
}

choco_install_if_missing() {
  local pkg="$1"
  if choco list --local-only --exact "$pkg" >/dev/null 2>&1; then
    return 0
  fi
  log "📦 Instalando $pkg..."
  choco install -y "$pkg"
}

ensure_ffmpeg_full_path_macos() {
  if command -v brew >/dev/null 2>&1; then
    local prefix
    prefix="$(brew --prefix ffmpeg-full 2>/dev/null || true)"
    if [ -n "$prefix" ] && [ -d "$prefix/bin" ]; then
      export PATH="$prefix/bin:$PATH"
    fi
  fi
}

ffmpeg_has_subtitles_filter() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    return 1
  fi
  ffmpeg -hide_banner -filters 2>/dev/null | grep -Eq "\bsubtitles\b"
}

choose_python() {
  if [ -n "${PYTHON_BIN:-}" ] && command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "${PYTHON_BIN}"
    return
  fi
  local candidate
  for candidate in python3.12 python3.11 python3 py; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}

python_version_ok() {
  local py="$1"
  if [ "$py" = "py" ]; then
    py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1
    return $?
  fi
  "$py" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1
}

install_system_deps() {
  if [ "${1:-}" = "--no-setup" ]; then
    return 0
  fi

  if is_macos; then
    ensure_homebrew
    log "🔎 macOS detectado. Verificando dependencias..."
    brew_install_if_missing "python@3.11" || true
    brew_install_if_missing "ffmpeg-full" || true
    brew_install_if_missing "yt-dlp" || true
    ensure_ffmpeg_full_path_macos
    return 0
  fi

  if is_linux && is_wsl; then
    ensure_apt
    log "🔎 WSL detectado. Verificando dependencias..."
    apt_install_if_missing "ffmpeg" || true
    apt_install_if_missing "python3" || true
    apt_install_if_missing "python3-venv" || true
    return 0
  fi

  if is_git_bash_windows; then
    ensure_choco
    log "🔎 Windows (Git Bash) detectado. Verificando dependencias..."
    choco_install_if_missing "python" || true
    choco_install_if_missing "ffmpeg" || true
    choco_install_if_missing "yt-dlp" || true
    return 0
  fi
}

setup_venv_and_python_deps() {
  local no_setup="${1:-}"
  local py
  py="$(choose_python)"

  if [ -z "$py" ]; then
    die "❌ No se encontró Python en PATH. Instala Python 3.11+ y reintenta."
  fi

  if ! python_version_ok "$py"; then
    die "❌ Python detectado no cumple el mínimo (3.11). Instala Python 3.11+ y reintenta."
  fi

  if [ ! -d "$VENV_PATH" ]; then
    if [ "$no_setup" = "--no-setup" ]; then
      die "❌ Falta el entorno virtual: $VENV_PATH (ejecuta ./run.sh sin --no-setup)."
    fi
    log "🐍 Creando entorno virtual (.venv)..."
    cd "$SCRIPT_DIR"
    if [ "$py" = "py" ]; then
      py -3.11 -m venv ".venv"
    else
      "$py" -m venv ".venv"
    fi
  fi

  # shellcheck disable=SC1091
  source "$VENV_PATH/bin/activate"
  "$VENV_PATH/bin/python" -m pip install -U pip
  "$VENV_PATH/bin/pip" install -r requirements.txt
}

verify_runtime_deps() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    die "❌ FFmpeg no está disponible. Instálalo (macOS: brew install ffmpeg-full; Windows: choco install ffmpeg; WSL: sudo apt-get install ffmpeg)."
  fi

  if ! command -v ffprobe >/dev/null 2>&1; then
    die "❌ ffprobe no está disponible (viene con FFmpeg). Reinstala FFmpeg."
  fi

  # El aviso de soporte de subtítulos se maneja en la UI.
}

main() {
  cd "$SCRIPT_DIR"

  log "▶︎ ReelsFactoryPro - arranque"

  install_system_deps "${1:-}"

  if is_macos; then
    ensure_ffmpeg_full_path_macos
  fi

  setup_venv_and_python_deps "${1:-}"
  verify_runtime_deps

  export PYTORCH_ENABLE_MPS_FALLBACK=1

  log "🚀 Iniciando aplicación..."
  py="$(choose_python)"
  "$VENV_PATH/bin/python" app.py
}

main "${1:-}"
