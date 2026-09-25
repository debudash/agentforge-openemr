# Preflight the co-pilot module on the OpenEMR that Railway is actually running.
#
#   .\deploy\railway\preflight_module.ps1
#
# Run it after every OpenEMR deploy. It asks the live target -- as the web server user -- whether
# every OpenEMR class and method the module calls exists, whether the module's own classes load
# and answer, whether its configuration is complete, and whether the folders it writes to are
# writable. It exits non-zero on any failure.
#
# Why it exists: until 2026-09-25 Railway ran the stock 8.0.0 image while this repository is
# 8.2.0-dev, so `PatientSessionUtil::getPid()` existed here and not there, both module tabs
# returned 500 with an empty body, and document generation died on a read-only web root. Nothing
# in the repository could catch it, because the repository was the other version.
# module_preflight.php asks the target instead.
#
# The module now ships inside the OpenEMR image (deploy/railway/build_openemr_image.sh), so there
# is nothing to copy: until 2026-09-25 this script also tarred the module onto the sites volume.
#
# Windows PowerShell 5.1 (no && / || operators).

param(
    [string]$Service = "openemr-v82",
    [string]$Environment = "v82",
    [string]$Site = "default"
)

$ErrorActionPreference = "Stop"

# The railway CLI prints "Using SSH key from file ..." on stderr. Under ErrorActionPreference
# Stop, PowerShell 5.1 wraps a native command's stderr in a NativeCommandError and kills the
# script even when the command succeeded, so native calls run with Continue and are judged on
# their exit code -- the only thing here that means anything.
function Invoke-Native {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command } finally { $ErrorActionPreference = $previous }
}

# Run a shell script on the service.
#
# The script goes as a FILE redirected by cmd, never through a PowerShell pipe. Piping into the
# railway CLI puts a UTF-8 byte-order mark at the front of the stream -- the CLI is an npm
# PowerShell shim, so $OutputEncoding does not reach it -- and `sh` then reads the BOM as part of
# the first word and reports "cat: not found" for a line that plainly says cat. Line endings are
# forced to LF for the same class of reason: sh chokes on CRLF.
function Invoke-RemoteShell {
    param([string]$Service, [string]$ScriptText)
    $file = Join-Path ([System.IO.Path]::GetTempPath()) ("cpa-remote-" + [Guid]::NewGuid().ToString("N") + ".sh")
    $lf = $ScriptText -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($file, $lf, (New-Object System.Text.UTF8Encoding $false))
    try {
        Invoke-Native { cmd /c "railway ssh --service $Service --environment $Environment sh < ""$file""" }
    } finally {
        Remove-Item -Force $file -ErrorAction SilentlyContinue
    }
}

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$module = Join-Path $repo "interface\modules\custom_modules\oe-module-copilot-agent"

if (-not (Test-Path $module)) { Write-Host "Module not found at $module" -ForegroundColor Red; exit 1 }

# -- 1. what the module asks of OpenEMR ---------------------------------------------------------
# Imported OpenEMR classes, static calls on them, and methods called on freshly-constructed
# services. Deliberately simple: it reads what the module actually writes. Anything the regexes
# miss is still covered by the preflight loading the module's own classes and calling into them.
Write-Host "Reading the module's OpenEMR dependencies..." -ForegroundColor Cyan
$deps = New-Object System.Collections.Generic.HashSet[string]

foreach ($file in (Get-ChildItem -Path $module -Filter *.php -Recurse)) {
    $text = Get-Content $file.FullName -Raw

    # Methods this file guards with method_exists(...) -- both the ::class form and the instance
    # form. A guard is the module saying it copes without the method, so the dependency is
    # optional and its absence must not block a ship. Both live guards exist for real reasons:
    # PatientSessionUtil::getPid() is missing on 8.0.0, OEGlobalsBag::getKernel() on the stable
    # image. Without this the preflight reports handled cases as failures.
    $guarded = New-Object System.Collections.Generic.HashSet[string]
    foreach ($g in [regex]::Matches($text, "method_exists\s*\([^,]+,\s*'([A-Za-z0-9_]+)'\s*\)")) {
        [void]$guarded.Add($g.Groups[1].Value)
    }

    foreach ($m in [regex]::Matches($text, '(?m)^use\s+(OpenEMR\\[A-Za-z0-9_\\]+)\s*;')) {
        $class = $m.Groups[1].Value
        if ($class -notlike 'OpenEMR\Modules\CopilotAgent\*') { [void]$deps.Add($class) }
    }
    foreach ($m in [regex]::Matches($text, 'new\s+([A-Za-z0-9_]+Service)\s*\(\s*\)\s*\)?\s*->\s*([A-Za-z0-9_]+)\s*\(')) {
        $mark = ""
        if ($guarded.Contains($m.Groups[2].Value)) { $mark = "?" }
        [void]$deps.Add($mark + "OpenEMR\Services\" + $m.Groups[1].Value + "::" + $m.Groups[2].Value)
    }
    foreach ($m in [regex]::Matches($text, '(?<![\w\\$])([A-Z][A-Za-z0-9_]+)::([a-zA-Z0-9_]+)\s*\(')) {
        $short = $m.Groups[1].Value
        $import = [regex]::Match($text, "(?m)^use\s+(OpenEMR\\[A-Za-z0-9_\\]*\\$short)\s*;")
        if ($import.Success -and $import.Groups[1].Value -notlike 'OpenEMR\Modules\CopilotAgent\*') {
            $mark = ""
            if ($guarded.Contains($m.Groups[2].Value)) { $mark = "?" }
            [void]$deps.Add($mark + $import.Groups[1].Value + "::" + $m.Groups[2].Value)
        }
    }
    foreach ($m in [regex]::Matches($text, '\\Document::([a-zA-Z0-9_]+)\s*\(')) {
        [void]$deps.Add("Document::" + $m.Groups[1].Value)
    }
}

Write-Host ("  " + $deps.Count + " dependencies to verify on the target")

# Both payloads travel base64-encoded inside the script, so no quoting, escaping or encoding of
# PHP source has to survive two shells.
$preflightB64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes((Join-Path $PSScriptRoot "module_preflight.php")))
$manifestB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes((($deps | Sort-Object) -join "`n")))

# `railway ssh` lands as root, and root can write places the web server cannot. Run the checks as
# the web server user instead, or they answer a question nobody asked: the first version of this
# reported the web root writable and CREATED it -- root could -- which would have left a
# root-owned directory that the module resolves to and then cannot write into. A permission check
# that runs as the wrong user is worse than no check, because it passes.
function New-PreflightScript {
    param([string]$Phase, [string]$AsUser = "apache")
    return @"
echo '$preflightB64' | base64 -d > /tmp/cpa_preflight.php
echo '$manifestB64' | base64 -d > /tmp/cpa_manifest.txt
chmod 644 /tmp/cpa_preflight.php /tmp/cpa_manifest.txt
su -s /bin/sh $AsUser -c "php /tmp/cpa_preflight.php $Site $Phase < /tmp/cpa_manifest.txt"
rc=`$?
rm -f /tmp/cpa_preflight.php /tmp/cpa_manifest.txt
exit `$rc
"@
}

# -- 2. preflight on the deploy target ----------------------------------------------------------
# "post" is the strict phase: the module is installed (it is in the image), so its own classes,
# configuration and writable paths must all check out, not only the platform APIs.
Write-Host ""
Write-Host "Preflight against '$Service' in '$Environment' (the deployed OpenEMR, not this checkout)..." -ForegroundColor Cyan
Invoke-RemoteShell -Service $Service -ScriptText (New-PreflightScript -Phase "post")
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Preflight failed. The module will not work on this OpenEMR as deployed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Preflight passed." -ForegroundColor Green
Write-Host "Open a patient, then the Co-Pilot and Demo Data tabs. A blank tab is a 500: check" -ForegroundColor Yellow
Write-Host "  railway logs --service $Service --environment $Environment" -ForegroundColor Yellow
