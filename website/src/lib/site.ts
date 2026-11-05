// Release details for the pages, read once at build time.
//
// The Pages workflow resolves the latest release (and the APT signing key, for a project that
// publishes an APT repository) before it builds the site, writes them to a JSON file and passes
// its path in SITE_METADATA_FILE. Local and pull request builds don't have that file, so they fall
// back to the newest local tag and leave the fingerprint out rather than guess it.
//
// The docs are versioned by release line (v0.8, v0.9 and so on). The latest line is built at the
// site root. When a newer line ships, the release workflow builds the old one again with
// SITE_ARCHIVE set to its line, which moves it under the root as <root>v0.8/, and the Pages
// workflow puts each archived line back beside the latest one and lists them in docs_versions.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

export const links = {
  org: "https://github.com/netspeedy",
  repo: "https://github.com/netspeedy/s3mirror",
  releases: "https://github.com/netspeedy/s3mirror/releases",
  issues: "https://github.com/netspeedy/s3mirror/issues",
  homebrew: "https://github.com/netspeedy/homebrew-s3mirror",
  container: "https://github.com/netspeedy/s3mirror/pkgs/container/s3mirror",
  source: "https://github.com/netspeedy/s3mirror/blob/main/s3mirror.py",
  siteUrl: "https://netspeedy.github.io/s3mirror/",
  image: "ghcr.io/netspeedy/s3mirror",
};

export interface Release {
  /** The release tag, such as v0.8.38, or "dev" when no tag is known. */
  version: string;
  /** True when version is a real tag rather than the "dev" placeholder. */
  tagged: boolean;
  /** The APT signing key's fingerprint in groups of four, only when the repository is published. */
  aptFingerprint?: string;
  /** The release page, or the releases list when there's no tag. */
  url: string;
}

interface Metadata {
  latest_release?: { tag_name?: string; html_url?: string } | null;
  apt_repository?: { available?: boolean; fingerprint?: string };
  /** The archived release lines published beside this build, each with its newest release. */
  docs_versions?: { version: string; release: string }[];
}

function readMetadata(): Metadata | undefined {
  const file = process.env.SITE_METADATA_FILE;
  if (!file) return undefined;
  if (!existsSync(file)) throw new Error(`SITE_METADATA_FILE points at ${file}, which doesn't exist`);
  return JSON.parse(readFileSync(file, "utf8")) as Metadata;
}

function latestTag(): string | undefined {
  try {
    const tag = execFileSync("git", ["describe", "--tags", "--abbrev=0", "--match", "v*"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return tag || undefined;
  } catch {
    return undefined;
  }
}

const metadata = readMetadata();

function resolveRelease(): Release {
  const latest = metadata?.latest_release ?? undefined;
  const tag = latest?.tag_name || latestTag();
  const apt = metadata?.apt_repository;
  return {
    version: tag ?? "dev",
    tagged: Boolean(tag),
    aptFingerprint: apt?.available && apt.fingerprint ? apt.fingerprint : undefined,
    url: latest?.html_url || (tag ? `${links.releases}/tag/${tag}` : links.releases),
  };
}

export const release = resolveRelease();

/** The release line a version belongs to: v0.8.38 is in v0.8. */
export const lineOf = (version: string) => /^v\d+\.\d+/.exec(version)?.[0];

export interface DocsVersion {
  /** The release line, such as v0.8, or "dev" for an untagged build. */
  version: string;
  /** The line's newest release, such as v0.8.38. */
  release: string;
  /** Where the line's docs start, such as <root>v0.8/. */
  url: string;
  /** The newest release's notes. */
  notes: string;
  latest: boolean;
}

const archive = process.env.SITE_ARCHIVE || undefined;
const base = import.meta.env.BASE_URL.replace(/\/?$/, "/");

/** The site root every line lives under, also in an archived build. */
export const siteRoot = archive ? base.slice(0, base.length - archive.length - 1) : base;

/**
 * A link from the root, such as <root>quickstart/, as a link to that page in the line being
 * built. In the latest line it's unchanged. rehype-archive-links.mjs does the same for the pages.
 */
export const docsHref = (href: string) =>
  archive && href.startsWith(siteRoot) && !/^v\d+\.\d+\//.test(href.slice(siteRoot.length))
    ? base + href.slice(siteRoot.length)
    : href;

function resolveDocs() {
  const current = archive ?? lineOf(release.version) ?? "dev";
  const self: DocsVersion = {
    version: current,
    release: release.version,
    url: base,
    notes: release.url,
    latest: !archive,
  };
  // An archived build only knows itself. Its version menu fetches the full list from the root's
  // versions.json, and this link to the latest docs stands in until it does.
  if (archive) {
    const latest: DocsVersion = { version: "Latest", release: "", url: siteRoot, notes: links.releases, latest: true };
    return { current, archived: true, versions: [latest, self] };
  }
  const older = (metadata?.docs_versions ?? [])
    .filter(({ version }) => version !== current)
    .sort((a, b) => b.version.localeCompare(a.version, "en", { numeric: true }))
    .map(({ version, release: tag }) => ({
      version,
      release: tag,
      url: `${siteRoot}${version}/`,
      notes: `${links.releases}/tag/${tag}`,
      latest: false,
    }));
  return { current, archived: false, versions: [self, ...older] };
}

/** Which line these docs are, whether it's an archived one, and every line published. */
export const docs = resolveDocs();

// ------------------------------------------------------------------ this project's copy
//
// What the shared components say about this project. The components themselves are the same in
// every netspeedy site, so a project's name, description and footer links live here.

export const product = {
  name: "s3mirror",
  description:
    "Mirrors buckets and objects from one S3-compatible endpoint to another, copying what's new or " +
    "changed in size and removing what the source no longer has.",
};

/** The line under "Browse the docs" on the home page. */
export const directorySubtitle = "From a first copy-only run to every config key.";

/** The site footer's link columns. */
export const footerColumns = [
  {
    title: "Docs",
    items: [
      { label: "Introduction", href: `${base}introduction/` },
      { label: "Quickstart", href: `${base}quickstart/` },
      { label: "How mirroring works", href: `${base}how-it-works/` },
      { label: "CLI reference", href: `${base}reference/cli/` },
    ],
  },
  {
    title: "Project",
    items: [
      { label: "GitHub", href: links.repo },
      { label: "Releases", href: links.releases },
      { label: "Issues", href: links.issues },
      { label: "Source", href: links.source },
    ],
  },
  {
    title: "Install",
    items: [
      { label: "Homebrew tap", href: links.homebrew },
      { label: "GHCR image", href: links.container },
      { label: "From a checkout", href: `${base}installation/#from-a-checkout` },
    ],
  },
];
