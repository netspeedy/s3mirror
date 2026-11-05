---
title: Config keys
description: Every key in s3mirror's four config sections, with its default and what reads it.
---

The config file is YAML (`.yaml`, `.yml`) or JSON (`.json`) with four sections. Your file is merged
over the defaults one section at a time, so you only need the keys you want to change, and
`--show-config` prints the result. [Configuration](/s3mirror/guides/configuration/) explains the
merge and walks through building a file.

This file sets every key:

```yaml title="config.yaml"
source:
  endpoint_url: "https://s3.source.example.com"
  aws_access_key_id: "SOURCE_ACCESS_KEY"
  aws_secret_access_key: "SOURCE_SECRET_KEY"
  region_name: "us-east-1"
  verify_ssl: true

destination:
  endpoint_url: "https://s3.destination.example.com"
  aws_access_key_id: "DEST_ACCESS_KEY"
  aws_secret_access_key: "DEST_SECRET_KEY"
  region_name: "us-east-1"
  verify_ssl: true

performance:
  max_workers: 20
  multipart_threshold: 8388608
  multipart_chunksize: 8388608
  max_concurrency: 10
  max_pool_connections: 50

sync:
  delete_extraneous: false
  exclude_buckets:
    - scratch-bucket
    - temporary-exports
```

`delete_extraneous` and `verify_ssl` are checked when the file is loaded, and a value s3mirror
can't read stops it with `Error: Invalid config in <file>: ...` and exit code 1 before it connects.
The other values aren't checked yet. A key s3mirror doesn't know is kept and ignored, and a value of
the wrong type fails later, during the run, or quietly does the wrong thing. The notes below say
where that matters.

## `source` and `destination`

Both sections take the same keys. Each one configures one `boto3` S3 client.

| Key | Default | Description |
| --- | --- | --- |
| `endpoint_url` | `https://s3.source.example.com`, `https://s3.destination.example.com` | The S3 API endpoint, with scheme and any port. Requests use path-style addressing against it. |
| `aws_access_key_id` | `SOURCE_ACCESS_KEY`, `DEST_ACCESS_KEY` | Access key for the endpoint. Debug output and `--show-config` show only its first and last four characters, or `***` if it's shorter than 20. |
| `aws_secret_access_key` | `SOURCE_SECRET_KEY`, `DEST_SECRET_KEY` | Secret key for the endpoint. Never logged, and redacted by `--show-config`. |
| `region_name` | `us-east-1` | Region used to sign requests, and on the destination, the region missing buckets are created in. Many non-AWS services ignore it but still need one. |
| `verify_ssl` | `true` | TLS certificate verification, passed to `boto3` as `verify`: `true`, `false` (or those as strings, in any case), or the path to a CA bundle file or directory that exists. |

The defaults are placeholders, so a working config sets at least the endpoint and both keys on each
side. With both keys on a side set to `null`, `boto3` uses its own credential chain for that client;
with only one of them `null`, the run stops with `FATAL ERROR: Partial credentials found` and exit
code 1.

When `verify_ssl` is `false` on a side, s3mirror logs one warning saying so for that endpoint and
turns off `urllib3`'s per-request insecure-request warnings. Up to 1.0.4 the default was `false`;
[Safety](/s3mirror/how-it-works/safety/#tls) has what that means for an existing config.

## `performance`

| Key | Default | Description |
| --- | --- | --- |
| `max_workers` | `20` | Objects copied at the same time within a bucket, and later objects deleted. `--workers` overrides it. |
| `multipart_threshold` | `8388608` (8 MiB) | Size in bytes from which an object is uploaded as a multipart upload. |
| `multipart_chunksize` | `8388608` (8 MiB) | Size in bytes of each multipart part. For an object that would need more than S3's 10,000 parts, about 78 GiB at the default, s3mirror uses the smallest whole number of MiB that fits. Kept between 5 MiB and 5 GiB, S3's limits. |
| `max_concurrency` | `10` | Threads each object's upload can use for its parts. |
| `max_pool_connections` | `50` | HTTP connections each client keeps open. Applies to the source and destination clients separately. |

All five must be integers. A quoted number such as `"20"` gets past loading and stops the run with
`FATAL ERROR` when it's first used.

## `sync`

| Key | Default | Description |
| --- | --- | --- |
| `delete_extraneous` | `true` | Delete destination objects whose keys the source bucket doesn't have. `--no-delete` sets it to `false` for one run. |
| `exclude_buckets` | `[]` | Source bucket names to skip entirely, on both sides. Exact names only. |

`delete_extraneous` must be `true` or `false`, as a boolean or as a string in any case; anything
else, `0`, `"no"` and `null` included, is a config error. `exclude_buckets` must be a list: a plain
string is read as a set of single characters and excludes nothing.

## Not configurable

These are fixed in the code:

- Signature Version 4 and path-style addressing for both clients
- botocore's adaptive retry mode, with up to three retries per request
- TCP keepalive on every connection
- no prefix, key or object filters, and no bucket renaming
- no way to set metadata, storage class, ACLs or encryption on copied objects
