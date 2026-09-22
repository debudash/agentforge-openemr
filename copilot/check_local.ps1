# Local gate for the Clinical Co-Pilot. Run this before any Railway publish.
#
#   cd copilot
#   .\check_local.ps1                 # unit tests + golden gate (needs OPENROUTER_API_KEY in .env)
#   .\check_local.ps1 -WithGateway    # also the live OpenEMR gateway tests (local stack + service up,
#                                     #   OE_DOCTOR_PASS set for the physician cases)
#   .\check_local.ps1 -SkipGolden     # unit tests only (no model calls)
#
# On success it writes .local-checks-passed with the commit and working-tree fingerprint it
# checked. deploy\railway\deploy_agent.ps1 refuses to publish unless that marker matches the
# tree it is about to upload. Windows PowerShell 5.1 (no && / || operators).

param(
    [switch]$WithGateway,
    [switch]$SkipGolden
)

$ErrorActionPreference = "Stop"
$copilot = $PSScriptRoot
$repo = Split-Path $copilot -Parent
$python = Join-Path $copilot ".venv\Scripts\python.exe"
$marker = Join-Path $copilot ".local-checks-passed"

function Step($name, $block) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $name" -ForegroundColor Red
        if (Test-Path $marker) { Remove-Item $marker }
        exit 1
    }
}

Set-Location $copilot
if (Test-Path $marker) { Remove-Item $marker }

Step "unit and service tests" { & $python -m pytest -q }

# Week 2 gate: 50 recorded cases through the real code, no model, no key. Always runs.
Step "Week 2 eval gate (stage2, deterministic)" { & $python -m evals.stage2.gate }

# One class of UI bug no other layer can see: an element hidden while a Bootstrap display
# utility keeps it on screen. Static, no browser.
Step "UI guard (hidden vs display utilities)" { & $python -m evals.ui_guard }

if (-not $SkipGolden) {
    Step "golden gate (stage1, live model)" { & $python -m evals.run_evals --stage stage1 --suite golden --pace 8 }
}

if ($WithGateway) {
    Set-Location (Join-Path $repo "usecases")
    if (-not $env:OPENEMR_BASE_URL) { $env:OPENEMR_BASE_URL = "https://localhost:9300" }
    if (-not $env:OE_PASS) { $env:OE_PASS = "pass" }
    $env:MSYS_NO_PATHCONV = "1"
    Step "live gateway tests against the local stack" { & (Join-Path $repo "usecases\.venv\Scripts\python.exe") -m pytest test_uc_copilot.py -q }
    Set-Location $copilot
}

# Fingerprint: the commit plus a hash of the uncommitted diff, so the deploy script can tell
# whether what it is about to upload is what was checked.
Set-Location $repo
$head = (git rev-parse HEAD).Trim()
$diff = (git diff HEAD -- copilot Dockerfile.copilot | Out-String)
$sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($diff))).Replace("-", "").ToLower()
$golden = if ($SkipGolden) { "skipped" } else { "passed" }
$gateway = if ($WithGateway) { "passed" } else { "skipped" }
@"
head=$head
diff_sha256=$sha
golden=$golden
gateway=$gateway
checked_at=$(Get-Date -Format "yyyy-MM-ddTHH:mm:ssK")
"@ | Out-File -Encoding ascii $marker

Write-Host ""
Write-Host "All local checks passed. Marker written: $marker" -ForegroundColor Green
Write-Host "  head=$head  golden=$golden  gateway=$gateway"
