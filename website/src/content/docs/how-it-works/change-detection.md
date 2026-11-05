---
title: Change detection
description: s3mirror copies an object when its key is missing at the destination or its size differs, and that's the only comparison it makes.
---

For each bucket, s3mirror lists every object on both sides and keeps two things per object: its
key and its size in bytes. Then, for each source object:

| At the destination | What happens |
| --- | --- |
| No object with that key | Copied, logged at debug level as `New file:` |
| An object with that key and a different size | Copied over it, logged as `Changed:` |
| An object with that key and the same size | Skipped, with no log line |

That's the whole rule. With `--debug` you can see each decision as the run makes it:

```text title="Output, part of a --debug run"
[INFO]   Source: 4 objects
[INFO]   Destination: 3 objects
[DEBUG]   Calculating differences...
[DEBUG]     Changed: config/settings.json (src:2.3KB != dst:2.1KB)
[DEBUG]     New file: exports/2026-11-02.csv (49.8KB)
[DEBUG]     New file: exports/2026-11-03.csv (48.7KB)
[INFO]   Actions: 3 to copy (100.8KB), 0 to delete
```

The fourth source object, `exports/2026-11-01.csv`, had the same size on both sides, so it isn't
mentioned at all.

## What it doesn't compare

s3mirror doesn't look at ETags, checksums, modification times or contents. Two objects with the same
key and size count as in sync even when their bytes differ, for example a config file edited without
changing its length, or a fixed-width export regenerated with new values. Those changes never reach
the destination.

The comparison is also blind to everything about an object other than its size:

- metadata, including `Content-Type`, `Cache-Control` and user metadata
- tags
- ACLs and object ownership
- storage class
- server-side encryption settings
- Object Lock retention and legal holds
- older versions, in a versioned source bucket

None of those are copied either. A copied object is uploaded with only its bucket and key set, so it
gets whatever the destination applies by default: its default storage class and encryption, no
user metadata, and a generic content type. If something downstream relies on `Content-Type`, for
example a website served from the destination bucket, s3mirror's copies won't carry it.

`ListObjectsV2` returns only the current version of each key, so a versioned source is mirrored as
its latest state. Delete markers and noncurrent versions aren't copied.

## Forcing a copy

Because a same-size object is never copied again, the only way to make s3mirror re-copy one is to
remove it from the destination, or rename it there, and run again. It will then count as a new file.

## Why it works like this

Comparing listings is cheap. Listing a bucket returns up to a thousand keys and sizes per request,
so a bucket of a million objects that's already in sync costs about a thousand requests per side,
and no object is read. Comparing contents would mean reading or hashing every object, or trusting
ETags, which differ between providers and between single-part and multipart uploads of the same
bytes. The trade-off is the blind spots above: if your objects can change without changing size,
s3mirror alone won't keep the destination in step.
