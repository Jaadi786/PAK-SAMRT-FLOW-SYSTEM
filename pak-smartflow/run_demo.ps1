# Pak-SmartFlow demo launcher.
#
#   .\run_demo.ps1              # all five scenarios
#   .\run_demo.ps1 4            # scenario 4, with Urdu notices
#   .\run_demo.ps1 4 -NoUrdu    # scenario 4, no Urdu
#   .\run_demo.ps1 -Check       # run tests and invariants first, then the demo

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Scenario,

    [switch]$NoUrdu,
    [switch]$Check,
    [string]$Db = "demo.sqlite"
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
Set-Location -Path $PSScriptRoot

function Get-Python {
    $candidates = @(
        "C:\Users\Jawad Ali\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe",
        "python",
        "py"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw "Python 3.10+ not found. Install it, or edit the candidates list in this script."
}

$python = Get-Python
Write-Host "python: $python" -ForegroundColor DarkGray

if ($Check) {
    Write-Host "`n== tests ==" -ForegroundColor Cyan
    & $python -m unittest discover -s tests -t .
    if ($LASTEXITCODE -ne 0) { throw "test suite failed" }

    Write-Host "`n== invariants ==" -ForegroundColor Cyan
    & $python -m smartflow selftest
    if ($LASTEXITCODE -ne 0) { throw "invariant checks failed" }
}

$demoArgs = @("-m", "smartflow", "demo")
if ($Scenario) {
    $demoArgs += $Scenario
} else {
    $demoArgs += "--all"
}
$demoArgs += @("--db", $Db)
if (-not $NoUrdu) { $demoArgs += "--urdu" }

Write-Host "`n== demo ==" -ForegroundColor Cyan
& $python @demoArgs

Write-Host "`n== legal probe ==" -ForegroundColor Cyan
& $python -m smartflow probe

Write-Host "`nCase file written to $Db" -ForegroundColor Green
Write-Host "Next: $python -m smartflow compliance RWP-9087 --db $Db" -ForegroundColor DarkGray
