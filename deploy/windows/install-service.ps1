<#
.SYNOPSIS
    Installs Searchables (the Streamlit app) as a Windows service using WinSW.

.DESCRIPTION
    Creates the Python environment, prepares a data folder the service account can write to,
    finds Tesseract for OCR, writes the WinSW service configuration, installs and starts the
    service, and checks that the app responds. Safe to re-run: an existing service with the same
    name is stopped and replaced, and the data folder is never touched beyond permissions.

    Run from an elevated PowerShell prompt (Run as administrator).

.EXAMPLE
    .\install-service.ps1
    Local-only install on http://127.0.0.1:8501 with data in C:\ProgramData\Searchables.

.EXAMPLE
    .\install-service.ps1 -Address 0.0.0.0 -Port 8600 -OpenFirewall
    Reachable from other machines on the network (the app has no login; see README).
#>
[CmdletBinding()]
param(
    # Windows service name (also the WinSW wrapper's file name)
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$ServiceName = "Searchables",

    [ValidateRange(1, 65535)]
    [int]$Port = 8501,

    # 127.0.0.1 = this machine only; 0.0.0.0 = all network interfaces
    [string]$Address = "127.0.0.1",

    # Library: stored PDFs, SQLite index, collections, and service logs
    [string]$DataDir = (Join-Path $env:ProgramData "Searchables"),

    # Built-in accounts only: LocalService (least privilege), NetworkService, or LocalSystem
    [ValidateSet("LocalService", "NetworkService", "LocalSystem")]
    [string]$ServiceAccount = "LocalService",

    # python.exe (3.10+) used to create the environment; default: the "py" launcher
    [string]$Python = "",

    # A WinSW-x64.exe you downloaded yourself; default: download the pinned release from GitHub
    [string]$WinSWPath = "",

    # Tesseract "tessdata" folder; default: TESSDATA_PREFIX or the standard install location
    [string]$TessdataDir = "",

    # Add an inbound firewall rule for the port (only meaningful when -Address isn't 127.0.0.1)
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WinSWVersion = "v2.12.0"
$WinSWUrl = "https://github.com/winsw/winsw/releases/download/$WinSWVersion/WinSW-x64.exe"
$AccountSids = @{ LocalService = "*S-1-5-19"; NetworkService = "*S-1-5-20" }
$AccountNames = @{ LocalService = "NT AUTHORITY\LocalService"; NetworkService = "NT AUTHORITY\NetworkService"; LocalSystem = "LocalSystem" }

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-XmlSafe([string]$Value) { return [System.Security.SecurityElement]::Escape($Value) }

if (-not (Test-Administrator)) {
    throw "Run this script from an elevated PowerShell prompt (right-click PowerShell > Run as administrator)."
}

# ---- Locate the app ------------------------------------------------------------------------
$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not (Test-Path (Join-Path $AppDir "app.py"))) {
    throw "app.py not found in $AppDir. Run this script from deploy\windows inside the project."
}
if ($ServiceAccount -ne "LocalSystem" -and $AppDir.StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Warning ("The project is inside your user profile ($AppDir). The $ServiceAccount account can't read " +
                   "other users' profiles, so the service will fail to start. Move the project to a folder " +
                   "such as C:\Apps\Searchables and run this script again.")
    throw "Project location isn't readable by $ServiceAccount."
}
Write-Step "Project: $AppDir"

# ---- Python environment --------------------------------------------------------------------
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
if ([version]$PyVersion -lt [version]"3.10") { throw "Python $PyVersion found; Searchables needs 3.10 or newer." }
# A venv runs its base interpreter from the "home" folder in pyvenv.cfg; the service account must be able to read it
$BasePython = (Get-Content (Join-Path $AppDir ".venv\pyvenv.cfg") | Where-Object { $_ -match '^\s*home\s*=' }) -replace '^\s*home\s*=\s*', ''
if ($ServiceAccount -ne "LocalSystem" -and $BasePython.StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase)) {
    throw ("Python is installed for your user only ($BasePython), which $ServiceAccount can't read. Reinstall Python " +
           "from python.org choosing 'Install for all users', delete the .venv folder, and run this script again.")
}

Write-Step "Installing Python packages (first run can take several minutes)"
& $VenvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "Upgrading pip failed." }
& $VenvPython -m pip install -r (Join-Path $AppDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Installing requirements.txt failed." }

# ---- Data folder and permissions -----------------------------------------------------------
Write-Step "Data folder: $DataDir"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null
if ($AccountSids.ContainsKey($ServiceAccount)) {
    $Sid = $AccountSids[$ServiceAccount]
    # Modify on the data folder (library, logs); read & execute on the app and its Python environment
    & icacls $DataDir /grant "${Sid}:(OI)(CI)M" /T /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Granting $ServiceAccount access to $DataDir failed." }
    & icacls $AppDir /grant "${Sid}:(OI)(CI)RX" /T /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Granting $ServiceAccount read access to $AppDir failed." }
}

# ---- Tesseract (optional, for scanned pages) -----------------------------------------------
if (-not $TessdataDir) {
    $Candidates = @($env:TESSDATA_PREFIX,
                    (Join-Path $env:ProgramFiles "Tesseract-OCR\tessdata"),
                    (Join-Path ${env:ProgramFiles(x86)} "Tesseract-OCR\tessdata")) | Where-Object { $_ }
    $TessdataDir = $Candidates | Where-Object { Test-Path (Join-Path $_ "eng.traineddata") } | Select-Object -First 1
}
if ($TessdataDir) {
    Write-Step "Tesseract language data: $TessdataDir"
} else {
    Write-Warning "Tesseract language data not found: scanned pages won't be searchable. See README (OCR) to add it later."
}

# ---- WinSW wrapper -------------------------------------------------------------------------
# WinSW reads the configuration from an .xml file with the same name as the renamed executable
$Wrapper = Join-Path $PSScriptRoot "$ServiceName.exe"
$ConfigPath = Join-Path $PSScriptRoot "$ServiceName.xml"

$Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Step "Replacing the existing $ServiceName service"
    if ($Existing.Status -ne "Stopped") { Stop-Service -Name $ServiceName -Force }
    if (Test-Path $Wrapper) { & $Wrapper uninstall | Out-Null } else { & sc.exe delete $ServiceName | Out-Null }
    Start-Sleep -Seconds 2
}

if ($WinSWPath) {
    Copy-Item -Path $WinSWPath -Destination $Wrapper -Force
} elseif (-not (Test-Path $Wrapper)) {
    Write-Step "Downloading WinSW $WinSWVersion from GitHub"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $WinSWUrl -OutFile $Wrapper -UseBasicParsing
}
Write-Host ("    WinSW SHA-256: " + (Get-FileHash $Wrapper -Algorithm SHA256).Hash +
            "  (compare with the release page if you want to verify it)")

# ---- Service configuration -----------------------------------------------------------------
$Arguments = @(
    "-m", "streamlit", "run", "`"$(Join-Path $AppDir 'app.py')`"",
    "--server.port", $Port,
    "--server.address", $Address,
    "--server.headless", "true",
    "--server.fileWatcherType", "none",   # No source-file polling in production
    "--browser.gatherUsageStats", "false"
) -join " "

$EnvLines = @(
    "    <env name=`"SEARCHABLES_DATA_DIR`" value=`"$(Get-XmlSafe $DataDir)`" />",
    "    <env name=`"PYTHONUNBUFFERED`" value=`"1`" />"
)
if ($TessdataDir) { $EnvLines += "    <env name=`"TESSDATA_PREFIX`" value=`"$(Get-XmlSafe $TessdataDir)`" />" }

$DisplayName = if ($ServiceName -eq "Searchables") { "Searchables" } else { "Searchables ($ServiceName)" }
$Xml = @"
<service>
    <id>$ServiceName</id>
    <name>$DisplayName</name>
    <description>Standards Search: Streamlit app for searching licensed standards PDFs, on port $Port.</description>
    <executable>$(Get-XmlSafe $VenvPython)</executable>
    <arguments>$(Get-XmlSafe $Arguments)</arguments>
    <workingdirectory>$(Get-XmlSafe $AppDir)</workingdirectory>
$($EnvLines -join "`r`n")
    <startmode>Automatic</startmode>
    <delayedAutoStart>true</delayedAutoStart>
    <onfailure action="restart" delay="10 sec" />
    <onfailure action="restart" delay="30 sec" />
    <onfailure action="restart" delay="2 min" />
    <resetfailure>1 hour</resetfailure>
    <stoptimeout>15 sec</stoptimeout>
    <logpath>$(Get-XmlSafe (Join-Path $DataDir 'logs'))</logpath>
    <log mode="roll-by-size">
        <sizeThreshold>10240</sizeThreshold>
        <keepFiles>8</keepFiles>
    </log>
</service>
"@
Set-Content -Path $ConfigPath -Value $Xml -Encoding UTF8
Write-Step "Service configuration written to $ConfigPath"

# ---- Install, set account, start -----------------------------------------------------------
& $Wrapper install
if ($LASTEXITCODE -ne 0) { throw "WinSW failed to install the service." }
# Built-in service accounts have no password. CIM rather than sc.exe: Windows PowerShell 5.1 drops the
# empty-string argument that "sc.exe config ... password= """ relies on.
$Result = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" |
    Invoke-CimMethod -MethodName Change -Arguments @{ StartName = $AccountNames[$ServiceAccount]; StartPassword = "" }
if ($Result.ReturnValue -ne 0) { throw "Setting the service account to $ServiceAccount failed (Win32 error $($Result.ReturnValue))." }

$IsLoopback = $Address -in @("127.0.0.1", "localhost", "::1")
if ($OpenFirewall) {
    if ($IsLoopback) {
        Write-Warning "-OpenFirewall ignored: the app only listens on $Address. Use -Address 0.0.0.0 to allow other machines."
    } else {
        $RuleName = "Searchables ($ServiceName) TCP $Port"
        Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -Profile Domain, Private | Out-Null
        Write-Step "Firewall rule added: $RuleName (Domain and Private networks only)"
    }
}

Write-Step "Starting the service"
Start-Service -Name $ServiceName

$ProbeHost = if ($Address -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $Address }
$Url = "http://${ProbeHost}:$Port"
$Healthy = $false
foreach ($i in 1..60) {
    try {
        $Response = Invoke-WebRequest -Uri "$Url/_stcore/health" -UseBasicParsing -TimeoutSec 2
        if ($Response.StatusCode -eq 200) { $Healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}

if ($Healthy) {
    Write-Host ""
    Write-Host "Searchables is running: $Url" -ForegroundColor Green
    if (-not $IsLoopback) {
        Write-Warning "The app is reachable from the network and has no login. Anyone who can reach port $Port can read and delete documents."
    }
} else {
    Write-Warning "The service started but the app didn't answer within 60 seconds. Check the logs in $(Join-Path $DataDir 'logs')."
    exit 1
}
