<#
.SYNOPSIS
  Hands-off "autodump + scan" loop to recover the HZD Remastered line->stream
  binding from the running game's RAM.

.DESCRIPTION
  Strategy A of docs/runtime-binding-plan.md, fully automated. The binding
  (resource GUID -> 64-bit stream key) exists only in engine RAM at runtime. This
  script:
    1. WAITS for the game process to appear (start the script BEFORE launching).
    2. Periodically captures a FULL-memory dump (procdump -ma, else comsvcs MiniDump).
    3. Runs tools/hzd_memscan.py on each dump to find resident binding records,
       accumulating recovered (line_id -> stream key) rows into one CSV.
    4. Deletes scan-miss dumps (bounded disk) unless -KeepAll; keeps any dump that
       yielded bindings (renamed hzd_hit_<n>.dmp).

  The user just: runs this, plays into dialogue scenes, then sends the table CSV.

.NOTES
  * Prereq: out\hzd\line_ids.csv must exist (build it once with
    `PYTHONPATH=src .venv\Scripts\python.exe tools\hzd_extract_ids.py`).
  * Run the terminal AS ADMINISTRATOR if dumping fails with "Access is denied".
  * Full dumps are multi-GB; without -KeepAll at most ~1 miss-dump exists at a time.
  * The comsvcs.dll MiniDump method may be flagged by AV (benign here).

  hzd_memscan exit codes: 0=bindings recovered, 1=GUIDs resident but no consistent
  delta (pointer-linked -> use the Frida hook), 2=no relevant data resident
  (dump too early / not in a dialogue scene).
#>
[CmdletBinding()]
param(
    [string] $ProcessName = "HorizonZeroDawnRemastered",
    [int]    $Interval    = 25,
    [int]    $MaxDumps    = 8,
    [string] $OutDir      = ".\hzd_dumps",
    [string] $Table       = ".\hzd_bindings.csv",
    [Parameter(Mandatory=$true)][string] $Package,
    [switch] $KeepAll
)

$ErrorActionPreference = "Stop"
$repo   = Split-Path -Parent $PSScriptRoot          # tools\.. = repo root
$python = Join-Path $repo ".venv\Scripts\python.exe"
$scan   = Join-Path $repo "tools\hzd_memscan.py"
$ids    = Join-Path $repo "out\hzd\line_ids.csv"

if (-not (Test-Path $python)) { throw "venv python not found at $python" }
if (-not (Test-Path $ids))    { throw "missing $ids -- run tools\hzd_extract_ids.py first" }
if (-not (Test-Path (Join-Path $Package "PackFileLocators.bin"))) {
    throw "no PackFileLocators.bin under -Package '$Package' -- point -Package at the game's LocalCacheDX12\package dir"
}
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# --- locate a dump tool -------------------------------------------------------
function Find-ProcDump {
    $cand = @(
        (Join-Path $PSScriptRoot "procdump.exe"),
        (Join-Path $PSScriptRoot "procdump64.exe")
    )
    foreach ($c in $cand) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command procdump.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}
$procdump = Find-ProcDump
if ($procdump) { Write-Host "[autodump] using procdump: $procdump" }
else { Write-Host "[autodump] procdump not found -> using comsvcs.dll MiniDump fallback" }

function Capture-Dump {
    param([int] $ProcId, [string] $Path)
    if ($procdump) {
        & $procdump -accepteula -ma $ProcId $Path | Out-Null
    } else {
        # Windows built-in full-memory dump via comsvcs.dll.
        rundll32.exe "$env:WINDIR\System32\comsvcs.dll", MiniDump $ProcId $Path full
    }
    return (Test-Path $Path)
}

# --- wait for the process (start this BEFORE launching the game) --------------
Write-Host "[autodump] waiting for process '$ProcessName' (start the game now)..."
$proc = $null
while (-not $proc) {
    $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $proc) { Start-Sleep -Seconds 2 }
}
Write-Host "[autodump] found PID $($proc.Id). Capturing up to $MaxDumps dumps every $Interval s."
Write-Host "[autodump] Play into dialogue scenes (e.g. the prologue naming ceremony)."

# --- capture / scan loop ------------------------------------------------------
$hitCount = 0
$lastExit = $null
for ($i = 1; $i -le $MaxDumps; $i++) {
    # re-resolve PID in case the game restarted
    $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $proc) { Write-Host "[autodump] process gone; stopping."; break }

    $dump = Join-Path $OutDir ("hzd_{0:yyyyMMdd_HHmmss}.dmp" -f (Get-Date))
    Write-Host "[autodump] ($i/$MaxDumps) dumping PID $($proc.Id) -> $dump"
    $ok = $false
    try { $ok = Capture-Dump -ProcId $proc.Id -Path $dump }
    catch { Write-Warning "[autodump] dump failed: $($_.Exception.Message) (try running as Administrator)" }
    if (-not $ok) {
        Write-Warning "[autodump] no dump produced; retrying after interval."
        Start-Sleep -Seconds $Interval
        continue
    }

    Write-Host "[autodump] scanning $dump ..."
    & $python $scan --dump $dump --ids $ids --package $Package --table $Table
    $lastExit = $LASTEXITCODE
    Write-Host "[autodump] memscan exit code: $lastExit"

    if ($lastExit -eq 0) {
        $hitCount++
        $kept = Join-Path $OutDir ("hzd_hit_{0}.dmp" -f $hitCount)
        Move-Item -Path $dump -Destination $kept -Force
        Write-Host "[autodump] BINDINGS FOUND -> kept dump as $kept; table -> $Table"
        # keep going to MaxDumps to accumulate coverage from other scenes
    }
    elseif (-not $KeepAll) {
        Remove-Item -Path $dump -Force -ErrorAction SilentlyContinue
        Write-Host "[autodump] no bindings this dump (exit $lastExit) -> deleted (bounded disk)"
    }

    if ($i -lt $MaxDumps) { Start-Sleep -Seconds $Interval }
}

# --- final summary ------------------------------------------------------------
$rows = 0
if (Test-Path $Table) {
    $rows = (Import-Csv $Table | Measure-Object).Count
}
Write-Host ""
Write-Host "===================== autodump summary ====================="
Write-Host "  dumps attempted     : up to $MaxDumps"
Write-Host "  dumps with bindings : $hitCount"
Write-Host "  bindings in table   : $rows  ($Table)"
if ($rows -gt 0) {
    Write-Host "  NEXT: send $Table back. It maps line_id -> stream_key for resident lines."
} elseif ($lastExit -eq 1) {
    Write-Host "  NEXT: GUIDs were resident but the binding record is pointer-linked."
    Write-Host "        Pivot to the Frida hook (tools\hzd_dstorage_hook.js, Strategy B)."
} elseif ($lastExit -eq 2) {
    Write-Host "  NEXT: nothing relevant was resident -- dump earlier / while in a dialogue scene,"
    Write-Host "        or increase -MaxDumps / lower -Interval for more coverage."
} else {
    Write-Host "  NEXT: no dumps were scanned successfully; check dump-tool / admin rights."
}
Write-Host "============================================================"
