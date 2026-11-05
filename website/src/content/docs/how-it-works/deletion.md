---
title: Deletion
description: Which destination objects s3mirror deletes, when it deletes them, how to turn it off, and why a failed listing means nothing is deleted.
---

With deletion on, s3mirror deletes every object in a mirrored destination bucket whose key isn't in
the matching source bucket. That's what makes the destination a mirror rather than an accumulating
copy, and it's on by default: `delete_extraneous` is `true` unless your config says otherwise.

## What gets deleted

Deletion works bucket by bucket, and only on the buckets s3mirror is mirroring in that run:

- In a bucket that exists on both sides, any destination key the source doesn't have is deleted,
  whatever it is and whoever wrote it. An object someone uploaded straight to the destination is
  deleted on the next run.
- Buckets that exist only at the destination are left alone. s3mirror never lists the destination's
  buckets beyond the connection check, so it never looks inside them.
- Buckets named in `exclude_buckets` are skipped on both sides, so their destination copies are left
  alone too.
- Buckets themselves are never deleted, even when the source bucket has gone.

Deletion compares keys only. An object whose key exists on both sides is never deleted, though it
may be overwritten if its size differs. And it only ever works from two complete listings: if either
side's listing fails, nothing in that bucket is deleted, as [below](#when-a-listing-fails)
explains.

## When it happens

Within each bucket, the deletions run after the copies, once every copy has finished. They run even
if some copies failed. They use the same number of workers as the copies, `max_workers`.

At the normal log level a run only reports how many objects it deleted:

```text title="Output"
  Actions: 0 to copy (0.0B), 1 to delete
  ✓ Deleted 1 objects in 0.0s
```

`--debug` lists the first five keys it's about to delete and then each key as it goes, and
`--log-file` always writes those lines to the file, so keep a log of runs that can delete.

## Turning it off

For one run, pass `--no-delete`. It wins over the config whatever `delete_extraneous` says:

```bash
s3mirror --config config.yaml --no-delete
```

To turn it off for good, set it in the config:

```yaml title="config.yaml"
sync:
  delete_extraneous: false
```

The value has to be `true` or `false`: a real boolean, such as YAML's bare `false` or JSON's
`false`, or the string `"true"` or `"false"` in any case. Anything else, such as `"no"` in quotes,
`0` or an empty value, stops s3mirror with a config error and exit code 1 before it connects, so a
value it can't read never leaves deletion on by accident. Up to and including 1.0.4 the value was
only tested for truth, and a quoted `"false"` left deletion on.

## Versioned destinations

s3mirror deletes with a plain `DeleteObject` and no version ID. In a destination bucket with
versioning enabled, that adds a delete marker and keeps the object's earlier versions, so a deletion
can be undone by removing the marker. In an unversioned bucket the object is gone. If you want a way
back from an unwanted deletion, turn versioning on at the destination, with a lifecycle rule to
expire noncurrent versions so they don't pile up.

## When a listing fails

If listing a bucket's objects fails on either side, s3mirror skips that bucket: nothing in it is
copied and nothing is deleted. That holds whether the listing fails on its first page or partway
through a large bucket, and whether the cause is an S3 error, such as a credential without
`s3:ListBucket` on that bucket, or a timeout or dropped connection that outlasted botocore's
retries. A partial listing is never used, because the keys it didn't reach would look as if the
source no longer had them.

The skipped bucket counts as an error, so the run carries on with the other buckets, ends with
`Status: COMPLETED WITH ERRORS` and exits 1. This is what it looks like when the source credential
can't list one bucket:

```text title="Output"
  Failed to list objects in app-data on the source: An error occurred (AccessDenied) when calling the ListObjectsV2 operation: Access Denied
  Skipping bucket due to listing failure
```

With `--debug`, a line between those two says how many objects were listed before the failure. A bucket that
keeps failing is skipped on every run until the credential can list it, so grant `s3:ListBucket` on
it, or add it to `exclude_buckets` if it shouldn't be mirrored.

The same goes for the source's bucket list. If the second `ListBuckets` call, after the connection
check, fails, no bucket is mirrored and the run exits 1.

:::caution[Releases up to 1.0.4 deleted on a failed listing]
Up to and including 1.0.4, a failed listing was treated as an empty bucket and wasn't counted as an
error. A failed source listing with deletion on deleted every object in the destination bucket, or,
if it failed partway, every object the listing hadn't reached, and the run still exited 0. If you run one of those
releases, upgrade, or run with `--no-delete` until you can.
:::
