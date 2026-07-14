#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Deletes the HZD runtime-binding RAM dumps (tools/hzd_dumps/*.dmp).

  These are git-ignored, regenerable autodump scratch written by an elevated
  procdump/comsvcs MiniDump pass, so their ACLs deny deletion from a normal
  (non-elevated) session. Run this from an Administrator PowerShell.

  Safe to run repeatedly; does nothing if the folder is already gone.
#>

$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'hzd_dumps'

if (-not (Test-Path $target)) {
    Write-Host "Nothing to do - '$target' does not exist. Already clean." -ForegroundColor Green
    return
}

$before = (Get-ChildItem $target -Recurse -File -Force -ErrorAction SilentlyContinue |
           Measure-Object Length -Sum).Sum
Write-Host ("Found {0:N2} GB in {1}" -f ($before / 1GB), $target) -ForegroundColor Cyan

# First attempt: plain delete. An elevated Administrators token usually has rights.
try {
    Remove-Item -Recurse -Force $target -ErrorAction Stop
    Write-Host "Deleted on first pass." -ForegroundColor Green
}
catch {
    # Fallback: the dumps were written with ACLs that exclude even Administrators.
    # Take ownership and grant the Administrators group full control, then delete.
    Write-Warning "Direct delete failed ($($_.Exception.Message)). Taking ownership..."
    takeown /f $target /r /d y | Out-Null
    icacls $target /grant *S-1-5-32-544:F /t /c | Out-Null
    Remove-Item -Recurse -Force $target -ErrorAction Stop
    Write-Host "Deleted after taking ownership." -ForegroundColor Green
}

if (Test-Path $target) {
    Write-Error "Folder still present - deletion did not fully succeed."
}
else {
    Write-Host ("Reclaimed {0:N2} GB. tools/hzd_dumps is gone." -f ($before / 1GB)) -ForegroundColor Green
}
