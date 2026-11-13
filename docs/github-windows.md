# Update the existing GitHub repository from Windows

Run these steps in the extracted MeshLens project folder. The destination is
`https://github.com/kumarwaibhav/MeshLens`. Keep your current `.git` folder and repository
history. Commit identity and the GitHub account used to push are separate checks.

## 0. Prepare a fresh source ZIP if needed

Start PowerShell inside the extracted MeshLens folder containing `package.json`. A source
ZIP may omit Git history. This block keeps a folder that already has `.git`; otherwise it
clones the existing repository into a new folder and copies the delivered source into it.
It leaves your extracted source intact.

```powershell
Get-Item .\package.json -ErrorAction Stop
if (-not (Test-Path .\.git)) {
    $meshLensSource = (Get-Location).Path
    $meshLensRepo = Join-Path $env:USERPROFILE ("MeshLens-GitHub-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    git clone https://github.com/kumarwaibhav/MeshLens.git "$meshLensRepo"
    if ($LASTEXITCODE -ne 0) { throw "Git clone failed. Keep the source folder and resolve the error before continuing." }
    Get-ChildItem -LiteralPath $meshLensSource -Force -ErrorAction Stop | Where-Object {
        $_.Name -notin @('.git', 'node_modules', 'dist', 'tmp', 'inspection-output', '__pycache__', '.pytest_cache', '.ruff_cache') -and
        $_.Name -notlike '.venv*' -and $_.Name -notlike '.env*'
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $meshLensRepo -Recurse -Force -ErrorAction Stop
    }
    Set-Location -LiteralPath $meshLensRepo -ErrorAction Stop
}
Get-Location
```

Continue in the folder printed by this block. The clone preserves existing repository
history; copying updates does not delete older files. Review the staged diff for any intended
removals before committing.

## 1. Check the folder and account

```powershell
Get-Item .\README.md, .\package.json, .\artifacts\model.onnx
git status -sb
git branch --show-current
git remote -v
gh auth status --hostname github.com
$meshLensLogin = gh api user --jq ".login"
if ($LASTEXITCODE -ne 0 -or $meshLensLogin -ne "kumarwaibhav") {
    throw "Authenticate as kumarwaibhav before committing or pushing this project."
}
$meshLensLogin
```

The branch should be `main`,
the remote should belong to `kumarwaibhav/MeshLens`, and the authenticated login should
be `kumarwaibhav`. If authentication is missing, complete this once and repeat the login check:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
gh api user --jq ".login"
```

Set the identity for new commits in this repository:

```powershell
git config --local user.name "Kumar Waibhav Akshat"
git config --local user.email "130293310+kumarwaibhav@users.noreply.github.com"
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

Both identities should start with the configured name and noreply address. This changes
future commits. Existing commits and third-party dataset credits keep their recorded attribution.

## 2. Check the update and run the app

```powershell
git fetch origin
git status -sb
git --no-pager log -3 --oneline
git diff --check
npm.cmd ci
npm.cmd test
npm.cmd run build
```

Stop if a check fails. If `main` is behind or has diverged from `origin/main`, inspect and
integrate those changes before publishing. Preserve local edits before changing branches.

Start the verified build:

```powershell
npm.cmd run serve
```

Open the printed local URL, try a gallery image, upload a supported image, review the
decision and evidence, and test history/export. Press `Ctrl+C` to return to the terminal.
If port 4173 is already used, choose an available port without stopping another process:

```powershell
node --input-type=module -e "import {startServer} from './scripts/serve_web.mjs'; const server = await startServer({port:0}); console.log('http://127.0.0.1:' + server.address().port)"
```

## 3. Review and push

```powershell
git add --all
git --no-pager diff --cached --stat
git --no-pager diff --cached --name-only
git diff --cached --check
git ls-files node_modules .venv .venv-dev .venv-inspection data/cache tmp inspection-output
```

The last command should print nothing. Review staged files for credentials and unrelated
work before committing. The trained assets, licensed examples, reports and the complete
401-file `data/raw/grid/` acquisition are intentionally tracked. A `data/raw/` ignore rule
only covers untracked files. Retain the data license and notices when redistributing them.

```powershell
git commit -m "Improve MeshLens detection and inspection workflow"
git --no-pager log -1 --format="Author: %an <%ae>%nCommitter: %cn <%ce>"
git push -u origin main
git status -sb
```

If there are no staged changes, skip the commit. A rejected push needs inspection of the
remote changes. Keep the normal push and resolve the history instead of force-pushing.
Open the newest GitHub Actions run and any connected Vercel deployment. A successful push
alone does not verify the live application. Follow the [deployment smoke checks](deployment.md).

## Preserve frozen artifact bytes

Frozen CSV digests include their exact line endings. `.gitattributes` marks CSV files
`-text` so Git preserves these bytes on Windows and Linux. Keep that rule, and retain all
recorded checksums. Regenerate a release through its documented workflow when a real artifact
changes; editing expected hashes to pass a failed check removes the integrity evidence.

For Python development, dataset verification and independent field checks, use the
[workflow guide](RUNBOOK.md). The static build needs Node.js and shipped artifacts;
it does not train a model or install the Python development environment.
