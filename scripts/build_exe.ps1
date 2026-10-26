# Build onedir PyInstaller + Inno Setup: dist\SIS-DG-APAC\ e dist\SIS-DG-APAC-Setup.exe
param(
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "venv não encontrado em .venv. Crie com: py -3 -m venv .venv"
}

function Find-Iscc {
    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

Write-Host "==> Instalando PyInstaller (dev)..."
& $Py -m pip install -q "pyinstaller>=6.0.0"

Write-Host "==> Limpando build/dist anteriores..."
$DistApp = Join-Path $Root "dist\SIS-DG-APAC"
$DistSetup = Join-Path $Root "dist\SIS-DG-APAC-Setup.exe"
if (Test-Path (Join-Path $Root "build")) {
    Remove-Item -Recurse -Force (Join-Path $Root "build")
}
if (Test-Path $DistApp) {
    Remove-Item -Recurse -Force $DistApp
}
if (Test-Path $DistSetup) {
    Remove-Item -Force $DistSetup
}

Write-Host "==> PyInstaller (apac-bot.spec)..."
$Spec = Join-Path $Root "packaging\apac-bot.spec"
& $Py -m PyInstaller $Spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $DistApp)) {
    Write-Error "Pasta dist\SIS-DG-APAC não gerada."
}

Copy-Item (Join-Path $Root "config.example.json") `
    (Join-Path $DistApp "config.example.json") -Force
Copy-Item (Join-Path $Root "packaging\DIST_README.txt") `
    (Join-Path $DistApp "LEIA-ME.txt") -Force

$Exe = Join-Path $DistApp "SIS-DG-APAC.exe"
Write-Host ""
Write-Host "OK: $Exe"

if ($SkipSetup) {
    Write-Host "SkipSetup: pasta onedir pronta (Setup.exe não gerado)."
    Write-Host "Copie a pasta dist\SIS-DG-APAC inteira para o PC alvo."
    Write-Host "Veja LEIA-ME.txt (config + playwright install chromium)."
    exit 0
}

Write-Host "==> Inno Setup (sis-dg-apac.iss)..."
$Iscc = Find-Iscc
if (-not $Iscc) {
    Write-Error @"
ISCC.exe (Inno Setup 6) não encontrado.
Instale: https://jrsoftware.org/isinfo.php
  ou: winget install --id JRSoftware.InnoSetup -e
Para gerar só a pasta onedir: .\scripts\build_exe.ps1 -SkipSetup
"@
}

$Iss = Join-Path $Root "packaging\sis-dg-apac.iss"
& $Iscc $Iss
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $DistSetup)) {
    Write-Error "Setup não gerado: dist\SIS-DG-APAC-Setup.exe"
}

Write-Host ""
Write-Host "OK: $DistSetup"
Write-Host "Distribua o Setup.exe (ou a pasta dist\SIS-DG-APAC)."
Write-Host "Veja LEIA-ME.txt (config + playwright install chromium)."
