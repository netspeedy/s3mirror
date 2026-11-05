---
title: Safety
description: The permissions each side needs, TLS verification, where the secrets live, and the checks to make before a run that can delete.
---

s3mirror writes to the destination and, with deletion on, removes from it. It can't change
anything at the source: it only lists and reads there. The risks are all on the destination side,
and most of them come down to three things: the credentials you give it, whether TLS is verified,
and what you check before letting it delete.

## Permissions

Give s3mirror its own credential on each side, with only what a mirror needs. In AWS IAM terms:

| Side | Actions | Used for |
| --- | --- | --- |
| Source | `s3:ListAllMyBuckets` | The connection check and bucket discovery |
| Source | `s3:ListBucket` on each mirrored bucket | Listing its objects |
| Source | `s3:GetObject` on each mirrored bucket's objects | Reading each object it copies |
| Destination | `s3:ListAllMyBuckets` | The connection check |
| Destination | `s3:ListBucket` on each mirrored bucket | `HeadBucket` and listing its objects; without it, the bucket is skipped |
| Destination | `s3:CreateBucket` | Only if s3mirror should create missing buckets |
| Destination | `s3:PutObject` on each mirrored bucket's objects | Single and multipart uploads |
| Destination | `s3:AbortMultipartUpload` on each mirrored bucket's objects | Cleaning up a multipart upload that failed |
| Destination | `s3:DeleteObject` on each mirrored bucket's objects | Only if deletion is on |

Other providers name these differently, but most offer the same split between listing, reading,
writing and deleting. s3mirror never writes to the source, but a read-only source credential still
matters: if the `source` and `destination` sections are ever swapped by mistake, it's what stops the
run overwriting and deleting your real data. A destination credential without `s3:DeleteObject` turns deletion into
logged errors rather than lost data, and each refused delete is counted, so the run exits 1.

Make sure the source credential can list every bucket it can see. A bucket that shows up in
`ListBuckets` but can't be listed is skipped, with nothing copied or deleted, and counted as an
error on every run; [Deletion](/s3mirror/how-it-works/deletion/#when-a-listing-fails) has the
details.

## TLS

`verify_ssl` defaults to `true` for both endpoints, so s3mirror checks each endpoint's certificate
against the system's trusted CAs and refuses to connect if it doesn't verify. That's what any hosted
provider needs. For a private CA, the value is passed straight to `boto3` as its `verify` argument,
so a path to a CA bundle works too. For a self-signed certificate, the certificate file itself
usually works as the bundle:

```yaml title="config.yaml"
destination:
  endpoint_url: "https://minio.internal.example:9000"
  aws_access_key_id: "DEST_ACCESS_KEY"
  aws_secret_access_key: "DEST_SECRET_KEY"
  verify_ssl: "/etc/ssl/certs/internal-ca.pem"
```

`verify_ssl: false` turns the check off for that endpoint, so s3mirror accepts any certificate,
including one presented by something in the middle. Use it only when you can't get the CA bundle,
and only on a network you trust. Each run then logs
`⚠ TLS certificate verification is off for the source` (or `destination`) once, after the banner,
in place of the warning `urllib3` would otherwise print for every request.

:::caution[The default was `false` up to 1.0.4]
Up to and including 1.0.4, `verify_ssl` defaulted to `false`. A config that leaves it out and
points at an endpoint with a self-signed or private-CA certificate now fails the connection check
with `CERTIFICATE_VERIFY_FAILED`. Set `verify_ssl` to the CA bundle, or to `false`, for that
endpoint.
:::

## Secrets

Both secret keys live in the config file in plain text. Keep it readable only by the account that
runs s3mirror (`chmod 600`), and out of version control.

`--show-config` replaces both secret keys with `***REDACTED***`, but prints the access key IDs in
full. Debug output and log files show only the first and last four characters of each access key
ID, and never the secret keys.

## Before a run that can delete

1. Run with `--no-delete --debug` and read the output: the bucket list, the object counts on each
   side and the `Actions:` line for each bucket.
2. Add any bucket the destination should keep to itself, or that's temporary or test-only, to
   `exclude_buckets`. Buckets that exist only at the destination are already safe.
3. Turn on versioning at the destination, or keep an independent backup of anything you can't
   lose. s3mirror's deletions are plain `DeleteObject` calls.
4. Try new endpoints and credential changes against a non-production bucket first.
5. For scheduled runs, use `--log-file` and alert on a non-zero exit code.
