---
title: Configuration
description: Write the config file, from both endpoints to exclusions and tuning, and check what s3mirror will actually use.
---

s3mirror reads one config file, in YAML or JSON, with four sections: `source`, `destination`,
`performance` and `sync`. You pass it with `--config`; there's no default path and no environment
variables, so without `--config` s3mirror runs with built-in placeholders that point at
`s3.source.example.com` and fail the connection check. [Config keys](/s3mirror/reference/configuration/)
lists every key with its default; this page is about putting a file together.

## The file format

The format comes from the extension: `.yaml` or `.yml` is read as YAML, `.json` as JSON. Anything
else stops with `Error: Unsupported config format. Use .yaml, .yml or .json` and exit code 1. The file has
to hold a mapping at the top level. An empty YAML file is read as an empty mapping, which leaves
every default in place, placeholders included.

The same config in JSON:

```json title="config.json"
{
  "source": {
    "endpoint_url": "https://s3.source.example.com",
    "aws_access_key_id": "SOURCE_ACCESS_KEY",
    "aws_secret_access_key": "SOURCE_SECRET_KEY",
    "verify_ssl": true
  },
  "destination": {
    "endpoint_url": "https://s3.destination.example.com",
    "aws_access_key_id": "DEST_ACCESS_KEY",
    "aws_secret_access_key": "DEST_SECRET_KEY",
    "verify_ssl": true
  }
}
```

## How your file is merged

s3mirror starts from its defaults and merges your file over them one section at a time. Within a
section, a key you set replaces the default and a key you leave out keeps it. So this sets
`max_workers` and leaves the other four `performance` keys at their defaults:

```yaml
performance:
  max_workers: 8
```

The merge goes one level deep and doesn't check anything. Keys s3mirror doesn't know are kept and
ignored, so a misspelt key such as `delete_extranous` silently does nothing. Values aren't
type-checked either. Run `--show-config` after any change to see what s3mirror will really use:

```bash
s3mirror --config config.yaml --show-config
```

It prints the merged configuration as JSON, after `--workers` and `--no-delete` are applied, with
both secret keys replaced by `***REDACTED***`, and exits 0 without connecting to anything.

## The two endpoints

`source` and `destination` take the same five keys. `endpoint_url` is the service's S3 API address,
including the scheme and any port:

```yaml title="config.yaml"
source:
  endpoint_url: "https://s3.eu-west-2.amazonaws.com"
  aws_access_key_id: "SOURCE_ACCESS_KEY"
  aws_secret_access_key: "SOURCE_SECRET_KEY"
  region_name: "eu-west-2"
  verify_ssl: true

destination:
  endpoint_url: "https://minio.internal.example:9000"
  aws_access_key_id: "DEST_ACCESS_KEY"
  aws_secret_access_key: "DEST_SECRET_KEY"
  verify_ssl: "/etc/ssl/certs/internal-ca.pem"
```

`region_name` defaults to `us-east-1`. Many S3-compatible services ignore it, but it's part of every
request signature, so set it to whatever region the provider tells you to use. On AWS, use the
regional endpoint and the matching region.

s3mirror uses path-style addressing for both endpoints, so the endpoint URL is the service's root,
never a bucket's own hostname.

The keys are passed to `boto3` exactly as written. If you leave one out, its placeholder default
stays and the connection check fails. If you set both keys on a side to `null`, `boto3` falls back
to its usual credential chain for that client (environment variables, `~/.aws/credentials`, an
instance role). The chain is the same for both sides, so that only makes sense for one of them.
Setting just one of the pair to `null` stops the run with `FATAL ERROR: Partial credentials found`
and exit code 1.

`verify_ssl` defaults to `true`, which checks the endpoint's certificate against the system's
trusted CAs. For a private CA or a self-signed certificate, set it to the path of the CA bundle, as
the destination above does; [Safety](/s3mirror/how-it-works/safety/#tls) explains when `false` is
acceptable.

## Choosing what's mirrored

Every source bucket the source credential can list is mirrored, under the same name, unless you
exclude it:

```yaml
sync:
  exclude_buckets:
    - scratch-bucket
    - temporary-exports
```

Names must match exactly; there are no patterns or prefixes. `exclude_buckets` has to be a list: a
single name written as a plain string is read as a set of characters and excludes nothing. Excluded
buckets are skipped on both sides, so their destination copies are neither updated nor deleted
from. The run logs `Excluding 2 bucket(s): scratch-bucket, temporary-exports` when any of them are
on the source.

There's no way to mirror only part of a bucket, or to rename a bucket on the way across. To mirror
a few buckets out of many, give the source credential access to only those, since s3mirror
mirrors whatever `ListBuckets` returns.

## Deletion

```yaml
sync:
  delete_extraneous: false
```

`delete_extraneous` defaults to `true`, so leave it out and runs delete destination objects the
source doesn't have. Write a bare `false`: a quoted `"false"` is a non-empty string, which counts as
true. `--no-delete` turns deletion off for one run whatever the file says. Read
[Deletion](/s3mirror/how-it-works/deletion/) before you leave it on.

## Tuning

The defaults copy 20 objects at once, upload anything from 8 MiB up in 8 MiB parts with up to ten
threads each, and keep up to 50 connections open per endpoint:

```yaml
performance:
  max_workers: 20
  multipart_threshold: 8388608
  multipart_chunksize: 8388608
  max_concurrency: 10
  max_pool_connections: 50
```

All five are plain integers; sizes are in bytes. Some starting points:

- Many small objects: raise `max_workers`, and raise `max_pool_connections` with it so each worker
  can keep a connection.
- A few very large objects: `max_workers` matters less than `max_concurrency` and
  `multipart_chunksize`, because each large object is split into parts and the parts run in
  parallel. s3mirror streams each object without telling the uploader its size, so the part size
  is never raised automatically. AWS allows 10,000 parts per upload, which with the default 8 MiB
  parts caps an object at about 78 GiB; raise `multipart_chunksize` if you have larger ones.
- A rate-limited or shared endpoint: lower `max_workers`, or pass `--workers` for one run.
- Memory: each large object being uploaded can hold up to ten parts in memory at once, so with 20
  workers all on large objects and 8 MiB parts that's up to about 1.6 GiB. Lower `max_workers` or
  `multipart_chunksize` on a small machine.

## Several mirrors

One config file describes one source and one destination. For several pairs, write one file per
pair and run s3mirror once for each, one after another, so they don't compete for bandwidth. Give
each its own `--log-file`.
