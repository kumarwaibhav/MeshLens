param([string]$ProjectPath = (Get-Location).Path, [switch]$Push)
$ErrorActionPreference = 'Stop'
function Run-Git {
    & git @args
    if ($LASTEXITCODE -ne 0) { throw "Git failed with exit code $LASTEXITCODE. Your local files were preserved." }
}
function Check-Account {
    $account = & gh api user --jq '.login'
    if ($LASTEXITCODE -ne 0 -or "$account".Trim() -ne 'kumarwaibhav') {
        throw 'Sign in as kumarwaibhav: gh auth login --hostname github.com --git-protocol https --web'
    }
}
$manifestPath = Join-Path $PSScriptRoot 'update-manifest.json'
$patchPath = Join-Path $PSScriptRoot 'meshlens-update.patch'
if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath $patchPath)) {
    throw 'Run this script from the extracted MeshLens-Accuracy-Update folder, beside its manifest and patch.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $patchPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.patch_sha256) {
    throw 'Patch checksum mismatch. Extract a fresh copy of the update.'
}
Push-Location -LiteralPath $ProjectPath
try {
    if (-not (Test-Path -LiteralPath 'package.json') -or -not (Test-Path -LiteralPath '.git')) { throw 'Choose your existing MeshLens repository folder.' }
    $root = "$(Run-Git rev-parse --show-toplevel)".Trim()
    if ([IO.Path]::GetFullPath($root) -ne [IO.Path]::GetFullPath((Get-Location).Path)) { throw 'Run from the top-level MeshLens folder.' }
    $origin = "$(Run-Git remote get-url origin)".Trim().TrimEnd('/')
    if ($origin -notin @('https://github.com/kumarwaibhav/MeshLens.git', 'https://github.com/kumarwaibhav/MeshLens')) { throw 'Origin must be https://github.com/kumarwaibhav/MeshLens.git.' }
    if ("$(Run-Git branch --show-current)".Trim() -ne 'main') { throw 'Switch to your clean main branch first.' }
    if (Run-Git status --porcelain) { throw 'Commit or safely stash your local changes before applying the update.' }
    if ($Push) { Check-Account }
    Run-Git fetch origin main
    if ("$(Run-Git rev-parse HEAD)".Trim() -ne $manifest.base_commit -or "$(Run-Git rev-parse origin/main)".Trim() -ne $manifest.base_commit) {
        throw "This update targets $($manifest.base_commit). Your history differs; no project files were changed. Do not reset or force-push."
    }
    Run-Git apply --check --binary $patchPath
    Run-Git apply --binary --index $patchPath
    Run-Git config --local user.name 'Kumar Waibhav Akshat'
    Run-Git config --local user.email '130293310+kumarwaibhav@users.noreply.github.com'
    Run-Git diff --cached --check
    Run-Git diff --cached --stat
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. The update remains staged locally; nothing was pushed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed. The update remains staged locally; nothing was pushed.' }
    Run-Git commit -m 'Improve MeshLens detector and complete verified inspection workflow'
    if ($Push) {
        Check-Account
        Run-Git -c 'credential.helper=' -c 'credential.helper=!gh auth git-credential' push origin main
        Write-Host 'Pushed to kumarwaibhav/MeshLens using your GitHub CLI account.'
    } else {
        Write-Host 'Committed locally. To push using your authenticated GitHub CLI account:'
        Write-Host 'git -c credential.helper= -c "credential.helper=!gh auth git-credential" push origin main'
    }
    Write-Host 'To preview: npm.cmd run serve. See docs/deployment.md if port 4173 is busy.'
    Write-Host 'The frozen result is 56/57 defects and 4/21 clean false alarms. Independent field qualification is still required.'
    Run-Git status -sb
} finally { Pop-Location }
