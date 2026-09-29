# Gated publish of the Clinical Co-Pilot agent service to Railway.
#
#   .\deploy\railway\deploy_agent.ps1
#
# Refuses unless copilot\check_local.ps1 has passed on exactly the tree about to be uploaded
# (same commit, same uncommitted diff), then asks you to type DEPLOY. Only then does it run
# `railway up`. Nothing else in this repository publishes to Railway.
# Windows PowerShell 5.1 (no && / || operators).

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$marker = Join-Path $repo "copilot\.local-checks-passed"

Set-Location $repo

if (-not (Test-Path $marker)) {
    Write-Host "No local check marker. Run copilot\check_local.ps1 first." -ForegroundColor Red
    exit 1
}

$facts = @{}
Get-Content $marker | ForEach-Object { $k, $v = $_ -split "=", 2; $facts[$k] = $v }

$head = (git rev-parse HEAD).Trim()
$diff = (git diff HEAD -- copilot Dockerfile.copilot | Out-String)
$sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($diff))).Replace("-", "").ToLower()

if ($facts["head"] -ne $head -or $facts["diff_sha256"] -ne $sha) {
    Write-Host "The local checks passed on a different tree than the one you are about to upload." -ForegroundColor Red
    Write-Host "  checked: head=$($facts['head'])  diff=$($facts['diff_sha256'].Substring(0,12))"
    Write-Host "  now:     head=$head  diff=$($sha.Substring(0,12))"
    Write-Host "Re-run copilot\check_local.ps1."
    exit 1
}
if ($facts["golden"] -ne "passed") {
    Write-Host "The golden gate was skipped in the last local check. Re-run without -SkipGolden." -ForegroundColor Red
    exit 1
}

Write-Host "Local checks passed at $($facts['checked_at']) on head $head (golden=$($facts['golden']), gateway=$($facts['gateway']))." -ForegroundColor Green
Write-Host "Target: Railway project openemr-agent, environment v82, service copilot-agent-v82 (built from Dockerfile.copilot)."
Write-Host ""
$answer = Read-Host "Type DEPLOY to publish the agent to Railway, anything else to abort"
if ($answer -cne "DEPLOY") {
    Write-Host "Aborted. Nothing was published."
    exit 1
}

railway up --service copilot-agent-v82 --environment v82 -c
if ($LASTEXITCODE -ne 0) {
    Write-Host "railway up failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Checking readiness over the private network..."
railway ssh --service openemr-v82 --environment v82 sh -c "curl -s -m 20 http://copilot-agent-v82.railway.internal:8600/readyz"
Write-Host ""
Write-Host "Done. Consider deleting the marker so the next publish needs a fresh check:" -ForegroundColor Yellow
Write-Host "  Remove-Item copilot\.local-checks-passed"
