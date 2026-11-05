---
title: Logging
description: Where s3mirror's output goes for each combination of flags, the format of the console and the log file, and what each line means.
---

s3mirror logs to two places: the console, always, and a file, when you pass `--log-file`. The
console level depends on the flags; the file always gets everything.

## Console level

| Flags | Console shows | Line format |
| --- | --- | --- |
| none | Progress and the summary (info and above) | The message alone |
| `--debug` | Everything (debug and above) | `[LEVEL] message` |
| `--quiet` | Errors only | The message alone |
| `--quiet --debug` | Errors only | `[LEVEL] message` |
| `--log-file` | Errors only | The message alone |
| `--log-file --debug` | Everything | `[LEVEL] message` |
| `--log-file --quiet` | Errors only | The message alone |

`--quiet` wins over `--debug` for the level, but `--debug` still adds the level prefix. When
standard output is a terminal, `--debug` also colours the level names.

Every log line goes to standard output, errors included. Three things go to standard error instead,
because they happen before logging starts: config file errors (`Error: Config file not found: ...`
and the like), usage errors from bad flags, and a Python traceback if the log file can't be opened.

## The log file

With `--log-file`, every line at debug level and above is appended to the file, with a timestamp
and the level padded to eight characters. Each run starts with a session header:

```text title="s3mirror.log"
2026-11-05 08:10:55 [INFO    ] 
2026-11-05 08:10:55 [INFO    ] ######################################################################
2026-11-05 08:10:55 [INFO    ] # NEW SESSION: 2026-11-05 08:10:55
2026-11-05 08:10:55 [INFO    ] ######################################################################
2026-11-05 08:10:55 [INFO    ] ======================================================================
2026-11-05 08:10:55 [INFO    ] S3 BUCKET MIRROR
2026-11-05 08:10:55 [INFO    ] Session started: 2026-11-05 08:10:55
2026-11-05 08:10:55 [INFO    ] ======================================================================
2026-11-05 08:10:55 [DEBUG   ] ======================================================================
2026-11-05 08:10:55 [DEBUG   ] INITIALIZATION
2026-11-05 08:10:55 [DEBUG   ] ======================================================================
2026-11-05 08:10:55 [DEBUG   ] Source endpoint: https://s3.source.example.com
```

The file is never truncated or rotated by s3mirror. It's opened when the run starts and closed when
it ends, so any log rotation tool can rotate it between runs.

## A bucket at debug level

This is one bucket from a log file, from the session above: one object changed size, two are new,
and one exists only at the destination.

```text title="s3mirror.log"
2026-11-05 08:10:55 [INFO    ]   Source: 4 objects
2026-11-05 08:10:55 [INFO    ]   Destination: 3 objects
2026-11-05 08:10:55 [DEBUG   ]   Calculating differences...
2026-11-05 08:10:55 [DEBUG   ]     Changed: config/settings.json (src:2.3KB != dst:2.1KB)
2026-11-05 08:10:55 [DEBUG   ]     New file: exports/2026-11-02.csv (49.8KB)
2026-11-05 08:10:55 [DEBUG   ]     New file: exports/2026-11-03.csv (48.7KB)
2026-11-05 08:10:55 [DEBUG   ]   Files to delete: 1
2026-11-05 08:10:55 [DEBUG   ]     - exports/old-report.csv
2026-11-05 08:10:55 [INFO    ]   Actions: 3 to copy (100.8KB), 1 to delete
2026-11-05 08:10:55 [DEBUG   ]   Starting parallel copy (20 workers)...
2026-11-05 08:10:55 [DEBUG   ]     ✓ config/settings.json [2.3KB]
2026-11-05 08:10:55 [DEBUG   ]     ✓ exports/2026-11-02.csv [49.8KB]
2026-11-05 08:10:55 [DEBUG   ]     ✓ exports/2026-11-03.csv [48.7KB]
2026-11-05 08:10:55 [INFO    ]   ✓ Copied 3 objects in 0.0s (45.0MB/s)
2026-11-05 08:10:55 [DEBUG   ]   Starting parallel delete (20 workers)...
2026-11-05 08:10:55 [DEBUG   ]     ✓ Deleted: exports/old-report.csv
2026-11-05 08:10:55 [INFO    ]   ✓ Deleted 1 objects in 0.0s
2026-11-05 08:10:55 [INFO    ]   ✓ Bucket completed in 0.0s
2026-11-05 08:10:55 [DEBUG   ]   Bucket stats: copied=3, deleted=1, errors=0
```

`Files to delete` lists at most five keys, followed by `... and N more`; the `✓ Deleted:` lines
name every key. In `Bucket stats`, `copied` is for this bucket, but `deleted` and `errors` are
totals for the run so far.

## What each level holds

**Info** is the run's progress: the banner, the two connection checks, the excluded buckets, then
for each bucket its `[n/N]: name` header, a `Created bucket` line if it was created, the object
counts on each side, the `Actions:` line, the copy and delete totals with their timings, or
`Already synchronized (no changes needed)`, and the bucket's time. Then the summary.

**Warning** marks a risk or something that didn't happen:
`⚠ TLS certificate verification is off for the source` (or `destination`),
`No buckets found to sync`, `Skipping bucket due to HeadBucket failure`, `due to creation failure`
or `due to listing failure`, `⚠ N objects failed to copy` or `failed to delete`,
`⚠ Errors encountered: N` in the summary, `Stopping: dropping the queued work ...`,
`Operation cancelled by user (Ctrl+C)` and `Operation stopped by SIGTERM`.

**Error** is a failed call: the connection check (`✗ Source connection FAILED` with the error code,
message and HTTP status), `Failed to list source buckets`, `Failed to check bucket on destination`,
`Failed to create bucket`, `Failed to list objects in <bucket> on the source` or
`on the destination`, `Failed to copy <key>`, `Failed to delete <key>`, and `FATAL ERROR` with a
traceback for anything unexpected.

**Debug** adds the detail: the settings in use, including each endpoint's region, with access keys
shortened to their first and last four characters, a sample of the source's bucket names, each
listing's object count, page count and sizes, or how far a failed listing got, every `New file:`
and `Changed:` decision, the keys to delete, the part size for an object too big for the configured
one (`Using 11.0MB parts for ...`), every key copied or deleted, progress every 50 copies, and
per-bucket timings.

## The summary

```text title="Output"
======================================================================
FINAL SUMMARY
======================================================================
Started:  2026-11-05 08:10:53
Finished: 2026-11-05 08:10:53
Duration: 0.0s (0s)

Buckets:
  - Processed: 2
  - Created:   1

Objects:
  - Copied:    5
  - Deleted:   0

Data transferred: 843.0KB
Average throughput: 36.6MB/s

✓ Status: COMPLETED SUCCESSFULLY
======================================================================
```

`Processed` counts buckets that got as far as the comparison, whatever happened to their copies.
A `Skipped` line appears when a bucket couldn't be checked, created or listed, `Average throughput`
only when something was copied, and with any errors the status line becomes `⚠ Errors encountered: N` followed by
`Status: COMPLETED WITH ERRORS`. A run stopped by Ctrl+C, `SIGTERM` or a fatal error prints no summary.

Sizes are in powers of 1024 with `B`, `KB`, `MB`, `GB` and `TB` labels. Durations under a minute
are in seconds, under an hour in minutes to one decimal place (`12.5m`), and beyond that in hours
and minutes (`2h 5m`).
