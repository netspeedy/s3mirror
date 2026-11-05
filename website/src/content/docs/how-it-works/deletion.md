---
title: Deletion
description: Which destination objects s3mirror deletes, when it deletes them, how to turn it off, and the case where a failed listing empties a destination bucket.
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
may be overwritten if its size differs.

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

Use YAML's bare `false`, or JSON's `false`. The value isn't checked, only tested for truth, so a
quoted `"false"` is a non-empty string and leaves deletion on.

## Versioned destinations

s3mirror deletes with a plain `DeleteObject` and no version ID. In a destination bucket with
versioning enabled, that adds a delete marker and keeps the object's earlier versions, so a deletion
can be undone by removing the marker. In an unversioned bucket the object is gone. If you want a way
back from an unwanted deletion, turn versioning on at the destination, with a lifecycle rule to
expire noncurrent versions so they don't pile up.

## When a listing fails

:::danger[A failed source listing deletes the destination bucket's contents]
If listing a source bucket's objects fails, for example because the source credential lacks
`s3:ListBucket` on that bucket, s3mirror logs the error and treats the source bucket as empty. With
deletion on, every object in the destination bucket then counts as extraneous and is deleted. The
listing error isn't counted as an error, so the run can still end with
`✓ Status: COMPLETED SUCCESSFULLY` and exit 0.
:::

This is what it looks like for a bucket that was already in sync:

```text title="Output"
  Failed to list objects in app-data: An error occurred (AccessDenied) when calling the ListObjectsV2 operation: Access Denied
  Source: 0 objects
  Destination: 4 objects
  Actions: 0 to copy (0.0B), 4 to delete
  ✓ Deleted 4 objects in 0.0s
```

The same applies if the listing fails partway through a large bucket: the keys after the failure
count as missing from the source. s3mirror doesn't stop on a failed listing, so guard against this
in the config and in permissions:

- Give the source credential `s3:ListBucket` on every bucket it can see, and check it with a
  `--no-delete --debug` run after any change to its permissions.
- Exclude any bucket the source credential can list in `ListBuckets` but not read.
- Watch scheduled logs for `Failed to list objects` as well as the exit code.
- Keep versioning on at the destination, so a run like this can be rolled back.

A failed listing on the destination side is less dangerous: the destination bucket is treated as
empty, so every source object is copied again and nothing is deleted.
