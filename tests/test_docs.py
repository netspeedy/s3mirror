"""Docs site tests."""

# argparse has no public way to list a parser's options.
# pylint: disable=protected-access

import re
from pathlib import Path

import s3mirror

REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "website"
    / "src"
    / "content"
    / "docs"
    / "reference"
    / "cli.mdx"
)


def _documented_flags() -> list[str]:
    """Return every option in the CLI reference page's flag lists, in page order."""
    text = REFERENCE.read_text(encoding="utf-8")
    flags: list[str] = []
    for body in re.findall(r"^export const \w+ = \[(.*?)^\];", text, re.M | re.S):
        for short, flag in re.findall(
            r'(?:short: "(-\w)", )?flag: "(--[a-z0-9-]+)"', body
        ):
            flags.append(flag)
            if short:
                flags.append(short)
    return flags


def test_cli_reference_covers_every_flag() -> None:
    """The CLI reference documents exactly the options s3mirror accepts.

    The page is written by hand so each option can be explained, which means nothing
    regenerates it when one changes. Its flag lists are the `export const ... = [...]`
    arrays the FlagTable component renders, and between them they cover every option
    string, -h and --help included, once.
    """
    documented = _documented_flags()
    repeated = sorted({flag for flag in documented if documented.count(flag) > 1})
    assert not repeated, f"reference/cli.mdx documents these more than once: {repeated}"

    parser = s3mirror.build_parser()
    accepted = {
        option for action in parser._actions for option in action.option_strings
    }
    missing = sorted(accepted - set(documented))
    unknown = sorted(set(documented) - accepted)
    assert not missing and not unknown, (
        "reference/cli.mdx is out of step with the parser: "
        f"not documented {missing}, documented but not accepted {unknown}"
    )
