$ErrorActionPreference = 'Stop'

Set-Location -Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent)

if (!(Test-Path .venv)) {
  py -3.11 -m venv .venv
}

.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install cx_Freeze

python packaging\windows\cxfreeze_setup.py bdist_msi

Write-Host "MSI generado en dist/" -ForegroundColor Green

