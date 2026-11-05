#!/usr/bin/env bash
# Print the commit an outgoing release line's docs are archived from.
#
# A line's docs stay current on main until the first release-bearing commit after the line's last
# release, using the same rules as next-release.sh: feat:, fix:, perf:, revert:, build:, deps:,
# packaging:, release: and breaking changes. Everything after the last release ships in the new
# line, because s3mirror doesn't release from old lines, so that commit is where the old line's
# pages stop describing it. The archive is built from the commit just before it, which keeps
# docs: and ci: changes that landed after the last release. If nothing release-bearing landed
# between the two tags, it's the commit before the new line's first tag.
#
# s3mirror's versions are chosen by bumping __version__, so a new minor needn't contain a feat:
# commit, which is why this doesn't look for one the way next-release.sh's minor bump does.
#
# Usage: bash scripts/release/docs-archive-commit.sh <last tag of the old line> <first tag of the new line>
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <last tag of the old line> <first tag of the new line>" >&2
  exit 2
fi

previous_tag="$1"
next_tag="$2"

while read -r commit; do
  subject="$(git log -1 --format=%s "${commit}")"
  body="$(git log -1 --format=%b "${commit}")"
  if [[ "${subject}" =~ ^(feat|fix|perf|revert|build|deps|packaging|release)(\([^\)]+\))?:\  ]] ||
    [[ "${subject}" =~ ^[[:alnum:]][[:alnum:]-]*(\([^\)]+\))?!:\  ]] ||
    grep -q 'BREAKING CHANGE:' <<<"${body}"; then
    git rev-parse "${commit}^"
    exit 0
  fi
done < <(git rev-list --reverse --first-parent "${previous_tag}..${next_tag}")

git rev-parse "${next_tag}^"
