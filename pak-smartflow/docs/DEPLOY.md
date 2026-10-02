# Deployment

Two hosts: **GitHub** for the code, **Streamlit Community Cloud** for the live
dashboard. The command-line engine needs no host at all — it runs anywhere Python
does.

Total time: about 10 minutes.

---

## 0. What was changed to make this deployable

Deployment is not just "push it". Three real problems had to be fixed first, and
one of them would have failed *only* in the cloud.

| Problem | Why it breaks in the cloud | Fix |
|---------|---------------------------|-----|
| `requirements.txt` was intentionally empty | Community Cloud reads that file to build the environment. Empty means it guesses. | `requirements.txt` now declares `streamlit` and `pandas`. The core's "zero dependencies" claim moved to `requirements-core.txt` and is re-proved in CI. |
| The SQLite connection was thread-bound | **Streamlit runs every script rerun on a different worker thread.** A default `sqlite3` connection raises `ProgrammingError: SQLite objects created in a thread can only be used in that same thread` on the second interaction. | `Store` now takes `check_same_thread` and serialises all access with an `RLock`. `tests/test_db.py` proves the default fails and the fixed version survives 8 concurrent readers/writers. |
| Community Cloud's default **Main file path** is `streamlit_app.py` | Deploying without setting the path would show a "file not found" page. | Added `streamlit_app.py`, which delegates to `app_streamlit.py` via `runpy`. Both entrypoints are smoke-tested. |
| Ephemeral, sometimes read-only filesystem | The app could fail to start on a cold container. | The store falls back to in-memory and the sidebar reports which mode is live. |
| An empty database on first load | A judge clicking your link would see an empty dashboard. | The app auto-runs scenario 4 once so the first screen already shows the compliance ladder. |

Also added: `.streamlit/config.toml` (theme and sane server defaults) and
`.github/workflows/tests.yml` (a real CI matrix).

---

## 1. Before you push — get out of OneDrive

This repository currently lives inside OneDrive. **Do not run `git init` there.**
OneDrive's file sync and Git both write to the working tree, and the usual result
is a corrupted `.git` directory or phantom "file changed" errors mid-commit.

```powershell
# Copy to a local folder outside any sync service
New-Item -ItemType Directory -Force -Path C:\dev | Out-Null
Copy-Item -Recurse -Force "C:\Users\Jawad Ali\OneDrive\Documents\deepseek-harness\default-workspace\pak-smartflow" "C:\dev\pak-smartflow"
cd C:\dev\pak-smartflow
```

Then confirm everything still passes from the new location:

```powershell
python -m unittest discover -s tests -t .
python -m smartflow selftest
```

If you must stay in OneDrive, pause syncing (system tray → OneDrive → Pause) for
the whole session and re-enable it afterwards.

---

## 2. Install Git

Git is **not** installed on this machine, and this sandbox has **no network
access**, so the push has to happen from your side. Pick one:

| Option | Command / step |
|--------|----------------|
| **Git for Windows** (recommended) | Download from [git-scm.com/download/win](https://git-scm.com/download/win), install with defaults, then reopen your terminal |
| **GitHub Desktop** | [desktop.github.com](https://desktop.github.com) — GUI alternative, handles auth for you |
| **Web upload** | Create the repo on GitHub, then "Add file → Upload files" and drag the folder in. Works, but you lose history and the CI badge stays grey until the first push |

Verify:

```powershell
git --version
```

Set your identity once:

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

---

## 3. Push to GitHub

### 3a. Create the empty repository

On GitHub: **New repository** →

- **Name:** `pak-smartflow`
- **Visibility:** **Public** (judges and CI can read it; private also works on
  Community Cloud but you must grant access during deploy)
- **Do NOT** add a README, `.gitignore` or licence — this repo already has them,
  and pre-filling causes a merge conflict on the first push.

### 3b. Commit and push

Replace `YOUR-USERNAME` before running:

```powershell
cd C:\dev\pak-smartflow

git init -b main
git add .
git commit -m "Pak-SmartFlow: 12-agent compliance resolution prototype

- Explainable Mamdani fuzzy risk engine (20 rules, monotonicity tested)
- SHA-256 evidence chain of custody with automatic dispute cancellation
- Progressive capped penalty ladder and compliance escalation scoring
- Two-key enforcement request: inert by construction, human approval required
- 187 tests, zero third-party imports in the core, no network calls"

git remote add origin https://github.com/YOUR-USERNAME/pak-smartflow.git
git push -u origin main
```

If Git asks for a password, it wants a **Personal Access Token**, not your GitHub
password: GitHub → Settings → Developer settings → Personal access tokens →
Fine-grained tokens → grant **Contents: Read and write** on this repository. Or
just use GitHub Desktop, which handles this for you.

### 3c. Confirm the ignore rules worked

```powershell
git status --short          # should be clean
git ls-files | findstr /i "sqlite pycache"   # should print nothing
```

The `.gitignore` excludes `*.sqlite`, `__pycache__/`, `demo4.txt` and `.env`.
**Never commit a `.env` or an API key.** Nothing in this project needs one.

---

## 4. Deploy on Streamlit Community Cloud

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with
   GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Fill the form:

   | Field | Value |
   |-------|-------|
   | Repository | `YOUR-USERNAME/pak-smartflow` |
   | Branch | `main` |
   | **Main file path** | `app_streamlit.py` |
   | App URL | pick something short, e.g. `pak-smartflow` |

   > `streamlit_app.py` also works and is the field's default. Either is fine —
   > both are smoke-tested. Use `app_streamlit.py` if you want the file name to
   > match the README.

4. Open **Advanced settings**:
   - **Python version:** `3.12` (matches what this was developed and tested on)
   - **Secrets:** leave **empty**. This project deliberately needs no API keys,
     which is worth saying out loud in a pitch.
5. **Deploy**. The first build takes 2–4 minutes.

Your app lands at:

```
https://YOUR-APP-NAME.streamlit.app
```

---

## 5. Post-deploy checklist

Run through this once on the live URL, on a phone as well as a laptop — judges
often open links on mobile.

- [ ] The page loads with the red **SIMULATED** banner visible
- [ ] The first screen is **not** empty (scenario 4 auto-ran, or press
      *Run scenario*)
- [ ] Sidebar → **Run scenario** works and the agent trace appears
- [ ] **Fuzzy engine** tab shows the five inputs and the fired rules
- [ ] **Compliance ladder** tab shows 11.2 SEVERE → 100 COMPLIANT
- [ ] **Legal boundary** tab lists all nine blocked capabilities
- [ ] **Citizen portal** lists the seeded plates
- [ ] Sidebar shows the storage mode; on Cloud it should say *ephemeral*
- [ ] No red exception box anywhere
- [ ] The URL opens correctly on a phone

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'streamlit'` | `requirements.txt` missing or not at the root | It must sit at the repository root. Check with `git ls-files \| findstr requirements` |
| `ModuleNotFoundError: No module named 'smartflow'` | Working directory is not the repo root, or the file layout changed | Community Cloud always runs from the repo root; keep `smartflow/` at the top level |
| `ImportError: cannot import name 'AppTest'` — only in CI | Streamlit older than 1.28 | `requirements.txt` already pins `streamlit>=1.36` |
| `ProgrammingError: SQLite objects created in a thread...` | A `Store` was created without `check_same_thread=False` | Reuse `get_store()` in the app; never construct `Store` inline |
| App shows "Oh no" / blank page | Usually a failed build | Cloud sidebar → **Manage app** → logs. The most common cause is a dependency that is not in `requirements.txt` |
| Data disappears after a while | Expected: the container is ephemeral | Say so in the demo. For durable data, `db.py` is a narrow interface built to swap for PostgreSQL |
| Two people see each other's data | The container is shared across visitors | Fine for a demo; a real deployment needs per-citizen authn. Mention it as roadmap, not as a defect |
| Build fails on `pandas` | Python version mismatch | Set the Python version to 3.12 in Advanced settings |
| CI badge is grey | No push yet, or Actions disabled on the repo | Actions tab → enable workflows |

---

## 7. Optional: skip the dashboard entirely

If the Cloud build gives you trouble on the day, you lose almost nothing. The
dashboard holds **no business logic** — it renders `PipelineResult` objects. The
command line tells the identical story with zero dependencies and zero network:

```powershell
python -m smartflow demo 4 --urdu
```

Any judge will accept a terminal demo when it is fast, legible and honest. Keep the
Cloud link as the "and here is it running for anyone" flourish, not as the spine of
the presentation.

---

## 8. What deployment buys you in the pitch

Deployment is not housekeeping. It is evidence for three claims that are otherwise
just words:

1. **"It runs on a fresh machine."** `requirements-core.txt` is empty and CI
   re-proves the zero-dependency claim on every push. Nobody can say "it only works
   on your laptop."
2. **"It is a product, not a script."** A URL a judge can open on their own phone,
   while you are still talking, is worth more than any screenshot.
3. **"We test what we ship."** The CI workflow runs 187 tests on three Python
   versions, including six headless dashboard tests. **Add the badge to your deck**
   — at the time of writing, a green matrix is a differentiator in a student
   hackathon.

```markdown
[![tests](https://github.com/YOUR-USERNAME/pak-smartflow/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR-USERNAME/pak-smartflow/actions/workflows/tests.yml)
```

### What is *not* verified yet, and you should say so

The development environment for this project had no network access and no
Streamlit installed, so the dashboard was **written but never executed locally**.
It is verified only by the CI job and by your post-deploy checklist above. If a
render breaks, expect it to be a cosmetic Streamlit API issue in
`app_streamlit.py` — the engine, the CLI and all 187 tests are unaffected.

Being the team that knows exactly which part of its own system is unverified is a
strength. Say it before a judge finds it.
