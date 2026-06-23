import "@fontsource-variable/inter";
import "./style.css";

const defaultSiteURL = new URL("./", window.location.href).href;

const fallbackHighlights = [
  "Mirror buckets between S3-compatible endpoints",
  "Run copy-only validation before enabling guarded deletes",
  "Keep scheduled runs readable with quiet, debug, and file logging",
];

const defaultMetadata = {
  site_url: defaultSiteURL,
  github_repository: "netspeedy/s3mirror",
  github_url: "https://github.com/netspeedy/s3mirror",
  release_url: "https://github.com/netspeedy/s3mirror/releases",
  homebrew_url: "https://github.com/netspeedy/homebrew-s3mirror",
  latest_release: null,
  release_commit: "",
};

function normalizeMetadata(metadata = {}) {
  return {
    ...defaultMetadata,
    ...metadata,
    site_url: `${metadata.site_url || defaultMetadata.site_url}`.replace(/\/?$/, "/"),
    github_url: metadata.github_url || defaultMetadata.github_url,
    release_url: metadata.release_url || defaultMetadata.release_url,
    homebrew_url: metadata.homebrew_url || defaultMetadata.homebrew_url,
    latest_release: metadata.latest_release || null,
    release_commit: metadata.release_commit || "",
  };
}

function formatDate(value) {
  if (!value) {
    return "Not published yet";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return value;
  }

  return `${new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(parsed)} UTC`;
}

function shortCommit(value) {
  if (!value) {
    return "---";
  }

  return value.length > 10 ? value.slice(0, 7) : value;
}

function releaseCommit(metadata) {
  if (metadata.release_commit) {
    return metadata.release_commit;
  }

  const body = metadata.latest_release?.body || "";
  const match = body.match(/\/commit\/([0-9a-f]{7,40})/i);
  return match ? match[1] : "";
}

function stripMarkdown(value) {
  return value
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function releaseHighlights(metadata) {
  const release = metadata.latest_release;
  const body = release?.body || "";
  const highlights = [];

  for (const rawLine of body.split("\n")) {
    const line = rawLine.trim();
    if (!line.startsWith("- ")) {
      continue;
    }

    const cleaned = stripMarkdown(line.slice(2)).replace(/\s+\([^)]*\)\s*$/, "");
    if (cleaned && !cleaned.startsWith("Automatically merged")) {
      highlights.push(cleaned);
    }

    if (highlights.length === 3) {
      break;
    }
  }

  if (highlights.length > 0) {
    return highlights;
  }

  if (release?.tag_name) {
    return [`Stable ${release.tag_name} release metadata is published`, ...fallbackHighlights.slice(1)];
  }

  return fallbackHighlights;
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function setHref(id, value) {
  const element = document.getElementById(id);
  if (element && value) {
    element.href = value;
  }
}

function renderCommands(metadata) {
  const releaseTag = metadata.latest_release?.tag_name || "v1.0.2";

  setText("homebrew-command", "brew tap netspeedy/s3mirror\nbrew install s3mirror");
  setText(
    "venv-command",
    "git clone https://github.com/netspeedy/s3mirror.git\ncd s3mirror\npython3 -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt",
  );
  setText(
    "source-command",
    `curl -L https://github.com/netspeedy/s3mirror/archive/refs/tags/${releaseTag}.tar.gz -o s3mirror-${releaseTag}.tar.gz`,
  );
}

function renderMetadata(rawMetadata) {
  const metadata = normalizeMetadata(rawMetadata);
  const release = metadata.latest_release;
  const commit = shortCommit(releaseCommit(metadata));

  setHref("site-home-link", metadata.site_url);
  setHref("nav-github-link", metadata.github_url);
  setHref("nav-releases-link", metadata.release_url);
  setHref("nav-homebrew-link", metadata.homebrew_url);
  setHref("nav-docs-link", `${metadata.github_url}#readme`);
  setHref("hero-docs-link", `${metadata.github_url}#readme`);
  setHref("install-homebrew-link", metadata.homebrew_url);
  setHref("install-source-link", metadata.release_url);
  setHref("footer-release-link", release?.html_url || metadata.release_url);

  setText("release-version", release?.tag_name || "Awaiting release");
  setText("release-date", formatDate(release?.published_at));
  setText("release-commit", commit);
  setText("footer-version", release?.tag_name?.replace(/^v/, "") || "---");
  setText("footer-commit", commit);

  const highlightsList = document.getElementById("release-highlights");
  if (highlightsList) {
    highlightsList.replaceChildren(
      ...releaseHighlights(metadata).map((highlight) => {
        const item = document.createElement("li");
        item.textContent = highlight;
        return item;
      }),
    );
  }

  renderCommands(metadata);
}

async function loadMetadata() {
  renderMetadata(defaultMetadata);

  try {
    const response = await fetch("./website-metadata.json", { cache: "no-store" });
    if (response.ok) {
      renderMetadata(await response.json());
    }
  } catch {
    // Static previews work without generated release metadata.
  }
}

function selectInstallTab(container, tabID) {
  container.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === tabID;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  container.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${tabID}`);
  });
}

function wireTabs() {
  document.querySelectorAll(".install-tabs").forEach((container) => {
    container.addEventListener("click", (event) => {
      const button = event.target.closest(".tab");
      if (!button) {
        return;
      }

      selectInstallTab(container, button.dataset.tab);
    });
  });

  document.querySelectorAll("[data-install-tab]").forEach((link) => {
    link.addEventListener("click", () => {
      const container = document.querySelector(".install-tabs");
      if (container) {
        selectInstallTab(container, link.dataset.installTab);
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireTabs();
  void loadMetadata();
});
