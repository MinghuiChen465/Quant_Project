$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# 优先使用 Python Launcher；否则使用 PATH 中可用的 Python。
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    else { python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed.' }
}
& ./.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& ./.venv/Scripts/python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
& ./.venv/Scripts/python.exe run_week1.py
if ($LASTEXITCODE -ne 0) { throw 'Week 1 pipeline failed.' }
