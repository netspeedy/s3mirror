---
title: Exit codes
description: What s3mirror's exit codes 0, 1, 2, 130 and 143 mean, and what produces each.
---

s3mirror exits with one of five codes, so a scheduler or script can tell a clean run from one that
needs attention:

| Code | Meaning |
| --- | --- |
| `0` | The run finished and counted no errors, or `--show-config`, `--version` or `--help` |
| `1` | The run counted errors, couldn't connect, couldn't read its config or hit an unexpected error |
| `2` | A bad flag or flag value |
| `130` | Interrupted with Ctrl+C (`SIGINT`) |
| `143` | Stopped with `SIGTERM`, from `kill`, `systemctl stop` or `docker stop` |

## 0

The run went through every bucket and counted no errors. That includes runs that did nothing: every
bucket already in sync, or `No buckets found to sync` because the source has none or they're all
excluded.

`--show-config`, `--version` and `--help` also exit 0, without connecting to anything.

## 1

The run counted at least one error, which is one of:

- an object that failed to copy
- an object that failed to delete
- a destination bucket that `HeadBucket` couldn't check, other than a 404 for a missing one, or
  that couldn't be created, so the bucket was skipped
- a bucket whose objects couldn't be listed in full on either side, so the bucket was skipped with
  nothing copied or deleted
- the source's bucket list, if it couldn't be read again after the connection check, in which case
  no bucket is mirrored

These don't stop the run: it finishes every bucket it can, prints the summary with
`⚠ Errors encountered: N` and `Status: COMPLETED WITH ERRORS`, and then exits 1.

It also exits 1, without changing anything, when:

- the connection check fails on either side (`Connection verification failed - aborting`)
- the config file is missing, has an unsupported extension, doesn't parse, isn't a mapping at the
  top level, or has a `delete_extraneous` or `verify_ssl` value s3mirror can't read, with a message
  on standard error such as `Error: Config file not found: config.yaml`
- the log file can't be opened, for example because its directory doesn't exist, which prints a
  Python traceback

And it exits 1 part-way through when something unexpected goes wrong, logged as `FATAL ERROR:` with
a traceback, such as a config value of the wrong type.

## 2

A flag s3mirror doesn't know, a flag missing its value, or a `--workers` value that isn't a whole
number of at least 1. It prints usage and the problem to standard error and exits before reading the
config.

## 130 and 143

Ctrl+C, or `SIGINT` from anything else, exits 130, and `SIGTERM` exits 143, which is 128 plus the
signal's number, as a shell would report it. Both stop the run the same way. s3mirror stops
queuing work: if objects are being copied or deleted, it drops the ones still queued for the
current bucket, logs `Stopping: dropping the queued work and waiting for the transfers already
running`, and lets those finish, so none is cut off halfway. Then it logs
`Operation cancelled by user (Ctrl+C)` or `Operation stopped by SIGTERM` and exits without a
summary. The remaining buckets aren't touched.

The transfers already running are at most `max_workers` objects, but a large one can take a while.
A second Ctrl+C or `SIGTERM` stops at once, logging
`Stopping now, without waiting for the transfers in progress`, with the same exit code.

## Killed by a signal

`SIGKILL`, or a signal s3mirror doesn't handle such as `SIGHUP`, ends it at once, mid-transfer and
without a summary, and a shell reports 128 plus the signal's number: 137 for `SIGKILL`. That's what
happens when `docker stop` or systemd runs out of patience after a `SIGTERM`;
[Container](/s3mirror/guides/container/#stopping-it) has the timeouts.

Whichever way it stops, the next run picks up where this one stopped. An object whose upload was cut off never
appears at the destination, so it's copied again in full. An interrupted multipart upload can leave
its uploaded parts behind, though, and some providers keep and charge for those until they're
aborted, so a lifecycle rule that removes incomplete multipart uploads is worth having at the
destination.
