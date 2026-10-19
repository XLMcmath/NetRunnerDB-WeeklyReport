# Weekly NetrunnerDB digest runner.
# -IfDue : only run when the newest issue is older than ~6.5 days (used by the startup hook)
# -Force : always run now
# ASCII-only on purpose: this file is also launched by Windows PowerShell 5.1.

param(
    [switch]$IfDue,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $here "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path (Join-Path $logDir "runner.log") -Value $line -Encoding utf8
}

if ($IfDue) {
    $newest = Get-ChildItem $here -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d{4}-W\d{2}$' } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($newest) {
        $idx = Join-Path $newest.FullName "index.html"
        if ((Test-Path $idx) -and (((Get-Date) - (Get-Item $idx).LastWriteTime).TotalDays -lt 6.5)) {
            Write-Log ("skip: {0} is fresh" -f $newest.Name)
            exit 0
        }
    }
}

# Prefer the bundled runtime, fall back to python on PATH.
$py = "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source } else { Write-Log "FATAL: python not found"; exit 2 }
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$log = Join-Path $logDir ("run_" + $stamp + ".log")
$env:PYTHONIOENCODING = "utf-8"

Write-Log ("start: python={0}" -f $py)
& $py (Join-Path $here "nrdb_weekly.py") --days 7 *> $log
$code = $LASTEXITCODE
Write-Log ("done: exit={0} log={1}" -f $code, (Split-Path -Leaf $log))

# Keep 90 days of logs.
Get-ChildItem $logDir -Filter "run_*.log" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $code
