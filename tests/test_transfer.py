"""Part sizes for multipart uploads, which S3 caps at 10,000 parts."""

import logging
import math
from copy import deepcopy

import pytest

import s3mirror

MIB = 1024**2
GIB = 1024**3
TIB = 1024**4
DEFAULT_PART = s3mirror.DEFAULT_CONFIG["performance"]["multipart_chunksize"]


@pytest.mark.parametrize(
    "size",
    [0, 1, 8 * MIB, 10_000 * DEFAULT_PART, 10_000 * DEFAULT_PART + 1, 80 * GIB, TIB],
)
def test_every_object_fits_in_10000_parts(size):
    """Sizes either side of 10,000 default parts (about 78 GiB), and well past it."""
    part = s3mirror.part_size_for(size, DEFAULT_PART)

    assert math.ceil(size / part) <= 10_000
    assert part >= DEFAULT_PART
    assert part % MIB == 0


def test_the_largest_object_stays_within_the_part_size_limit():
    """S3's 5 TiB object limit fits in 10,000 parts of well under 5 GiB."""
    part = s3mirror.part_size_for(5 * TIB, DEFAULT_PART)

    assert math.ceil(5 * TIB / part) <= 10_000
    assert part <= 5 * GIB


def test_the_configured_part_size_is_kept_when_it_fits():
    """Up to about 78 GiB, the default 8 MiB parts are used unchanged."""
    assert s3mirror.part_size_for(10_000 * DEFAULT_PART, DEFAULT_PART) == DEFAULT_PART
    assert s3mirror.part_size_for(GIB, 64 * MIB) == 64 * MIB


def test_the_part_size_stays_within_s3s_limits():
    """S3 rejects parts under 5 MiB (other than the last) and over 5 GiB."""
    assert s3mirror.part_size_for(GIB, 1 * MIB) == 5 * MIB
    assert s3mirror.part_size_for(GIB, 6 * GIB) == 5 * GIB


def test_copy_object_uploads_a_large_object_in_larger_parts(
    source, destination, config, monkeypatch
):
    """The part size goes into the upload's TransferConfig.

    The object is tiny, but copy_object sizes the upload from the size the listing
    gave, so passing 100 GiB shows the TransferConfig a real one would get.
    """
    source.put("media-assets", {"film.mov": b"frames"})
    destination.put("media-assets", {})
    merged = deepcopy(s3mirror.DEFAULT_CONFIG)
    merged["source"].update(config["source"])
    merged["destination"].update(config["destination"])
    mirror = s3mirror.S3Mirror(merged, logging.getLogger("test"))
    uploads = []
    upload = mirror.dest_client.upload_fileobj

    def record(*args, Config, **kwargs):  # pylint: disable=invalid-name
        uploads.append(Config)
        return upload(*args, Config=Config, **kwargs)

    monkeypatch.setattr(mirror.dest_client, "upload_fileobj", record)

    assert mirror.copy_object("media-assets", "film.mov", 100 * GIB)

    assert len(uploads) == 1
    assert math.ceil(100 * GIB / uploads[0].multipart_chunksize) <= 10_000
    assert destination.objects("media-assets") == {"film.mov": b"frames"}
