$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
  Write-Host $Message -ForegroundColor Cyan
}

function Write-Warn([string]$Message) {
  Write-Host $Message -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
  Write-Host $Message -ForegroundColor Red
}

function Test-Administrator {
  try {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch {
    return $false
  }
}

function Get-PythonCommand {
  if ($env:PYTHON_BIN) {
    return $env:PYTHON_BIN
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return 'py -3.13'
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return 'python'
  }
  return $null
}

function Ensure-SystemDeps {
  param([switch]$NoSetup)

  if ($NoSetup) {
    return
  }

  $hasChoco = [bool](Get-Command choco -ErrorAction SilentlyContinue)
  $hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

  if (-not $hasChoco -and -not $hasWinget) {
    Write-Warn "No se detectó Chocolatey ni winget. Instala dependencias manualmente si falta algo."
    return
  }

  $isAdmin = Test-Administrator
  if (-not $isAdmin) {
    Write-Warn "No estás ejecutando PowerShell como Administrador. Si se requiere instalar algo, puede fallar."
  }

  if ($hasChoco) {
    Write-Step "Verificando dependencias (Chocolatey)..."
    choco install -y python --ignore-checksums | Out-Null
    choco install -y ffmpeg --ignore-checksums | Out-Null
    choco install -y yt-dlp --ignore-checksums | Out-Null
    return
  }

  if ($hasWinget) {
    Write-Step "Verificando dependencias (winget)..."
    winget install -e --id Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements | Out-Null
    winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements | Out-Null
    return
  }
}

function Test-FfmpegSubtitlesSupport {
  if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    return $false
  }
  try {
    $filters = & ffmpeg -hide_banner -filters 2>$null
    return $filters -match '\bsubtitles\b'
  } catch {
    return $false
  }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$NoSetup = $false
if ($args.Count -gt 0 -and $args[0] -eq '--no-setup') {
  $NoSetup = $true
}

Write-Step "▶︎ ReelsFactoryPro - arranque (PowerShell)"
Ensure-SystemDeps -NoSetup:$NoSetup

$pyCmd = Get-PythonCommand
if (-not $pyCmd) {
  Write-Err "No se encontró Python. Instala Python 3.11+ (x64) y reintenta."
  exit 1
}

if (!(Test-Path .venv)) {
  if ($NoSetup) {
    Write-Err "Falta el entorno virtual .venv. Ejecuta sin --no-setup para crearlo."
    exit 1
  }
  Write-Step "Creando venv (.venv)..."
  Invoke-Expression "$pyCmd -m venv .venv"
}

.\.venv\Scripts\Activate.ps1

# Solo se reinstalan las dependencias si requirements.txt cambió. Sin esto,
# cada arranque pagaba la descarga de torch (~2 GB) aunque nada hubiera
# cambiado.
$hashFile = Join-Path $ScriptDir '.venv\.requirements.sha256'
$currentHash = (Get-FileHash -Path (Join-Path $ScriptDir 'requirements.txt') -Algorithm SHA256).Hash

if (-not (Test-Path $hashFile) -or (Get-Content $hashFile -Raw).Trim() -ne $currentHash) {
  Write-Step "📦 Instalando dependencias Python (requirements.txt cambió)..."
  python -m pip install -U pip
  pip install -r requirements.txt
  Set-Content -Path $hashFile -Value $currentHash -NoNewline
} else {
  Write-Step "✅ Dependencias Python ya instaladas (sin cambios)."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Warn "FFmpeg no está disponible en PATH. Instálalo (choco/winget) o configura REELSFACTORYPRO_FFMPEG."
} elseif (-not (Test-FfmpegSubtitlesSupport)) {
  Write-Warn "Tu FFmpeg no incluye el filtro 'subtitles' (libass). Los subtítulos en el render pueden fallar."
}

Write-Step "🚀 Iniciando aplicación..."
python app.py
