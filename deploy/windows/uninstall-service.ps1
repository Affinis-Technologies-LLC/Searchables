<#
.SYNOPSIS
    Removes the Searchables Windows service. The library (PDFs, index, collections) is kept.

.EXAMPLE
    .\uninstall-service.ps1
    Stops and removes the service and its firewall rule; keeps C:\ProgramData\Searchables.

.EXAMPLE
    .\uninstall-service.ps1 -RemoveData
    Also deletes the data folder: every stored PDF, the search index, collections and logs.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$ServiceName = "Searchables",

    [string]$DataDir = (Join-Path $env:ProgramData "Searchables"),

    # Permanently delete the library. Asks for confirmation unless -Confirm:$false is given.
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell prompt (right-click PowerShell > Run as administrator)."
}

$Wrapper = Join-Path $PSScriptRoot "$ServiceName.exe"
$Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Service) {
    if ($Service.Status -ne "Stopped") { Stop-Service -Name $ServiceName -Force }
    if (Test-Path $Wrapper) { & $Wrapper uninstall } else { & sc.exe delete $ServiceName }
    Write-Host "Removed the $ServiceName service."
} else {
    Write-Host "No service named $ServiceName is installed."
}

Get-NetFirewallRule -DisplayName "Searchables ($ServiceName) TCP *" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Remove-Item -Path $Wrapper, (Join-Path $PSScriptRoot "$ServiceName.xml") -Force -ErrorAction SilentlyContinue

if ($RemoveData) {
    if ((Test-Path $DataDir) -and $PSCmdlet.ShouldProcess($DataDir, "Permanently delete the Searchables library")) {
        Remove-Item -Path $DataDir -Recurse -Force
        Write-Host "Deleted $DataDir."
    }
} else {
    Write-Host "Kept the library in $DataDir (use -RemoveData to delete it)."
}
