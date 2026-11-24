# Install the noobit-capcut-rough-cut skill on Windows (PowerShell).
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1          -> %USERPROFILE%\.claude\skills
#         powershell -ExecutionPolicy Bypass -File install.ps1 -All     -> also Codex + Antigravity
#         powershell -ExecutionPolicy Bypass -File install.ps1 -Deps    -> also ffmpeg + whisper.cpp + Thai model (3 GB)
# Status: written for Windows but not yet tested on a real Windows machine.
param([switch]$All, [switch]$Deps)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Src = Split-Path -Parent $MyInvocation.MyCommand.Path
$Name = "noobit-capcut-rough-cut"

# 1) Python (the skill's script needs it). The "python" in a fresh Windows is often a Microsoft Store stub.
function Find-Python {
    foreach ($c in @("py", "python", "python3")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
            $pyArgs = @(); if ($c -eq "py") { $pyArgs = @("-3") }
            try { & $c @pyArgs -c "import sys; assert sys.version_info >= (3, 8)" 2>$null; if ($LASTEXITCODE -eq 0) { return @($c) + $pyArgs } } catch {}
        }
    }
    return $null
}
$Py = Find-Python
if (-not $Py) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python 3.12 with winget ..."
        winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $Py = Find-Python
    }
    if (-not $Py) {
        Write-Host "! Python not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
        exit 1
    }
}

# 2) Copy the skill
$Dests = @("$env:USERPROFILE\.claude\skills")
if ($All) { $Dests += @("$env:USERPROFILE\.codex\skills", "$env:USERPROFILE\.gemini\antigravity\skills") }
foreach ($d in $Dests) {
    $t = Join-Path $d $Name
    if ((Resolve-Path $Src).Path -eq $t) { continue }
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    foreach ($sub in @("scripts", "references")) { if (Test-Path "$t\$sub") { Remove-Item -Recurse -Force "$t\$sub" } }
    Copy-Item "$Src\SKILL.md" $t -Force
    Copy-Item "$Src\scripts", "$Src\references" $t -Recurse -Force
    if (Test-Path "$t\scripts\__pycache__") { Remove-Item -Recurse -Force "$t\scripts\__pycache__" }
    Write-Host "installed -> $t"
}
Write-Host ""

# 3) Tools
$exe = $Py[0]; $pre = @(); if ($Py.Count -gt 1) { $pre = $Py[1..($Py.Count - 1)] }
if ($Deps) { & $exe @pre "$Src\scripts\ncr.py" doctor --install }
else {
    & $exe @pre "$Src\scripts\ncr.py" doctor
    if ($LASTEXITCODE -ne 0) { Write-Host "(ไม่เป็นไรครับ ตอนใช้งานครั้งแรก AI จะติดตั้งตัวที่ขาดให้เอง หรือรัน install.ps1 -Deps)" }
}
