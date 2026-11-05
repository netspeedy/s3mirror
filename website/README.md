# s3mirror website

This folder is the source of s3mirror's GitHub Pages site,
<https://netspeedy.github.io/s3mirror/>. It's a small Vite build rather than
documentation to read here; that lives in the main [README](../README.md).

## Working on it

Run these from the repository root:

```bash
make website-install   # npm ci, from package-lock.json
make website-dev       # local server with live reload
make website-check     # the page's required files and structure
make website-build     # production build into website/dist/
```

CI builds with Node 22, in the Lint workflow's Website Build job.

`public/og-image.png` and `public/og-image.svg` are the link-preview card. `make
readme-hero` generates them along with the README banner, so edit
`scripts/readme/build_readme_hero.py` rather than the files.

## How it's published

Deploy Pages Site runs after each Automated Release run on `main`, and can be
started by hand. It builds the page with the latest release's version and deploys
it. Dependabot checks the npm dependencies here weekly.
