# Pak-SmartFlow verification launcher.
#
#   .\run_tests.ps1
#
# Runs the full suite, the fast invariants, and a syntax check on the optional
# modules (which need extras that may not be installed).

[CmdletBinding()]
param()

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
    throw "Python 3.10+ not found."
}

$python = Get-Python

Write-Host "== syntax check (all modules) ==" -ForegroundColor Cyan
& $python -m compileall -q smartflow vision tools app_streamlit.py streamlit_app.py tests
if ($LASTEXITCODE -ne 0) { throw "compileall failed" }

Write-Host "`n== zero-dependency claim ==" -ForegroundColor Cyan
& $python tools/check_zero_deps.py
if ($LASTEXITCODE -ne 0) { throw "the core pulled in a third-party package" }

Write-Host "`n== full test suite ==" -ForegroundColor Cyan
& $python -m unittest discover -s tests -t . -v 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) { throw "test suite failed" }

Write-Host "`n== invariants ==" -ForegroundColor Cyan
& $python -m smartflow selftest
if ($LASTEXITCODE -ne 0) { throw "invariant checks failed" }

Write-Host "`n== legal probe ==" -ForegroundColor Cyan
& $python -m smartflow probe | Select-Object -Last 12
if ($LASTEXITCODE -ne 0) { throw "a prohibited operation succeeded" }

Write-Host "`n== all five scenarios ==" -ForegroundColor Cyan
& $python -m smartflow demo --all 2>&1 | Select-String -Pattern "RUN SUMMARY" -Context 0,9
if ($LASTEXITCODE -ne 0) { throw "scenario run failed" }

Write-Host "`nAll checks passed." -ForegroundColor Green
