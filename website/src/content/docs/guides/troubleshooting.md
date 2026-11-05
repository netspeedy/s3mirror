---
title: Troubleshooting
description: What to check when s3mirror can't connect, can't create a bucket, won't copy an object, or deletes more than you expected.
---

Start with `--debug`. It shows the endpoint and region each client uses, every listing with its
object count and sizes, and every copy and deletion decision. [Logging](/s3mirror/reference/logging/)
explains the lines.

## It can't connect

The connection check is a `ListBuckets` call on each side, and its failure looks like this:

```text title="Output"
✗ Source connection FAILED
  Error code: InvalidAccessKeyId
  Error message: The AWS Access Key Id you provided does not exist in our records.
  HTTP status: 403
Connection verification failed - aborting
```

The error code is the provider's, so it usually says what's wrong:

- `InvalidAccessKeyId` or `SignatureDoesNotMatch`: the keys are wrong, or are still the placeholder
  defaults because the key was left out of the config. `--show-config` shows what's in use.
- `AccessDenied`: the credential works but can't call `ListBuckets`. s3mirror needs it on both sides,
  even though it only uses the destination's answer to check the connection.
- `AuthorizationHeaderMalformed` or a region error: `region_name` doesn't match what the provider
  expects.

A failure that isn't an S3 error is logged on one line as `✗ Source connection error:` followed by
the exception, for example a DNS failure, a refused connection or a certificate that doesn't
verify. Check the scheme and port in `endpoint_url`, that this machine can reach it, and
`verify_ssl`. A `certificate verify failed` error with `verify_ssl: true` usually means a private
CA: point `verify_ssl` at its bundle, as [Safety](/s3mirror/how-it-works/safety/#tls) shows.

## A destination bucket isn't created

```text title="Output"
  ✗ Failed to create bucket: An error occurred (AccessDenied) when calling the CreateBucket operation: Access Denied
  Skipping bucket due to creation failure
```

The bucket is skipped and counted as an error, and the run carries on. Either the destination
credential can't create buckets, or the provider wants them created another way. s3mirror calls
`CreateBucket` with only the name, without a location constraint, which AWS rejects in any region
other than `us-east-1`. Create the bucket yourself in that case, and s3mirror will use it.

s3mirror also tries to create a bucket when `HeadBucket` fails for any reason, so a bucket that
exists but that the credential can't see gets a `CreateBucket` call too, which usually fails with
`BucketAlreadyExists` or `BucketAlreadyOwnedByYou`.

## An object isn't copied

If the destination has an object with the same key and the same size, s3mirror counts it as in sync
and never copies it again, even if the contents differ. Delete or rename the destination copy to
force a copy. [Change detection](/s3mirror/how-it-works/change-detection/) explains why.

If the whole bucket is missing from the run, check that the source credential can see it in
`ListBuckets` and that it isn't in `exclude_buckets`. The `Excluding` line near the top of the
output names the buckets excluded.

## A bucket is skipped after a listing failure

```text title="Output"
  Failed to list objects in app-data on the source: An error occurred (AccessDenied) when calling the ListObjectsV2 operation: Access Denied
  Skipping bucket due to listing failure
```

Nothing in the bucket is copied or deleted, the failure is counted as an error, and the run carries
on with the next bucket. An `AccessDenied` means the credential on the side named can see the
bucket but lacks `s3:ListBucket` on it: grant it, or add the bucket to `exclude_buckets` if it
shouldn't be mirrored. A timeout or connection error in that line means the endpoint stopped
answering and botocore's retries ran out; the next run lists the bucket again from the start. [Deletion](/s3mirror/how-it-works/deletion/#when-a-listing-fails) explains why a partial
listing is never used.

## More was deleted than expected

Deletion removes every destination object the source doesn't have, in each mirrored bucket,
including objects someone wrote straight to the destination. The log file, or `--debug`, names each
key with a `✓ Deleted:` line. Check that `source` points at the endpoint and credential you meant,
because a source that's been emptied or swapped is mirrored faithfully, and read
[Deletion](/s3mirror/how-it-works/deletion/). If the destination has versioning on, the deleted
objects can be restored by removing their delete markers.

## The output is too noisy for cron

Use `--log-file`, which sends the full log to a file and leaves only error lines on the console, or
`--quiet` for the same console without a file.

## A run fails with `FATAL ERROR`

An unexpected exception during the run is logged as `FATAL ERROR:` with a traceback and exit code 1.
A common cause is a config value of the wrong type, such as `max_workers: "20"` in quotes, because
s3mirror doesn't check types. Run `--show-config` and look for strings where numbers belong.
