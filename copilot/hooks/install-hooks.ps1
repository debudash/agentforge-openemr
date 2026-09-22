# Install the pre-push hook into this clone. Run once per clone:
#   cd copilot; .\hooks\install-hooks.ps1
$repo = (git rev-parse --show-toplevel).Trim()
$src = Join-Path $PSScriptRoot "pre-push"
$dst = Join-Path $repo ".git\hooks\pre-push"
# Copy byte for byte: the hook is a sh script and must keep LF line endings.
[System.IO.File]::WriteAllBytes($dst, [System.IO.File]::ReadAllBytes($src))
Write-Host "installed $dst"
Write-Host "every push now runs the unit tests and the Week 2 eval gate; bypass with: git push --no-verify"
