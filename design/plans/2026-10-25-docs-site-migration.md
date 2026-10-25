# Docs site: GitBook → Material for MkDocs on GitHub Pages, with versions

## Context

The docs already live in `docs/`, but GitBook publishes them, and GitBook syncs only to its own branch, `docs/gitbook-sync`.
- Edits made in GitBook's editor reach `dev` only through occasional "Docs/gitbook sync" PRs (#45, #50, #147).
- So docs can't ride along in feature PRs, and the branches drift. GitBook edits from 2026-03-13 never reached `dev`, and the May `dev` edits (#159, #160) never reached GitBook.
- There's no per-release history.

**Goal:** build the site from the repo's Markdown on every push and publish it at docs.trafficmonitor.ai for $0, with no server. Readers get a version dropdown with Dev, the latest release (the default), and each tagged release.

## Decisions

The user decided:
- **Host:** GitHub Pages, built by GitHub Actions. The repo is public, so this costs $0, and the deploy needs no webhook or server.
- **Generator:** Material for MkDocs plus mike (versions), from pinned PyPI packages. Material reaches end of life on 2027-05-05. Moving to Zensical is a follow-up, so `mkdocs.yml` stays within what Zensical can read.
- **Cutover:** before v0.8.0, through a docs-only **v0.7.1** cut from `main`. This keeps the unreleased work merging into `dev` out of it.
- **PR previews:** a strict build check plus local `mkdocs serve`. No live preview URLs.

Calls I made, for the user to check:
1. **Versions and URLs.**
   - Pushes to `dev` deploy to `/dev/` ("Dev (unreleased)").
   - Each `vX.Y.Z` tag deploys to `/vX.Y.Z/` and moves the alias `/latest/` to it. The site root redirects to `/latest/`.
   - **"Main" is the newest release, shown with the `latest` alias, not a separate build.** Fast-forward releases keep `main` equal to the newest tag. A separate main build would duplicate that entry, and Material would mark the newest release as outdated.
   - Pre-release tags (`-beta`) aren't published.
2. **Nav** moves from `docs/SUMMARY.md` to `nav:` in `mkdocs.yml`. Zensical can read that too, and the move drops SUMMARY's duplicated entries.
3. **Images** move from `docs/.gitbook/assets/` to `docs/assets/images/`, with spaces and parentheses removed from filenames. MkDocs skips folders whose names start with a dot. Images nothing references are dropped and listed in the PR.
4. **Front matter:** drop GitBook's `icon:` (its icon names don't exist in Material). Keep `description:`, and keep it visible under the title as GitBook does.
5. **Old URLs:** a root `404.html` sends any unversioned path to `/latest/<path>`, plus a small map for pages that moved. GitHub Pages has no server-side redirects, so this is a JavaScript redirect.
6. **Branch:** `hotfix/docs-site/<issue>` off `main`, which is v0.7.0. Per CONTRIBUTING.md, `hotfix` is the branch type that targets `main`.
7. **v0.7.1 bumps `tmsetup_tm_version` to `'0.7.1'`**, so the tag and the version a device reports match. This is the release's only change outside the docs.
8. No analytics at launch.
9. **Zensical compatibility is a preference, not a rule.** The outdated banner (a theme override) and the mike plugin (for canonical links to `/latest/`) stay. Zensical's mike page says the version settings and the outdated warning keep working, and the switch PR re-checks both.
10. **v0.7.1 gets a GitHub Release**, like every earlier tag, with short notes: docs moved, no software changes.

## Design

### Files

| Path | What |
|---|---|
| `mkdocs.yml` (new) | Site config, nav, theme, versions |
| `docs-site/requirements.txt` (new) | Build dependencies, all pinned: mkdocs-material 9.8.x, mkdocs 1.6.1, mike 2.2.0, plus everything they pull in |
| `docs-site/overrides/main.html` (new) | Outdated-version banner (Material's `outdated` block) and the visible description |
| `docs-site/pages-root/404.html`, `.nojekyll` (new) | Copied to the root of `gh-pages`. Redirects old URLs and works both under `glossyio.github.io/traffic-monitor/` and on the custom domain |
| `docs-site/gitbook_to_mkdocs.py` (new, temporary) | Converter, stdlib only, safe to re-run. Deleted after main is merged into dev |
| `.github/workflows/docs.yml` (new) | PR check and deploys |
| `docs/**` | Converted content. Delete `.gitbook.yaml` and `docs/SUMMARY.md` |
| `README.md` | Point docs links at `https://docs.trafficmonitor.ai/latest/…`. Fix the broken `[x]([url](…))` links on lines 37–38 |
| `docs/development/contributing.md` | Add a short "Writing docs" section: preview, nav, admonitions, images, versions |
| `.gitignore` | Add `site/` |
| `script/ansible/roles/tmsetup/vars/main.yml` | `tmsetup_tm_version: '0.7.1'` |
| `CLAUDE.md` (step 7, on `dev`) | Docs line and local checks: MkDocs instead of GitBook |

Rules: nothing goes under `utils/`, because that folder is copied to devices. Nothing except content goes under `docs/`.

### `mkdocs.yml` essentials

- **Site:** `site_url: https://docs.trafficmonitor.ai/`, `repo_url`, and `edit_uri: edit/dev/docs/`, so the edit button opens GitHub's editor on `dev`.
- **Theme:** `material` with `custom_dir: docs-site/overrides`. Features: `navigation.sections`, `navigation.indexes`, `content.action.edit`, `search.suggest`. Light and dark palettes.
- **Versions:** `extra.version: {provider: mike, default: latest, alias: true}`.
- **Plugins:** `search`, and `mike` with `canonical_version: latest`. Check that the mike plugin doesn't add a second version selector.
- **Markdown extensions:** `admonition`, `pymdownx.details`, `pymdownx.superfences`, `attr_list`, `md_in_html`, `tables`, `toc` (permalink).
- **`validation:`** `omitted_files`, `unrecognized_links` and `anchors` set to `warn`. With `--strict`, the build then fails on broken links, anchors and images, and on pages missing from the nav.

### Workflow (`.github/workflows/docs.yml`)

- **Triggers:**
  - `pull_request`, and `push` to `dev`, each limited to changes under `docs/**`, `mkdocs.yml`, `docs-site/**`, or the workflow file.
  - `push` of tags matching `v[0-9]+.[0-9]+.[0-9]+`. GitHub doesn't apply path filters to tags.
  - `workflow_dispatch` for manual runs, available only once the workflow is on `main` (from v0.7.1).
  - Nothing on `main`, because releases are tags.
- **Hardening:** top-level `permissions: contents: read`. Actions are pinned to commit SHAs. Python version pinned (3.12 or newer), with pip cache.
- **`check` job (PRs):** install the pinned requirements and run `mkdocs build --strict`. It has no write access and no secrets.
- **`deploy` job (push, tag, manual run):**
  - Setup:
    - `permissions: contents: write`.
    - `concurrency: docs-deploy` with `cancel-in-progress: false`.
    - `git fetch origin gh-pages --depth=1`, which must tolerate the branch not existing on the first run.
  - Run `mkdocs build --strict` before deploying anything.
  - Deploy by ref:
    - **`dev`** runs `mike deploy --push --title "Dev (unreleased)" dev`.
    - **A release tag** runs `mike deploy --push --title vX.Y.Z vX.Y.Z`. If it's the highest release tag, it adds `latest` with `--update-aliases`, so re-running an old tag can't move `latest` back. Then it runs `mike set-default --push latest`, which is safe to repeat.
    - **Any other ref** fails with a clear message.
  - Copy `docs-site/pages-root/*` into the `gh-pages` root and commit only if something changed. Never touch `CNAME`, which GitHub writes at cutover.
- **Known limit:** GitHub keeps only one pending run per concurrency group. A deploy dropped that way can be re-run from the Actions tab.

### Conversion: scripted, then finished by hand

**Script:**
- `{% hint style=X %}` becomes `!!! X`, with the body indented. The styles in use are info, success, warning and danger.
- "Mention" links become plain links. Their text becomes the target page's title or heading: GitBook ignored link text, so the source text is often a filename like `setup-guide.md`.
- `<figure><img><figcaption>` becomes `<figure markdown="span">![alt](path)<figcaption>…</figcaption></figure>`. MkDocs doesn't rewrite or check `src` in raw HTML, but it does both for Markdown images.
- `<picture>` with light and dark images becomes `#only-light` / `#only-dark` images.
- Image paths are rewritten and the files moved.
- Absolute `docs.trafficmonitor.ai` links become relative links.
- `icon:` is dropped.
- The script is safe to re-run, so it can convert docs that arrive later from other branches.

**By hand:**
- 3 GitBook card tables (`README.md`, `getting-started.md`) become Material grid cards.
- 4 `<div>` image pairs (deployment guide) become `<div class="grid" markdown>`.
- `<mark style>` and `<br>` stay as HTML.

### URL map: 23 live URLs from `sitemap-pages.xml`

Each path P maps to `/latest/P/`, with these exceptions:
- `/build-your-own-device-diy/recommended-hardware`: move `docs/recommended-hardware.md` into `docs/build-your-own-device-diy/` so the path survives.
- `/software-installation`: keep one copy, at `docs/software-installation.md`, where GitBook has it, and delete the nested duplicate. Map `/build-your-own-device-diy/software-installation`, which README uses, to it.
- `/sensor-payloads/events-payload`, a stale link inside the docs, maps to `/data-and-payloads/events-payload`.

## Steps

0. **User:**
   - Open an issue.
   - Confirm that GitBook's Git Sync panel shows the space in sync with `docs/gitbook-sync`.
   - Freeze editing in GitBook. GitBook keeps serving the domain until step 6.
1. Run `git fetch origin` (local refs are behind; `dev` has moved), then branch `hotfix/docs-site/<issue>` from `origin/main`. The first commit adds this design and the plan under `design/`.
2. **Reconcile GitBook content, docs files only.**
   - Do a 3-way merge per file: merge-base `5d34f8a` vs `main` vs `origin/docs/gitbook-sync`.
   - Add the GitBook-only files: 4 screenshots and `docs/software-installation.md`.
   - **Don't merge that branch itself.** It differs from `main` in 73 files outside `docs/`.
   - Expect to resolve `node-red-config.md`, `setup-guide.md` and `frigate-config.md` by hand.
3. Tooling commit: `mkdocs.yml`, `docs-site/`, the workflow, `.gitignore`.
4. Conversion, in separate commits so the mechanical diff can be reviewed on its own:
   1. Add the converter script.
   2. Commit the script's output only, which anyone can reproduce by re-running it.
   3. Hand-finish: grids, file moves, nav, README links, the contributing section, and deleting `.gitbook.yaml` and `SUMMARY.md`.
5. **Release v0.7.1 (user approves each outward step):**
   1. Bump `tmsetup_tm_version`.
   2. Open the PR into `main`. The check job runs.
   3. Fast-forward `main` with `git push origin origin/hotfix/docs-site/<issue>:main`. `main`'s ruleset requires a PR and a review, but the API reports you can always bypass it (that's how #225 merged). This is the first release done the documented fast-forward way.
   4. Tag and push `v0.7.1`, and publish a GitHub Release for it.
   5. The tag push runs the first deploy, which creates `gh-pages` with `/v0.7.1/`, `/latest/`, and the root files. A manual run can't come first: GitHub only allows one once the workflow is on `main`. If the tag doesn't start a run, start one manually on the tag.
   6. Settings → Pages → Source: deploy from branch `gh-pages`, at the root (it's "GitHub Actions" today). Smoke-test at glossyio.github.io/traffic-monitor/; readers still see GitBook.
   7. Fixes: root files (404 page) go out with any later deploy. A content fix goes to `dev`, or into a v0.7.2 if it can't wait.
6. **DNS cutover (user, in GitHub, Porkbun and GitBook):**
   1. Verify `trafficmonitor.ai` in your GitHub account's Pages settings: Porkbun TXT record `_github-pages-challenge-glossyio`. This prevents a domain takeover.
   2. A day ahead, lower the `docs` CNAME TTL from 599 to 300.
   3. Set the custom domain `docs.trafficmonitor.ai` in the repo's Pages settings.
   4. Point the Porkbun CNAME `docs` at `glossyio.github.io` (today it's `f05f5ccc4a-hosting.gitbook.io`).
   5. Once the certificate is issued, turn on Enforce HTTPS. Expect a few minutes of certificate warnings, so pick a quiet hour.
   6. In GitBook, remove the domain, disconnect Git Sync, and unpublish the space.
7. **Bring the change into dev** (steps 6 and 7 can go in either order):
   1. On the hotfix branch, merge `origin/dev` in (not the reverse). The `contributing.md` conflict from #202 is certain.
   2. Re-run the converter. Additions that PRs brought into `dev` in GitBook syntax can merge without conflicts and still be unconverted.
   3. Add any new pages to the nav.
   4. Update CLAUDE.md's docs line and local checks; CLAUDE.md is on `dev` now.
   5. Open a PR into `dev` and merge it with **"Create a merge commit"**. Squash or rebase would leave `main` with commits `dev` lacks, which breaks the next fast-forward release. The `dev` push deploys `/dev/`.
8. **Follow-ups (separate small PRs):**
   - Delete the converter.
   - Add `CNAME` to `docs-site/pages-root`, so a rebuilt `gh-pages` keeps the domain.
   - Tag `archive/gitbook-sync`, then delete branch `docs/gitbook-sync`.
   - Update M1 plan Task 9: `{% hint %}` becomes `!!! warning`, and the page goes in the `mkdocs.yml` nav instead of `SUMMARY.md`.
   - Switch to Zensical before 2027-05-05.
   - Optional: compress images (34 MB total, some screenshots around 2 MB), and add Dependabot to keep the pins current.

## Overlaps with open PRs

The base is `main`, so no PR is in this branch. These PRs add a few lines to doc files:

| PR | Doc files | State |
|---|---|---|
| #202 | `contributing.md` | Merged to `dev` 2026-10-25 |
| #208 | `data-overview.md`, `dev-environment.md` | Open |
| #212 | `setup-guide.md` | Open |
| #214 | `dev-environment.md` | Open |

Their conflicts get resolved in step 7 if they reach `dev` first, or when they rebase onto `dev` afterwards. #224 (M1) Task 9 writes GitBook syntax and is covered in the follow-ups.

## Verification

- **Local build:** `python3 -m venv ~/.venvs/tm-docs && ~/.venvs/tm-docs/bin/pip install -r docs-site/requirements.txt && ~/.venvs/tm-docs/bin/mkdocs build --strict` passes.
- **Visual check:** compare every page under `mkdocs serve` with the live GitBook page: images, admonitions, tables, cards, links.
- **Leftovers:** `grep -rE '\{%|"mention"|\.gitbook/' docs` finds nothing.
- **Local mike rehearsal:** on a local `gh-pages` branch, without `--push`, run `mike deploy dev`, `mike deploy --update-aliases v0.7.1 latest` and `mike set-default latest`, then `mike serve`. Check the dropdown, the outdated banner (on dev only), and search in each version. Delete the local branch afterwards.
- **Redirect page:** serve `docs-site/pages-root/` with a small local server that returns `404.html` for missing paths, and check a few old paths.
- **PR check:** the `check` job passes. A deliberately broken link fails it: try it once, then revert.
- **After v0.7.1, on glossyio.github.io/traffic-monitor/:**
  - The root goes to `/latest/`.
  - The dropdown shows `v0.7.1` with the `latest` alias, plus Dev after step 7.
  - All 23 sitemap paths redirect. Spot-check in a browser; `curl` shows the 404 page with the redirect script.
  - "Edit this page" opens GitHub on `dev`.
- **After DNS:** `dig docs.trafficmonitor.ai` shows `glossyio.github.io`, HTTPS is valid, and the redirect spot-checks pass on the custom domain.
- **Commits:** end with the repo's `Assisted-by` / `AI-Model` / `AI-Effort` / `AI-Role` trailer block. Everything is committed locally and shown to the user before any push.
