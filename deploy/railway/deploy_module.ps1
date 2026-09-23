# Ship the OpenEMR co-pilot module to the Railway sites volume, with a preflight.
#
#   .\deploy\railway\deploy_module.ps1              # preflight, ship, verify
#   .\deploy\railway\deploy_module.ps1 -CheckOnly   # preflight only, ship nothing
#
# The module is in no image: it lives on the persistent volume at sites/<site>/copilot-module and
# is symlinked into custom_modules, so it survives a redeploy of OpenEMR itself. Shipping it is a
# tar over `railway ssh`.
#
# Two things this does that hand-running did not, each written after a live failure:
#
#   1. Preflight. The deployed OpenEMR is NOT the one this repository runs -- Railway serves the
#      stable image's own code (8.0.0); the dev stack bind-mounts this checkout (8.2.0-dev). So
#      `PatientSessionUtil::getPid()` existed here and not there, both module tabs returned 500
#      with an empty body, and the clinician saw a blank panel with no error. Separately, the
#      image's web root is read-only, so document generation died on mkdir. Nothing in this
#      repository could catch either: the repository is the other version. module_preflight.php
#      asks the target -- including by calling the module's own code on it.
#
#   2. A check before the swap. Installing is one `mv`, so a truncated transfer would replace the
#      live module with an empty directory, and nothing would notice until the site was broken.
#
# Windows PowerShell 5.1 (no && / || operators).

param(
    [switch]$CheckOnly,
    [string]$Service = "openemr",
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
        Invoke-Native { cmd /c "railway ssh --service $Service sh < ""$file""" }
    } finally {
        Remove-Item -Force $file -ErrorAction SilentlyContinue
    }
}

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$module = Join-Path $repo "interface\modules\custom_modules\oe-module-copilot-agent"
$remoteSite = "/var/www/localhost/htdocs/openemr/sites/$Site"

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
Write-Host ""
Write-Host "Preflight against '$Service' (the deployed OpenEMR, not this checkout)..." -ForegroundColor Cyan
Invoke-RemoteShell -Service $Service -ScriptText (New-PreflightScript -Phase "pre")
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Preflight failed. The module would not work on this OpenEMR; nothing was shipped." -ForegroundColor Red
    exit 1
}

if ($CheckOnly) {
    Write-Host ""
    Write-Host "Preflight only; nothing was shipped." -ForegroundColor Yellow
    exit 0
}

# -- 3. ship ------------------------------------------------------------------------------------
Write-Host ""
Write-Host "Shipping the module..." -ForegroundColor Cyan
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("cpa-module-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null
$tar = Join-Path $staging "module.tar"

Push-Location (Join-Path $repo "interface\modules\custom_modules")
Invoke-Native { tar -cf $tar --exclude=__pycache__ oe-module-copilot-agent }
Pop-Location
if ($LASTEXITCODE -ne 0) { Write-Host "tar failed" -ForegroundColor Red; exit 1 }

$moduleB64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($tar))
Write-Host ("  " + [math]::Round((Get-Item $tar).Length / 1KB) + " KB")
Remove-Item -Recurse -Force $staging

# Unpack beside the live copy and swap only once the files that matter are present.
$installScript = @"
set -e
cd $remoteSite
echo '$moduleB64' | base64 -d > /tmp/cpa_module.tar
rm -rf copilot-module.new
mkdir copilot-module.new
tar -C copilot-module.new --strip-components=1 -xf /tmp/cpa_module.tar
for f in openemr.bootstrap.php moduleConfig.php public/api.php public/patient.php public/demo.php public/index.php src/ActivePatient.php src/DemoDocuments.php src/DocumentWriter.php src/ChartReader.php; do
  test -f "copilot-module.new/`$f" || { echo "MISSING after unpack: `$f"; exit 1; }
done
echo "  unpacked `$(find copilot-module.new -type f | wc -l) files, all expected present"
rm -rf copilot-module.old
mv copilot-module copilot-module.old
mv copilot-module.new copilot-module
chown -R apache:apache copilot-module
rm -f /tmp/cpa_module.tar
echo "  installed"
"@

Invoke-RemoteShell -Service $Service -ScriptText $installScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "Install failed. The previous module is still live, or in copilot-module.old." -ForegroundColor Red
    exit 1
}

# -- 4. preflight again, against what is now installed -------------------------------------------
Write-Host ""
Write-Host "Verifying the installed module..." -ForegroundColor Cyan
Invoke-RemoteShell -Service $Service -ScriptText (New-PreflightScript -Phase "post")
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Installed, but preflight now fails. Roll back with:" -ForegroundColor Red
    Write-Host "  railway ssh --service $Service sh -c 'cd $remoteSite && rm -rf copilot-module && mv copilot-module.old copilot-module'"
    exit 1
}

Write-Host ""
Write-Host "Module shipped and verified." -ForegroundColor Green
Write-Host "Open a patient, then the Co-Pilot and Demo Data tabs. A blank tab is a 500: check" -ForegroundColor Yellow
Write-Host "  railway logs --service $Service" -ForegroundColor Yellow
