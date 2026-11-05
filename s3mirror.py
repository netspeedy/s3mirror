#!/usr/bin/env python3
"""
S3 Bucket Mirror Script
Professional-grade bucket mirroring for S3-compatible storage systems.

Features:
- Command-line arguments for flexible configuration
- Config file support (YAML/JSON)
- Multiple output modes (silent/normal/debug)
- File logging with rotation
- Cron-friendly operation
- Detailed statistics and reporting
"""

import argparse
import difflib
import json
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

import boto3
import botocore
import urllib3
import yaml
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

__version__ = "1.1.0"

# ==========================================
# DEFAULT CONFIGURATION
# ==========================================

DEFAULT_CONFIG = {
    "source": {
        "endpoint_url": "https://s3.source.example.com",
        "aws_access_key_id": "SOURCE_ACCESS_KEY",
        "aws_secret_access_key": "SOURCE_SECRET_KEY",
        "region_name": "us-east-1",
        "verify_ssl": True,
    },
    "destination": {
        "endpoint_url": "https://s3.destination.example.com",
        "aws_access_key_id": "DEST_ACCESS_KEY",
        "aws_secret_access_key": "DEST_SECRET_KEY",
        "region_name": "us-east-1",
        "verify_ssl": True,
    },
    "performance": {
        "max_workers": 20,
        "multipart_threshold": 8_388_608,  # 8MB
        "multipart_chunksize": 8_388_608,  # 8MB
        "max_concurrency": 10,
        "max_pool_connections": 50,
    },
    "sync": {
        "delete_extraneous": True,
        "exclude_buckets": [],
    },
}


# The built-in placeholder key IDs aren't credentials, and seeing one in the output
# is how a config that never set its keys gets noticed.
PLACEHOLDER_KEY_IDS = {
    DEFAULT_CONFIG[side]["aws_access_key_id"] for side in ("source", "destination")
}


def redact_key_id(value):
    """An access key ID shortened for output to its first and last four characters.

    That's enough to tell which key is in use without printing the key. On AWS the
    first four only say what kind of key it is (AKIA long-term, ASIA temporary), the
    last four are what `aws configure list` shows, and the twelve in between stay
    hidden, so the ID can't be used to look up the AWS account it belongs to. A key
    ID shorter than 20 characters is hidden entirely, since four and four would be
    most of it. null, which hands the side to boto3's credential chain, and the
    placeholders are left as they are.
    """
    if value is None or value in PLACEHOLDER_KEY_IDS:
        return value
    value = str(value)
    if len(value) < 20:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


# S3's multipart upload limits. s3transfer can only keep an upload within them when
# it knows the object's size, and s3mirror streams each object without one, so
# part_size_for() picks the part size per object instead.
MAX_PARTS = 10_000
MIN_PART_SIZE = 5 * 1024**2
MAX_PART_SIZE = 5 * 1024**3


def part_size_for(object_size: int, configured: int) -> int:
    """The part size to upload an object with: `configured`, or larger if need be.

    It's raised, in whole MiB, just far enough that the object fits in MAX_PARTS
    parts, and kept between S3's 5 MiB minimum and 5 GiB maximum part size.
    """
    part_size = max(configured, MIN_PART_SIZE)
    needed = -(-object_size // MAX_PARTS)
    if needed > part_size:
        part_size = -(-needed // 1024**2) * 1024**2
    return min(part_size, MAX_PART_SIZE)


class StopRequested(BaseException):
    """Raised in the main thread by SIGINT or SIGTERM, to stop the run.

    It's a BaseException, like KeyboardInterrupt, so the `except Exception` handlers
    that turn a failed call into a logged error don't swallow it.
    """

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def _stop_on_signal(signum, _frame):
    # Stop cleanly on the first signal. A second one, while the transfers already
    # running are finishing, stops at once.
    signal.signal(signal.SIGINT, _stop_now)
    signal.signal(signal.SIGTERM, _stop_now)
    raise StopRequested(signum)


def _stop_now(signum, _frame):
    logging.getLogger("s3mirror").warning(
        "Stopping now, without waiting for the transfers in progress"
    )
    logging.shutdown()
    os._exit(128 + signum)  # pylint: disable=protected-access


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def format(self, record):
        original_levelname = record.levelname
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            levelname = record.levelname
            if levelname in self.COLORS:
                record.levelname = (
                    f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
                )
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class S3Mirror:  # pylint: disable=too-many-instance-attributes
    """High-performance S3 bucket mirroring engine."""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger

        perf = config["performance"]
        self.max_workers = perf["max_workers"]
        self.multipart_threshold = perf["multipart_threshold"]
        self.multipart_chunksize = perf["multipart_chunksize"]
        self.max_concurrency = perf["max_concurrency"]
        self.max_pool_connections = perf["max_pool_connections"]

        self.transfer_config = self._transfer_config(self.multipart_chunksize)

        self.delete_extraneous = config["sync"]["delete_extraneous"]
        self.exclude_buckets = set(config["sync"]["exclude_buckets"])

        self.logger.debug("=" * 70)
        self.logger.debug("INITIALIZATION")
        self.logger.debug("=" * 70)
        self.logger.debug("Source endpoint: %s", config["source"]["endpoint_url"])
        self.logger.debug("Source region: %s", config["source"]["region_name"])
        self.logger.debug(
            "Source access key: %s",
            redact_key_id(config["source"]["aws_access_key_id"]),
        )
        self.logger.debug(
            "Destination endpoint: %s",
            config["destination"]["endpoint_url"],
        )
        self.logger.debug(
            "Destination region: %s", config["destination"]["region_name"]
        )
        self.logger.debug(
            "Destination access key: %s",
            redact_key_id(config["destination"]["aws_access_key_id"]),
        )
        self.logger.debug("Max workers: %d", self.max_workers)
        self.logger.debug(
            "Multipart threshold: %s", self._format_bytes(self.multipart_threshold)
        )
        self.logger.debug(
            "Multipart chunk size: %s", self._format_bytes(self.multipart_chunksize)
        )
        self.logger.debug("Max concurrency: %d", self.max_concurrency)
        self.logger.debug("Connection pool: %d", self.max_pool_connections)
        self.logger.debug("Delete extraneous: %s", self.delete_extraneous)
        self.logger.debug("")

        self.source_client = self._create_client(config["source"], "SOURCE")
        self.dest_client = self._create_client(config["destination"], "DESTINATION")

        self._stats_lock = Lock()
        self.stats = {
            "buckets_processed": 0,
            "buckets_created": 0,
            "buckets_skipped": 0,
            "objects_copied": 0,
            "objects_deleted": 0,
            "bytes_transferred": 0,
            "errors": 0,
            "start_time": time.time(),
        }

    def _transfer_config(self, part_size: int) -> TransferConfig:
        return TransferConfig(
            multipart_threshold=self.multipart_threshold,
            multipart_chunksize=part_size,
            max_concurrency=self.max_concurrency,
            use_threads=True,
            max_io_queue=1000,
        )

    @contextmanager
    def _workers(self):
        """A thread pool that drops the work still queued when the run is stopped.

        On Ctrl+C or SIGTERM the transfers already running are left to finish, so
        none is cut off halfway, and the rest are cancelled.
        """
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            yield executor
        except BaseException as err:
            if isinstance(err, (StopRequested, KeyboardInterrupt)):
                self.logger.warning(
                    "  Stopping: dropping the queued work and waiting for the "
                    "transfers already running"
                )
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        executor.shutdown(wait=True)

    def _create_client(self, endpoint_config: dict, label: str):
        boto_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            max_pool_connections=self.max_pool_connections,
            retries={"max_attempts": 3, "mode": "adaptive"},
            tcp_keepalive=True,
        )

        self.logger.debug("Creating %s client...", label)

        return boto3.client(
            "s3",
            endpoint_url=endpoint_config["endpoint_url"],
            aws_access_key_id=endpoint_config["aws_access_key_id"],
            aws_secret_access_key=endpoint_config["aws_secret_access_key"],
            region_name=endpoint_config["region_name"],
            verify=endpoint_config.get("verify_ssl", True),
            config=boto_config,
        )

    def verify_connections(self) -> bool:
        """Test connectivity to both endpoints."""
        self.logger.debug("=" * 70)
        self.logger.debug("CONNECTION VERIFICATION")
        self.logger.debug("=" * 70)

        # Test source
        self.logger.debug("Testing SOURCE: %s", self.config["source"]["endpoint_url"])
        try:
            response = self.source_client.list_buckets()
            bucket_count = len(response["Buckets"])
            self.logger.info(
                "✓ Source connected successfully (%d buckets)", bucket_count
            )
            self.logger.debug(
                "  Response metadata: %s",
                response["ResponseMetadata"]["HTTPStatusCode"],
            )
            if bucket_count > 0:
                bucket_names = [b["Name"] for b in response["Buckets"][:5]]
                self.logger.debug("  Sample buckets: %s", ", ".join(bucket_names))
                if bucket_count > 5:
                    self.logger.debug("  ... and %d more", bucket_count - 5)
        except botocore.exceptions.ClientError as err:
            self.logger.error("✗ Source connection FAILED")
            self.logger.error("  Error code: %s", err.response["Error"]["Code"])
            self.logger.error("  Error message: %s", err.response["Error"]["Message"])
            self.logger.error(
                "  HTTP status: %s",
                err.response["ResponseMetadata"]["HTTPStatusCode"],
            )
            return False
        except Exception as err:  # pylint: disable=broad-except
            self.logger.error("✗ Source connection error: %s", err)
            return False

        # Test destination
        self.logger.debug(
            "Testing DESTINATION: %s", self.config["destination"]["endpoint_url"]
        )
        try:
            response = self.dest_client.list_buckets()
            bucket_count = len(response["Buckets"])
            self.logger.info(
                "✓ Destination connected successfully (%d buckets)", bucket_count
            )
            self.logger.debug(
                "  Response metadata: %s",
                response["ResponseMetadata"]["HTTPStatusCode"],
            )
        except botocore.exceptions.ClientError as err:
            self.logger.error("✗ Destination connection FAILED")
            self.logger.error("  Error code: %s", err.response["Error"]["Code"])
            self.logger.error("  Error message: %s", err.response["Error"]["Message"])
            self.logger.error(
                "  HTTP status: %s",
                err.response["ResponseMetadata"]["HTTPStatusCode"],
            )
            return False
        except Exception as err:  # pylint: disable=broad-except
            self.logger.error("✗ Destination connection error: %s", err)
            return False

        self.logger.debug("")
        return True

    def get_source_buckets(self) -> Optional[List[str]]:
        """Return the source's bucket names, or None if they couldn't be listed."""
        try:
            response = self.source_client.list_buckets()
        except (
            botocore.exceptions.BotoCoreError,
            botocore.exceptions.ClientError,
        ) as err:
            self.logger.error("Failed to list source buckets: %s", err)
            self.stats["errors"] += 1
            return None

        all_buckets = [b["Name"] for b in response["Buckets"]]
        buckets = [b for b in all_buckets if b not in self.exclude_buckets]

        if self.exclude_buckets:
            excluded = [b for b in all_buckets if b in self.exclude_buckets]
            if excluded:
                self.logger.info(
                    "Excluding %d bucket(s): %s", len(excluded), ", ".join(excluded)
                )
                self.logger.debug("  Excluded buckets: %s", excluded)

        self.logger.debug("Total buckets to sync: %d", len(buckets))
        return buckets

    def bucket_exists(self, bucket_name: str) -> Optional[bool]:
        """Check whether the bucket exists on the destination.

        Only a 404 means it doesn't. Anything else, such as a 403 for a bucket the
        credential can't see, returns None, because creating a bucket on the strength
        of it would be a guess.
        """
        try:
            self.dest_client.head_bucket(Bucket=bucket_name)
            return True
        except botocore.exceptions.ClientError as err:
            error = err.response.get("Error", {})
            status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404 or error.get("Code") in {"404", "NoSuchBucket"}:
                return False
            self.logger.error("  ✗ Failed to check bucket on destination: %s", err)
            return None
        except botocore.exceptions.BotoCoreError as err:
            self.logger.error("  ✗ Failed to check bucket on destination: %s", err)
            return None

    def create_bucket(self, bucket_name: str) -> bool:
        """Create bucket on destination, in the destination client's region."""
        params = {"Bucket": bucket_name}
        # AWS creates a bucket in us-east-1 when there's no location constraint, and
        # rejects one that names us-east-1. Every other region has to be named, and
        # must match the region the request is signed for.
        region = self.dest_client.meta.region_name
        if region and region not in {"us-east-1", "aws-global"}:
            params["CreateBucketConfiguration"] = {"LocationConstraint": region}
        try:
            self.logger.debug(
                "  Creating bucket on destination in %s...",
                region or "the default region",
            )
            self.dest_client.create_bucket(**params)
            self.logger.info("  ✓ Created bucket: %s", bucket_name)
            self.stats["buckets_created"] += 1
            return True
        except botocore.exceptions.ClientError as err:
            self.logger.error("  ✗ Failed to create bucket: %s", err)
            self.logger.debug("    Error details: %s", err.response)
            self.stats["errors"] += 1
            return False
        except botocore.exceptions.BotoCoreError as err:
            self.logger.error("  ✗ Failed to create bucket: %s", err)
            self.stats["errors"] += 1
            return False

    def list_objects(
        self, client, bucket_name: str, label: str
    ) -> Optional[Dict[str, int]]:
        """List every object in a bucket as {key: size}.

        Returns None if the listing didn't complete, which is never the same as an
        empty bucket: a partial listing would make the missing keys look extraneous.
        """
        objects: Dict[str, int] = {}
        page_count = 0
        self.logger.debug("  Listing %s objects...", label)
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket_name):
                page_count += 1
                for obj in page.get("Contents", []):
                    objects[obj["Key"]] = obj["Size"]
        except (
            botocore.exceptions.BotoCoreError,
            botocore.exceptions.ClientError,
        ) as err:
            self.logger.error(
                "  Failed to list objects in %s on the %s: %s", bucket_name, label, err
            )
            self.logger.debug(
                "    Listed %d objects across %d page(s) before the failure",
                len(objects),
                page_count,
            )
            return None

        self.logger.debug(
            "    Found %d objects across %d page(s)", len(objects), page_count
        )

        if objects:
            sizes = list(objects.values())
            total_size = sum(sizes)
            avg_size = total_size / len(sizes)
            self.logger.debug("    Total size: %s", self._format_bytes(total_size))
            self.logger.debug("    Average size: %s", self._format_bytes(int(avg_size)))
            self.logger.debug("    Largest: %s", self._format_bytes(max(sizes)))
            self.logger.debug("    Smallest: %s", self._format_bytes(min(sizes)))

        return objects

    def copy_object(self, bucket: str, key: str, size: int) -> bool:
        """Transfer single object from source to destination."""
        body = None
        try:
            transfer_config = self.transfer_config
            part_size = part_size_for(size, self.multipart_chunksize)
            if part_size != self.multipart_chunksize:
                transfer_config = self._transfer_config(part_size)
                if size >= self.multipart_threshold:
                    self.logger.debug(
                        "    Using %s parts for %s [%s]",
                        self._format_bytes(part_size),
                        key,
                        self._format_bytes(size),
                    )

            response = self.source_client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]

            self.dest_client.upload_fileobj(
                body,
                bucket,
                key,
                Config=transfer_config,
            )

            with self._stats_lock:
                self.stats["bytes_transferred"] += size

            size_str = self._format_bytes(size)
            if size >= self.multipart_threshold:
                self.logger.debug("    ✓ %s [%s] (multipart)", key, size_str)
            else:
                self.logger.debug("    ✓ %s [%s]", key, size_str)

            return True
        except Exception as err:  # pylint: disable=broad-except
            self.logger.error("    ✗ Failed to copy %s: %s", key, err)
            return False
        finally:
            if body is not None:
                body.close()

    def delete_object(self, bucket: str, key: str) -> bool:
        """Remove object from destination."""
        try:
            self.dest_client.delete_object(Bucket=bucket, Key=key)
            self.logger.debug("    ✓ Deleted: %s", key)
            return True
        except botocore.exceptions.ClientError as err:
            self.logger.error("    ✗ Failed to delete %s: %s", key, err)
            return False

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        """Convert bytes to human-readable format."""
        value = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024.0:
                return f"{value:.1f}{unit}"
            value /= 1024.0
        return f"{value:.1f}PB"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Convert seconds to readable duration."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            return f"{seconds/60:.1f}m"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

    def _calculate_differences(
        self,
        src_objects: Dict[str, int],
        dest_objects: Dict[str, int],
    ) -> Tuple[List[Tuple[str, int]], Set[str], int]:
        """Determine what to copy and delete, and total bytes to copy."""
        to_copy: List[Tuple[str, int]] = []
        to_delete: Set[str] = set()
        total_copy_bytes = 0

        for key, size in src_objects.items():
            if key not in dest_objects:
                to_copy.append((key, size))
                total_copy_bytes += size
                self.logger.debug(
                    "    New file: %s (%s)", key, self._format_bytes(size)
                )
            elif dest_objects[key] != size:
                to_copy.append((key, size))
                total_copy_bytes += size
                self.logger.debug(
                    "    Changed: %s (src:%s != dst:%s)",
                    key,
                    self._format_bytes(size),
                    self._format_bytes(dest_objects[key]),
                )

        if self.delete_extraneous:
            extra = set(dest_objects.keys()) - set(src_objects.keys())
            if extra:
                to_delete = extra
                self.logger.debug("  Files to delete: %d", len(to_delete))
                for k in list(to_delete)[:5]:
                    self.logger.debug("    - %s", k)
                if len(to_delete) > 5:
                    self.logger.debug("    ... and %d more", len(to_delete) - 5)

        return to_copy, to_delete, total_copy_bytes

    def _run_parallel_copy(
        self,
        bucket_name: str,
        to_copy: List[Tuple[str, int]],
        total_copy_bytes: int,
    ) -> Tuple[int, int]:
        """Execute parallel object copies and return (success, failed)."""
        if not to_copy:
            return 0, 0

        self.logger.debug("  Starting parallel copy (%d workers)...", self.max_workers)
        copy_start = time.time()
        success = 0
        failed = 0

        with self._workers() as executor:
            futures = {
                executor.submit(self.copy_object, bucket_name, key, size): (key, size)
                for key, size in to_copy
            }

            completed = 0
            for future in as_completed(futures):
                completed += 1
                if future.result():
                    success += 1
                    self.stats["objects_copied"] += 1
                else:
                    failed += 1
                    self.stats["errors"] += 1

                if completed % 50 == 0:
                    progress_pct = (completed / len(to_copy)) * 100
                    self.logger.debug(
                        "  Progress: %d/%d (%.0f%%) - %d ok, %d failed",
                        completed,
                        len(to_copy),
                        progress_pct,
                        success,
                        failed,
                    )

        copy_duration = time.time() - copy_start
        throughput = total_copy_bytes / copy_duration if copy_duration > 0 else 0.0
        self.logger.info(
            "  ✓ Copied %d objects in %.1fs (%s/s)",
            success,
            copy_duration,
            self._format_bytes(int(throughput)),
        )
        if failed > 0:
            self.logger.warning("  ⚠ %d objects failed to copy", failed)

        return success, failed

    def sync_bucket(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self, bucket_name: str, bucket_num: int, total_buckets: int
    ) -> None:
        """Synchronize single bucket from source to destination."""
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("[%d/%d]: %s", bucket_num, total_buckets, bucket_name)
        self.logger.info("=" * 70)

        bucket_start = time.time()

        self.logger.debug("  Checking if bucket exists on destination...")
        exists = self.bucket_exists(bucket_name)
        if exists is None:
            self.logger.warning("  Skipping bucket due to HeadBucket failure")
            self.stats["buckets_skipped"] += 1
            self.stats["errors"] += 1
            return
        if exists:
            self.logger.debug("  Bucket already exists on destination")
        elif not self.create_bucket(bucket_name):
            self.logger.warning("  Skipping bucket due to creation failure")
            self.stats["buckets_skipped"] += 1
            return

        # Mirror nothing in a bucket whose listing on either side didn't finish. A
        # partial source listing would make the unlisted keys look extraneous, and a
        # partial destination listing would copy objects that are already there.
        src_objects = self.list_objects(self.source_client, bucket_name, "source")
        dest_objects = None
        if src_objects is not None:
            dest_objects = self.list_objects(
                self.dest_client, bucket_name, "destination"
            )
        if src_objects is None or dest_objects is None:
            self.logger.warning("  Skipping bucket due to listing failure")
            self.stats["buckets_skipped"] += 1
            self.stats["errors"] += 1
            return

        self.logger.info("  Source: %d objects", len(src_objects))
        self.logger.info("  Destination: %d objects", len(dest_objects))

        # Calculate differences
        self.logger.debug("  Calculating differences...")
        to_copy, to_delete, total_copy_bytes = self._calculate_differences(
            src_objects, dest_objects
        )

        if not to_copy and not to_delete:
            self.logger.info("  ✓ Already synchronized (no changes needed)")
            self.stats["buckets_processed"] += 1
            bucket_duration = time.time() - bucket_start
            self.logger.debug("  Bucket processing time: %.1fs", bucket_duration)
            return

        self.logger.info(
            "  Actions: %d to copy (%s), %d to delete",
            len(to_copy),
            self._format_bytes(total_copy_bytes),
            len(to_delete),
        )

        success_copies, _failed_copies = self._run_parallel_copy(
            bucket_name, to_copy, total_copy_bytes
        )

        if to_delete:
            self.logger.debug(
                "  Starting parallel delete (%d workers)...", self.max_workers
            )
            delete_start = time.time()
            success_del = 0
            failed_del = 0

            with self._workers() as executor:
                futures = {
                    executor.submit(self.delete_object, bucket_name, key): key
                    for key in to_delete
                }
                for future in as_completed(futures):
                    if future.result():
                        success_del += 1
                        self.stats["objects_deleted"] += 1
                    else:
                        failed_del += 1
                        self.stats["errors"] += 1

            delete_duration = time.time() - delete_start
            self.logger.info(
                "  ✓ Deleted %d objects in %.1fs", success_del, delete_duration
            )
            if failed_del > 0:
                self.logger.warning("  ⚠ %d objects failed to delete", failed_del)

        bucket_duration = time.time() - bucket_start
        self.logger.info("  ✓ Bucket completed in %.1fs", bucket_duration)
        self.logger.debug(
            "  Bucket stats: copied=%d, deleted=%d, errors=%d",
            success_copies,
            self.stats["objects_deleted"],
            self.stats["errors"],
        )
        self.stats["buckets_processed"] += 1

    def mirror_all_buckets(self) -> None:
        """Execute full mirror operation across all buckets."""
        self.logger.debug("=" * 70)
        self.logger.debug("BUCKET DISCOVERY")
        self.logger.debug("=" * 70)

        buckets = self.get_source_buckets()

        if buckets is None:
            return

        if not buckets:
            self.logger.warning("No buckets found to sync")
            return

        self.logger.info("")
        self.logger.info("Starting synchronization of %d bucket(s)", len(buckets))
        self.logger.info(
            "Performance: %d workers, %s multipart threshold",
            self.max_workers,
            self._format_bytes(self.multipart_threshold),
        )

        for idx, bucket in enumerate(buckets, 1):
            self.sync_bucket(bucket, idx, len(buckets))

    def print_summary(self) -> None:
        """Generate and log final summary report."""
        duration = time.time() - self.stats["start_time"]

        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("FINAL SUMMARY")
        self.logger.info("=" * 70)
        self.logger.info(
            "Started:  %s",
            datetime.fromtimestamp(self.stats["start_time"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        )
        self.logger.info("Finished: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.logger.info(
            "Duration: %.1fs (%s)", duration, self._format_duration(duration)
        )
        self.logger.info("")
        self.logger.info("Buckets:")
        self.logger.info("  - Processed: %d", self.stats["buckets_processed"])
        self.logger.info("  - Created:   %d", self.stats["buckets_created"])
        if self.stats["buckets_skipped"] > 0:
            self.logger.info("  - Skipped:   %d", self.stats["buckets_skipped"])
        self.logger.info("")
        self.logger.info("Objects:")
        self.logger.info("  - Copied:    %d", self.stats["objects_copied"])
        self.logger.info("  - Deleted:   %d", self.stats["objects_deleted"])
        self.logger.info("")
        self.logger.info(
            "Data transferred: %s",
            self._format_bytes(self.stats["bytes_transferred"]),
        )

        if duration > 0 and self.stats["bytes_transferred"] > 0:
            throughput = self.stats["bytes_transferred"] / duration
            self.logger.info(
                "Average throughput: %s/s",
                self._format_bytes(int(throughput)),
            )

        self.logger.info("")
        if self.stats["errors"] > 0:
            self.logger.warning("⚠ Errors encountered: %d", self.stats["errors"])
            self.logger.info("Status: COMPLETED WITH ERRORS")
        else:
            self.logger.info("✓ Status: COMPLETED SUCCESSFULLY")

        self.logger.info("=" * 70)


def setup_logging(args: argparse.Namespace) -> logging.Logger:
    """Configure logging with appropriate handlers and formatters."""
    logger = logging.getLogger("s3mirror")
    logger.setLevel(logging.DEBUG)

    logger.handlers.clear()

    if args.log_file and not args.debug:
        console_level = logging.ERROR
    elif args.quiet:
        console_level = logging.ERROR
    elif args.debug:
        console_level = logging.DEBUG
    else:
        console_level = logging.INFO

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)

    if args.debug:
        console_format = ColoredFormatter("[%(levelname)s] %(message)s")
    else:
        console_format = logging.Formatter("%(message)s")

    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file, mode="a")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

        logger.info("")
        logger.info("#" * 70)
        logger.info("# NEW SESSION: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("#" * 70)

    return logger


class ConfigError(ValueError):
    """Config values s3mirror won't run with, one problem per line."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("\n".join(self.problems))

    def report(self, path) -> str:
        """The message for standard error: one line, or one line per problem."""
        if len(self.problems) == 1:
            return f"Error: Invalid config in {path}: {self.problems[0]}"
        return "\n  ".join([f"Error: Invalid config in {path}:", *self.problems])


def config_bool(value, name: str) -> bool:
    """Read a boolean config value: a real boolean, or the string true or false.

    Anything else is an error rather than a truth test, because a quoted "false" is
    a non-empty string, and reading it as true would leave deletion on.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ConfigError(f"{name} must be true or false, not {value!r}")


def _unknown_key(name: str, known) -> str:
    """The problem for a key s3mirror doesn't know, with the likely intended one."""
    problem = f"{name} isn't a config key"
    prefix, _, key = name.rpartition(".")
    match = difflib.get_close_matches(key, sorted(known), n=1)
    if match:
        problem += f"; did you mean {prefix + '.' if prefix else ''}{match[0]}?"
    return problem


def _check_endpoint(side: str, section: dict, problems: List[str]) -> None:
    """Check one side's endpoint and credentials."""
    for key in ("endpoint_url", "aws_access_key_id", "aws_secret_access_key"):
        value = section[key]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            problems.append(f"{side}.{key} must be a string, or null, not {value!r}")
    url = section["endpoint_url"]
    if isinstance(url, str) and not url.lower().startswith(("http://", "https://")):
        problems.append(
            f"{side}.endpoint_url must be a URL starting with http:// or https://, "
            f"not {url!r}"
        )
    region = section["region_name"]
    if region is not None and (not isinstance(region, str) or not region.strip()):
        problems.append(f"{side}.region_name must be a string, or null, not {region!r}")
    if (section["aws_access_key_id"] is None) != (
        section["aws_secret_access_key"] is None
    ):
        problems.append(
            f"{side}.aws_access_key_id and {side}.aws_secret_access_key must both be "
            "set, or both be null to use boto3's credential chain"
        )


def _check_verify_ssl(side: str, section: dict, problems: List[str]) -> None:
    """Read verify_ssl: a boolean, the string true or false, or a CA bundle path."""
    verify = section["verify_ssl"]
    if isinstance(verify, bool):
        return
    expected = f"{side}.verify_ssl must be true, false or the path to a CA bundle"
    if not isinstance(verify, str) or not verify.strip():
        problems.append(f"{expected}, not {verify!r}")
    elif verify.strip().lower() in {"true", "false"}:
        section["verify_ssl"] = verify.strip().lower() == "true"
    elif not Path(verify).exists():
        problems.append(f"{expected}, and {verify!r} doesn't exist")


def _check_sync(sync: dict, problems: List[str]) -> None:
    """Read delete_extraneous strictly and check exclude_buckets is a list of names."""
    try:
        sync["delete_extraneous"] = config_bool(
            sync["delete_extraneous"], "sync.delete_extraneous"
        )
    except ConfigError as err:
        problems.extend(err.problems)
    buckets = sync["exclude_buckets"]
    if not isinstance(buckets, list) or not all(
        isinstance(bucket, str) and bucket for bucket in buckets
    ):
        problems.append(
            f"sync.exclude_buckets must be a list of bucket names, not {buckets!r}"
        )


def _check_sections(config: dict, problems: List[str]) -> Dict[str, dict]:
    """Check every section and key is one s3mirror knows, returning the mappings."""
    problems += [
        _unknown_key(name, DEFAULT_CONFIG)
        for name in config
        if name not in DEFAULT_CONFIG
    ]
    sections = {}
    for name, defaults in DEFAULT_CONFIG.items():
        section = config.get(name)
        if not isinstance(section, dict):
            problems.append(f"{name} must be a mapping of keys, not {section!r}")
            continue
        sections[name] = section
        problems += [
            _unknown_key(f"{name}.{key}", defaults)
            for key in section
            if key not in defaults
        ]
    return sections


def _check_performance(performance: dict, problems: List[str]) -> None:
    """Every performance value is a count or a size, so a whole number above 0."""
    for key in DEFAULT_CONFIG["performance"]:
        value = performance[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            problems.append(
                f"performance.{key} must be a whole number of at least 1, not {value!r}"
            )


def validate_config(config: dict) -> dict:
    """Check the merged config, normalising the values it accepts.

    Raises ConfigError listing every problem, so a config that s3mirror would
    otherwise misread, ignore part of, or fail on halfway through a run never gets
    as far as connecting.
    """
    problems: List[str] = []
    sections = _check_sections(config, problems)
    for side in ("source", "destination"):
        if side in sections:
            _check_endpoint(side, sections[side], problems)
            _check_verify_ssl(side, sections[side], problems)
    if "performance" in sections:
        _check_performance(sections["performance"], problems)
    if "sync" in sections:
        _check_sync(sections["sync"], problems)

    if problems:
        raise ConfigError(problems)
    return config


def load_config(config_path: Optional[str]) -> dict:
    """Load configuration from file or use defaults."""
    if not config_path:
        return deepcopy(DEFAULT_CONFIG)

    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_file, "r", encoding="utf-8") as file:
            config_suffix = config_file.suffix.lower()
            if config_suffix == ".json":
                user_config = json.load(file)
            elif config_suffix in {".yaml", ".yml"}:
                user_config = yaml.safe_load(file)
            else:
                print(
                    "Error: Unsupported config format. Use .yaml, .yml or .json",
                    file=sys.stderr,
                )
                sys.exit(1)

        if user_config is None:
            user_config = {}

        if not isinstance(user_config, dict):
            print(
                "Error: Config file must contain a top-level mapping", file=sys.stderr
            )
            sys.exit(1)

        config = deepcopy(DEFAULT_CONFIG)
        for key, value in user_config.items():
            if isinstance(config.get(key), dict) and isinstance(value, dict):
                config[key].update(value)
            else:
                config[key] = value

    except Exception as err:  # pylint: disable=broad-except
        print(f"Error loading config file: {err}", file=sys.stderr)
        sys.exit(1)

    try:
        return validate_config(config)
    except ConfigError as err:
        print(err.report(config_path), file=sys.stderr)
        sys.exit(1)


def redacted_config(config: dict) -> dict:
    """A copy of the config that's safe to print, for --show-config."""
    display_config = json.loads(json.dumps(config))
    for side in ("source", "destination"):
        section = display_config[side]
        section["aws_access_key_id"] = redact_key_id(section["aws_access_key_id"])
        section["aws_secret_access_key"] = "***REDACTED***"
    return display_config


def tls_verified(verify) -> bool:
    """Whether boto3 checks certificates when given this verify_ssl value."""
    return verify is None or bool(verify)


def positive_int(value: str) -> int:
    """Parse an argparse value that must be a positive integer."""
    try:
        parsed = int(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError("must be an integer") from err

    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")

    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser, without parsing anything."""
    parser = argparse.ArgumentParser(
        description="S3 Bucket Mirror - Professional bucket synchronization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Normal operation (console output)
  %(prog)s --config /etc/s3mirror.yaml

  # Try it first without deleting anything, showing every decision
  %(prog)s --config /etc/s3mirror.yaml --no-delete --debug

  # Silent mode for cron
  %(prog)s --config /etc/s3mirror.yaml --quiet

  # Log to file (only errors on the console, everything in the file)
  %(prog)s --config /etc/s3mirror.yaml --log-file /var/log/s3mirror.log

  # Log to file with debug console output too
  %(prog)s --config /etc/s3mirror.yaml --debug --log-file /var/log/s3mirror.log
        """,
    )

    parser.add_argument(
        "-c",
        "--config",
        metavar="FILE",
        help="Configuration file path (.yaml, .yml or .json)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode - only errors (for cron)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Debug mode - verbose output",
    )
    parser.add_argument(
        "-l",
        "--log-file",
        metavar="FILE",
        help="Log to file (console shows only errors unless --debug specified)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=positive_int,
        metavar="N",
        help="Number of parallel workers (default: max_workers, 20 if unset)",
    )
    parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Don't delete extraneous files from destination",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Display configuration and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"S3 Mirror v{__version__}",
    )

    return parser


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    return build_parser().parse_args()


def main():
    """Main application entry point."""
    args = parse_arguments()

    config = load_config(args.config)

    if args.workers is not None:
        config["performance"]["max_workers"] = args.workers

    if args.no_delete:
        config["sync"]["delete_extraneous"] = False

    if args.show_config:
        print(json.dumps(redacted_config(config), indent=2))
        sys.exit(0)

    logger = setup_logging(args)

    logger.info("=" * 70)
    logger.info("S3 BUCKET MIRROR")
    logger.info("Session started: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # urllib3 warns on every request made without certificate checks. Say it once
    # per endpoint instead, and only for one that really has them off: botocore
    # verifies when verify is None, and a CA bundle path verifies too.
    unverified = [
        label
        for label in ("source", "destination")
        if not tls_verified(config[label].get("verify_ssl", True))
    ]
    if unverified:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    for label in unverified:
        logger.warning("⚠ TLS certificate verification is off for the %s", label)

    # SIGTERM, from kill, systemctl stop or docker stop, is handled like Ctrl+C.
    # Without a handler it ends the run mid-transfer, and in a container, where
    # s3mirror is process 1, the kernel ignores it altogether.
    previous = {
        signum: signal.signal(signum, _stop_on_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        mirror = S3Mirror(config, logger)

        if not mirror.verify_connections():
            logger.error("Connection verification failed - aborting")
            sys.exit(1)

        mirror.mirror_all_buckets()
        mirror.print_summary()

        sys.exit(1 if mirror.stats["errors"] > 0 else 0)

    except (StopRequested, KeyboardInterrupt) as stop:
        signum = getattr(stop, "signum", signal.SIGINT)
        if signum == signal.SIGINT:
            logger.warning("\n\nOperation cancelled by user (Ctrl+C)")
        else:
            logger.warning("Operation stopped by %s", signal.Signals(signum).name)
        sys.exit(128 + signum)
    except Exception as err:  # pylint: disable=broad-except
        logger.exception("FATAL ERROR: %s", err)
        sys.exit(1)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
