---
title: Exit codes
description: What s3mirror's exit codes 0, 1, 2 and 130 mean, and what produces each.
---

s3mirror exits with one of four codes, so a scheduler or script can tell a clean run from one that
needs attention:

| Code | Meaning |
| --- | --- |
| `0` | The run finished and counted no errors, or `--show-config`, `--version` or `--help` |
| `1` | The run counted errors, couldn't connect, couldn't read its config or hit an unexpected error |
| `2` | A bad flag or flag value |
| `130` | Interrupted with Ctrl+C |

## 0

The run went through every bucket and counted no errors. That includes runs that did nothing: every
bucket already in sync, or `No buckets found to sync` because the source has none or they're all
excluded.

`--show-config`, `--version` and `--help` also exit 0, without connecting to anything.

## 1

The run counted at least one error, which is one of:

- an object that failed to copy
- an object that failed to delete
- a destination bucket that couldn't be created, so the bucket was skipped
- a bucket whose objects couldn't be listed in full on either side, so the bucket was skipped with
  nothing copied or deleted
- the source's bucket list, if it couldn't be read again after the connection check, in which case
  no bucket is mirrored

These don't stop the run: it finishes every bucket it can, prints the summary with
`⚠ Errors encountered: N` and `Status: COMPLETED WITH ERRORS`, and then exits 1.

It also exits 1, without changing anything, when:

- the connection check fails on either side (`Connection verification failed - aborting`)
- the config file is missing, has an unsupported extension, doesn't parse or isn't a mapping at
  the top level, with a message on standard error such as `Error: Config file not found: config.yaml`
- the log file can't be opened, for example because its directory doesn't exist, which prints a
  Python traceback

And it exits 1 part-way through when something unexpected goes wrong, logged as `FATAL ERROR:` with
a traceback, such as a config value of the wrong type.

## 2

A flag s3mirror doesn't know, a flag missing its value, or a `--workers` value that isn't a whole
number of at least 1. It prints usage and the problem to standard error and exits before reading the
config.

## 130

Ctrl+C, or `SIGINT` from anything else. If it arrives while objects are being copied or deleted,
s3mirror first waits for the ones already queued for the current bucket, which can take a while for
a big bucket, then logs `Operation cancelled by user (Ctrl+C)` and exits 130 without a summary. The
remaining buckets aren't touched. To stop it without waiting, send `SIGTERM` instead.

## Killed by a signal

s3mirror doesn't handle `SIGTERM`, so `kill` or a service manager's stop request ends it at once,
mid-transfer and without a summary; a shell reports that as 143. In a container it's different,
because s3mirror runs as process 1 there; [Container](/s3mirror/guides/container/#stopping-it)
explains.

Either way the next run picks up where this one stopped. An object whose upload was cut off never
appears at the destination, so it's copied again in full. An interrupted multipart upload can leave
its uploaded parts behind, though, and some providers keep and charge for those until they're
aborted, so a lifecycle rule that removes incomplete multipart uploads is worth having at the
destination.
