import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const websiteRoot = path.resolve(__dirname, "..");
const requiredFiles = [
  "favicon.svg",
  "index.html",
  "main.js",
  "style.css",
  "vite.config.js",
  "public/og-image.png",
];

const requiredDOMIDs = [
  "site-home-link",
  "nav-container-link",
  "nav-homebrew-link",
  "nav-releases-link",
  "nav-docs-link",
  "nav-github-link",
  "hero-docs-link",
  "release-version",
  "release-date",
  "release-commit",
  "release-highlights",
  "container-command",
  "homebrew-command",
  "venv-command",
  "source-command",
  "install-container-link",
  "install-homebrew-link",
  "install-source-link",
  "footer-release-link",
  "footer-container-link",
  "footer-version",
  "footer-commit",
];

const errors = [];

function assert(condition, message) {
  if (!condition) {
    errors.push(message);
  }
}

function load(relativePath) {
  const fullPath = path.join(websiteRoot, relativePath);
  assert(existsSync(fullPath), `Missing required file: ${relativePath}`);
  return existsSync(fullPath) ? readFileSync(fullPath, "utf8") : "";
}

function checkNodeSyntax(relativePath) {
  const result = spawnSync(process.execPath, ["--check", relativePath], {
    cwd: websiteRoot,
    encoding: "utf8",
  });

  if (result.status !== 0) {
    const output = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
    errors.push(`Syntax check failed for ${relativePath}${output ? `\n${output}` : ""}`);
  }
}

function findRootRelativeLocalAssets(html) {
  const assetRefs = [...html.matchAll(/\b(?:src|href)=["']([^"']+)["']/g)].map((match) => match[1]);
  return assetRefs.filter((ref) => ref.startsWith("/") && !ref.startsWith("//"));
}

const indexHTML = load("index.html");
const mainJS = load("main.js");
const viteConfig = load("vite.config.js");

for (const relativePath of requiredFiles) {
  assert(existsSync(path.join(websiteRoot, relativePath)), `Missing required file: ${relativePath}`);
}

checkNodeSyntax("main.js");
checkNodeSyntax("vite.config.js");

assert(indexHTML.includes('<script type="module" src="./main.js"></script>'), "index.html must load ./main.js");
assert(indexHTML.includes('<link rel="icon" href="./favicon.svg" type="image/svg+xml" />'), "index.html must declare ./favicon.svg");
assert(indexHTML.includes('property="og:image"'), "index.html must declare og:image for social previews");
assert(indexHTML.includes('property="og:image:type" content="image/png"'), "og:image:type must be image/png");
assert(indexHTML.includes('property="og:image:width" content="1200"'), "og:image:width must be 1200");
assert(indexHTML.includes('property="og:image:height" content="630"'), "og:image:height must be 630");
assert(indexHTML.includes('name="twitter:card" content="summary_large_image"'), "twitter:card must be summary_large_image");
assert(mainJS.includes('import "./style.css";') || mainJS.includes("import './style.css';"), "main.js must import ./style.css");
assert(viteConfig.includes('base: "./"') || viteConfig.includes("base: './'"), "vite.config.js must keep base set to ./");

for (const domID of requiredDOMIDs) {
  assert(indexHTML.includes(`id="${domID}"`), `index.html is missing required id="${domID}"`);
}

for (const tabID of ["container", "homebrew", "venv", "source"]) {
  assert(indexHTML.includes(`data-tab="${tabID}"`), `index.html is missing data-tab="${tabID}"`);
  assert(indexHTML.includes(`id="panel-${tabID}"`), `index.html is missing id="panel-${tabID}"`);
}

const rootRelativeAssets = findRootRelativeLocalAssets(indexHTML);
assert(
  rootRelativeAssets.length === 0,
  `index.html contains root-relative local asset paths that break GitHub Pages subpath deploys: ${rootRelativeAssets.join(", ")}`,
);

assert(indexHTML.includes('href="#install"'), "index.html must retain the install anchor link");
assert(indexHTML.includes('id="install"'), "index.html must retain the install section target");

if (errors.length > 0) {
  console.error("Website validation failed:\n");
  for (const error of errors) {
    console.error(`- ${error}`);
  }
  process.exit(1);
}

console.log("Website validation passed.");
