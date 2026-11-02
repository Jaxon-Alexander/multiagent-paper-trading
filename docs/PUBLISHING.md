# Publish the project to GitHub

The project source is prepared as a Git repository. To publish to your GitHub account, create a **new private repository** named `market-multiagent-paper-trading` at https://github.com/new. Leave the GitHub-generated README, .gitignore, and license boxes empty because they are already managed in this source tree.

From the **extracted** project folder on Windows PowerShell:

```powershell
git status
git remote add origin https://github.com/YOUR_USERNAME/market-multiagent-paper-trading.git
git push -u origin main
```

If your ZIP was extracted without `.git`, initialize locally first:

```powershell
git init -b main
git add .
git commit -m "Initial multi-agent paper-trading foundation"
git remote add origin https://github.com/YOUR_USERNAME/market-multiagent-paper-trading.git
git push -u origin main
```

Use GitHub authentication through your chosen Git Credential Manager / SSH agent. **Never embed an access token in a remote URL or committed file.**

The initial scaffold commit is attributed to the generic `Project Scaffold` author. If you want it attributed to your own GitHub identity **before the first push**, configure Git locally and amend it:

```powershell
git config user.name "YOUR NAME"
git config user.email "YOUR_GITHUB_EMAIL"
git commit --amend --reset-author --no-edit
```

You only need to do this once. Do not amend a published commit that your teammate has already based work on.

After publishing, invite your teammate in the repository's **Settings → Collaborators**. Ask them to work on `feature/sentiment-agent` and open a PR to `main`, using [`TEAMMATE_GUIDE.md`](TEAMMATE_GUIDE.md).

To confirm secrets are excluded before pushing:

```powershell
git status --short
git ls-files | Select-String -Pattern '(^|/)(\.env$|\.venv/|traces/|logs/)'   # Should be empty
```

For a later release, tag the initial prototype:

```powershell
git tag v0.1.0
git push origin v0.1.0
```
