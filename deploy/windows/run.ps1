<#
.SYNOPSIS
    Starts Searchables in this PowerShell window (no Windows service). Stop it with Ctrl+C.

.DESCRIPTION
    Sets up .venv and installs requirements.lock on first use, and again whenever requirements.lock
    changes. The library is kept in the project's data folder, as when the app is run by hand.
    For a service that starts with Windows, use install-service.ps1 instead.

.EXAMPLE
    .\run.ps1
    .\run.ps1 -Port 8600
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8501,

    # python.exe (3.10+) used to create .venv; default: the "py" launcher
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $AppDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Step "Creating Python environment in .venv"
    if ($Python) {
        & $Python -m venv (Join-Path $AppDir ".venv")
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv (Join-Path $AppDir ".venv")
    } else {
        throw "Python not found. Install Python 3.10+ from python.org (with the 'py' launcher) or pass -Python C:\path\to\python.exe."
    }
    if ($LASTEXITCODE -ne 0) { throw "Creating the Python environment failed." }
}
$PyVersion = & $VenvPython -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$PyVersion -lt [version]"3.10") {
    throw "The .venv uses Python $PyVersion; Searchables needs 3.10 or newer. Delete the .venv folder and run this again."
}

# Reinstall only when requirements.lock changes: installing is slow (PyTorch via sentence-transformers).
# The lock file pins every package to an exact version and hash; pip refuses anything else.
$Requirements = Join-Path $AppDir "requirements.lock"
$Stamp = Join-Path $AppDir ".venv\.requirements.sha256"
$Current = (Get-FileHash $Requirements -Algorithm SHA256).Hash
if (-not (Test-Path $Stamp) -or (Get-Content $Stamp -Raw).Trim() -ne $Current) {
    Write-Step "Installing Python packages (the first run can take several minutes)"
    & $VenvPython -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { throw "Upgrading pip failed." }
    & $VenvPython -m pip install --require-hashes -r $Requirements --quiet
    if ($LASTEXITCODE -ne 0) { throw "Installing requirements.lock failed." }
    Set-Content -Path $Stamp -Value $Current
}

# The meaning-search model is downloaded once, so the app itself never needs the internet
Push-Location $AppDir
try {
    # Everything the app needs is loaded once now, so a problem shows here rather than as an app that won't start
    & $VenvPython -m src.server --check
    if ($LASTEXITCODE -ne 0) { throw "The app can't start (see above). If packages are at fault, delete the .venv folder and run this again." }
    & $VenvPython -m src.search.semantic
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The meaning-search model couldn't be downloaded (no internet?). Search still works by words."
    }
} finally { Pop-Location }

# Tesseract for scanned pages: an existing TESSDATA_PREFIX, or the standard install location
if (-not $env:TESSDATA_PREFIX) {
    $Tessdata = @((Join-Path $env:ProgramFiles "Tesseract-OCR\tessdata"),
                  (Join-Path ${env:ProgramFiles(x86)} "Tesseract-OCR\tessdata")) |
        Where-Object { $_ -and (Test-Path (Join-Path $_ "eng.traineddata")) } | Select-Object -First 1
    if ($Tessdata) {
        $env:TESSDATA_PREFIX = $Tessdata
    } else {
        Write-Warning "Tesseract not found: scanned pages won't be searchable. See deploy\windows\README.md (OCR)."
    }
}

Set-Location $AppDir
Write-Step "Starting Searchables on http://127.0.0.1:$Port (Ctrl+C to stop)"
& $VenvPython -m src.server --port $Port --address 127.0.0.1
exit $LASTEXITCODE
