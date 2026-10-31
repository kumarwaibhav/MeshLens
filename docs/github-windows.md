# Publish from Windows PowerShell

Use the extracted MeshLens folder, not the ZIP itself. Verify commit identity separately from
the GitHub account that authenticates the push.
For Node application setup and the Linux/WSL Python workflow, first use the
[workflow guide](RUNBOOK.md). These commands publish source; they do not install ML tools.

```powershell
Set-Location "C:\path\to\MeshLens"
Get-Item .\package.json
git init -b main
git config --local user.name "Kumar Waibhav Akshat"
git config --local user.email "kwa.waibhav@gmail.com"
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT

gh auth login --hostname github.com --git-protocol https --web --scopes workflow
gh auth setup-git --hostname github.com
gh api user --jq ".login"
```

Both Git identities should begin `Kumar Waibhav Akshat <kwa.waibhav@gmail.com>`. Confirm the
printed GitHub username is your intended account, and verify the email on that profile.

```powershell
git add .
git ls-files data/raw data/cache node_modules .venv .venv-dev tmp
git --no-pager diff --cached --stat
```

The exclusion check should print nothing. Trained artifacts, small licensed examples, code,
reports and the executed notebook are intentional tracked deliverables.

```powershell
git commit -m "Build MeshLens autoencoder inspection project"
git branch -M main
git --no-pager log -1 --format="Author: %an <%ae>%nCommitter: %cn <%ce>"
$meshLensUser = gh api user --jq ".login"
gh repo create "$meshLensUser/meshlens" --public --source=. --remote=origin
git remote -v
git push -u origin main
```

If origin already exists, inspect its destination and skip repository creation. Do not replace
an unknown remote or force-push to resolve unexpected divergence. Watch the newest Actions
run; quick checks must use tracked model/examples without assuming raw dataset files exist.
