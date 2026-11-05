# Repository Guidelines

## Project Structure & Ownership

- s3mirror is one script, `s3mirror.py`, at the repository root, and its tests
  are in `tests/`. The `S3Mirror` class does the mirroring; `build_parser()`,
  `load_config()` and `setup_logging()` handle the flags, the config file and
  output, and `main()` ties them together.
- Its runtime dependencies are `boto3`, `urllib3` and `PyYAML`, listed unpinned
  in `requirements.txt`. Don't add another lightly: the Dockerfile installs
  `requirements.txt`, but the Homebrew formula in `netspeedy/homebrew-s3mirror`
  installs a fixed list of packages by name, so a new dependency has to be added
  there too or the Homebrew install breaks.
- Keep first-party automation, packaging and release assets at the root, under
  `.github/`, `scripts/` and `website/`. The Dockerfile copies only
  `requirements.txt` and `s3mirror.py` into the image.
- Treat `website/` as a first-party release surface, not a throwaway demo. It
  is the s3mirror documentation, built with Astro and Starlight; the pages are
  Markdown and MDX in `website/src/content/docs`. User-facing documentation
  lives there, with the README as the short version.
- When CLI behaviour, flags, defaults, config keys, log lines, deletion rules or
  exit codes change, update the matching site pages in the same change, and the
  README where it covers the same thing. The pages describe what the code does,
  including its rough edges, so a fix that changes behaviour changes the pages
  too. `test_cli_reference_covers_every_flag` in `tests/test_docs.py` fails when
  a flag is added or removed without updating
  `website/src/content/docs/reference/cli.mdx`; it reads the parser from
  `build_parser()`, so keep every flag registered there.
- The mark, the README banner, the social cards and the site's icons all come
  from `scripts/readme/build_readme_hero.py` via `make readme-hero`. Change the
  generator, not the generated files. The tap, `netspeedy/homebrew-s3mirror`,
  carries a copy of the generator, so change both.
- Each sidebar group has its own colour and icon, and each header tab owns
  some of the groups and shows only those in its sidebar. Both are in
  `website/src/lib/sections.ts`, matched to the sidebar in
  `website/astro.config.mjs` by label, so adding or renaming a group means
  updating `sections` and `tabs` there.
- The site's components and styles are shared with the other netspeedy docs
  sites, so their classes, custom properties and elements use the neutral
  `ns-` prefix and they don't name s3mirror. s3ctl's site is the standard, so
  carry design changes over from there rather than diverging. What's
  particular to s3mirror (its name, description, links and footer columns, and
  the home page's directory line) lives in `website/src/lib/site.ts`, and the
  pages written for s3mirror are `HomeTop.astro`, `InstallTabs.astro` and
  `src/pages/404.astro`, alongside the content, `astro.config.mjs`,
  `src/lib/sections.ts` and the palette and mark colours at the top of
  `theme.css`. Keep it that way, so a change to a shared file can be copied
  between the sites as it is.
- The shared components support versioned docs, but s3mirror doesn't publish
  archived release lines, so the version menu lists only the current release
  and `website/src/content/docs` always describes the latest one. Never copy
  pages into per-version folders. Keep page links root-relative
  (`/s3mirror/...`).
- Keep the website out of `.github/`. Dependabot stopped being able to open npm
  pull requests for manifests under `.github/` in June 2026 (its create-PR call
  is rejected as "invalid or unauthorized changes"), which is why it lives at
  the root.

## Build, Lint, and Test Commands

- Install the runtime dependencies and the development tools:
  ```bash
  python3 -m pip install -r requirements.txt
  python3 -m pip install black isort pylint pytest "moto[s3,server]"
  ```
- Check formatting and imports, and run pylint and the tests, as the Lint
  workflow does:
  ```bash
  black --check s3mirror.py tests
  isort --check-only s3mirror.py tests
  pylint s3mirror.py tests
  make test
  ```
- Build the container image and check it starts. It needs Docker and network
  access to pull the base image:
  ```bash
  make container-smoke
  ```
- Lint workflow changes:
  ```bash
  actionlint .github/workflows/*.yml
  ```
- Build the docs site, then validate the built output (pages, search index,
  icons, share card and every internal link). The check reads `website/dist`,
  so it always runs after the build:
  ```bash
  make website-install
  make website-build
  make website-check
  ```
- Drive the site in headless Chrome: the theme controls, the header and its
  tabs, and the version menu. It builds its own copies under `website/.test/`,
  so it needs no release metadata:
  ```bash
  make website-test
  ```
- Screenshot the built site in both themes at desktop and phone widths:
  ```bash
  make website-capture
  ```
- Serve the site with live reload while editing pages with `make website-dev`.
  When Astro detects an agent it starts the server in the background and returns,
  so stop it afterwards with `cd website && npx astro dev stop`.
  `website/README.md` summarises the folder, its targets and how it's published;
  keep it in step when any of those change.
- Rebuild the banner, social cards and site icons with `make readme-hero`. It
  runs the generator with `uv`, renders with headless Chrome or Chromium (set
  `CHROME` if it isn't found), and needs network access the first time to fetch
  the pinned fonts. With unchanged copy every output should come out
  byte-identical.

## Python Style & Quality Rules

- black and isort at their defaults (88 columns; there's no `pyproject.toml`),
  and pylint clean with `.pylintrc`. Pushes to `main` are formatted with black
  and isort automatically, but pull requests have to pass the checks first.
- Keep s3mirror a single script that runs on Python 3.11 and newer. The Lint
  workflow checks 3.11 to 3.14; the image is built on `python:3.15-slim`.
- Keep exit codes stable: 0 for a run with no counted errors, 1 for counted
  errors, a failed connection check, a config problem or a fatal error, 2 for a
  usage error, 130 for Ctrl+C and 143 for SIGTERM. Schedulers alert on them.
- Never log or print secret keys, or access key IDs in full. Debug output and
  `--show-config` shorten access key IDs with `redact_key_id()`, and
  `--show-config` redacts both secret keys.
- Deletion is the dangerous part. A change that affects what gets deleted, or
  when, needs saying plainly in the pull request and a matching update to the
  Deletion page. `--no-delete` must keep winning over the config.

## Workflow & Security Rules

- Treat workflow changes as security-sensitive. Keep GitHub Actions permissions
  least-privilege and scoped to the jobs that need them.
- Pull requests should validate code, the image build and the site without
  gaining access to release or publish credentials.
- Releases follow `__version__` in `s3mirror.py`:
  - Automated Release tags `v<__version__>` when that tag doesn't exist.
  - When it does exist, and every release-bearing commit since the last tag
    came from Dependabot, Renovate or this repository's workflows
    (`scripts/release/automated-only.sh`), it bumps `__version__` itself, and
    the run for that commit tags it.
  - A person releases their own change by bumping `__version__` in the pull
    request.
  - The tag push publishes the GHCR image, the Homebrew formula and the GitHub
    release (`github-release.yml`).
- `feat:`, `fix:`, `perf:`, `revert:`, `build:`, `deps:`, `packaging:` and
  `release:` commits, and breaking changes, are release-bearing
  (`scripts/release/next-release.sh` decides); `docs:`, `ci:`, `chore:` and
  `test:` aren't. `automated-only.sh` recognises automated commits by their
  author's noreply email, not by name. Dependabot titles Python and base-image
  updates `deps:`, so they release themselves, while Actions updates are `ci:`
  and website updates `chore:`.
- Container Image and Publish Homebrew Formula only publish stable tags that
  are on `main` and match `s3mirror.py --version`.
- Deploy Pages Site runs on pushes to `main`, published releases and completed
  GitHub Release runs. GitHub Release creates releases with `GITHUB_TOKEN`,
  which doesn't start release-event workflows, so the `workflow_run` trigger is
  what puts a new version on the site.

## Testing Expectations

- Minimum validation for changes to `s3mirror.py`:
  ```bash
  black --check s3mirror.py tests
  isort --check-only s3mirror.py tests
  pylint s3mirror.py tests
  make test
  python3 s3mirror.py --help
  ```
- `tests/test_mirror.py` runs `main()` against two moto S3 servers that
  `tests/conftest.py` starts on localhost, one per side, so the source and the
  destination keep separate state, and `tls_source` is a third that serves HTTPS
  with a self-signed certificate. The `faults` fixture makes chosen calls from
  s3mirror's own clients fail, with an S3 error or a raised exception, and can
  shrink listing pages to test pagination. A change to mirroring behaviour gets a
  test there. Never point a test at a real endpoint.
- If you change shell scripts, also run:
  ```bash
  bash -n scripts/release/*.sh
  shellcheck scripts/release/*.sh
  ```
- If you change the website, run `make website-build`, `make website-check` and
  `make website-test`, and look at `make website-capture` output for layout
  changes.
- If you change release tagging, also run:
  ```bash
  bash scripts/release/next-release.sh
  bash scripts/release/automated-only.sh "$(git describe --tags --abbrev=0)" HEAD
  ```

## Commit & PR Rules

- Do not create commits unless the user explicitly asks for a commit in the
  current turn.
- Use conventional commit subjects such as `feat:`, `fix:`, `docs:`, `ci:`,
  `deps:`, `chore:` or `test:`, and pick the type for its release effect: site
  changes are `docs:` and workflow changes are `ci:`. A `feat:` or `fix:` only
  ships when `__version__` is bumped in the same pull request.
- Keep changes focused by concern: runtime logic, automation, docs, packaging
  and website work shouldn't be bundled casually. A bug found while working on
  something else gets its own pull request.
- PR descriptions should explain the operational reason for the change, the
  validation performed, and any release, deletion or upgrade impact.
