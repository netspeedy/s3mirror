"""Mirroring tests, run against two moto S3 servers from conftest.py."""

# pytest passes fixtures as arguments, so a test that needs several takes several.
# pylint: disable=too-many-arguments,too-many-positional-arguments

import pytest
from botocore.exceptions import ReadTimeoutError

IN_SYNC = {f"exports/2026-11-0{n}.csv": f"export {n}".encode() for n in range(1, 6)}


def test_a_run_copies_new_and_changed_objects_and_deletes_the_rest(
    source, destination, config, run
):
    """The baseline: what the failure tests below expect when nothing fails."""
    source.put("app-data", {"new.txt": b"new", "changed.txt": b"longer now", **IN_SYNC})
    destination.put("app-data", {"changed.txt": b"short", "stray.txt": b"x", **IN_SYNC})
    source.put("media-assets", {"logo.svg": b"<svg/>"})

    code, output = run(config)

    assert code == 0, output
    assert destination.buckets() == ["app-data", "media-assets"]
    assert destination.objects("app-data") == source.objects("app-data")
    assert destination.objects("media-assets") == {"logo.svg": b"<svg/>"}
    assert "✓ Status: COMPLETED SUCCESSFULLY" in output


@pytest.mark.parametrize("after", [0, 1], ids=["first-page", "second-page"])
@pytest.mark.parametrize("side", ["SOURCE", "DESTINATION"])
def test_a_failed_listing_skips_the_bucket_and_deletes_nothing(
    source, destination, config, run, faults, side, after
):
    """A listing that doesn't finish leaves the bucket alone and fails the run.

    With two keys a page, a failure on the second page means the first two keys were
    listed and the rest weren't, which used to make the rest look extraneous.
    """
    source.put("app-data", {"new.txt": b"new", **IN_SYNC})
    destination.put("app-data", {"stray.txt": b"x", **IN_SYNC})
    source.put("media-assets", {"logo.svg": b"<svg/>"})
    before = destination.objects("app-data")
    faults.page_size(side, 2)
    faults.fail(side, "ListObjectsV2", bucket="app-data", after=after)

    code, output = run(config)

    assert code == 1, output
    assert destination.objects("app-data") == before
    assert "Failed to list objects in app-data" in output
    assert "Skipping bucket due to listing failure" in output
    assert "Status: COMPLETED WITH ERRORS" in output
    # The other bucket is still mirrored.
    assert destination.objects("media-assets") == {"logo.svg": b"<svg/>"}


def test_a_listing_that_times_out_skips_only_that_bucket(
    source, destination, config, run, faults
):
    """A timeout partway through a listing skips that bucket rather than the run."""
    source.put("app-data", IN_SYNC)
    destination.put("app-data", {"stray.txt": b"x", **IN_SYNC})
    source.put("media-assets", {"logo.svg": b"<svg/>"})
    before = destination.objects("app-data")
    faults.page_size("SOURCE", 2)
    faults.fail(
        "SOURCE",
        "ListObjectsV2",
        bucket="app-data",
        after=1,
        raises=ReadTimeoutError(endpoint_url=source.url),
    )

    code, output = run(config)

    assert code == 1, output
    assert destination.objects("app-data") == before
    assert "Skipping bucket due to listing failure" in output
    assert destination.objects("media-assets") == {"logo.svg": b"<svg/>"}


def test_a_failed_bucket_listing_fails_the_run(
    source, destination, config, run, faults
):
    """Listing the source's buckets again after the connection check can fail too."""
    source.put("app-data", IN_SYNC)
    faults.fail("SOURCE", "ListBuckets", after=1)

    code, output = run(config)

    assert code == 1, output
    assert "Failed to list source buckets" in output
    assert "No buckets found to sync" not in output
    assert "Status: COMPLETED WITH ERRORS" in output
    assert not destination.buckets()


def test_a_forbidden_head_bucket_skips_the_bucket_without_creating_it(
    source, destination, config, run, faults
):
    """A 403 from HeadBucket says nothing about whether the bucket exists."""
    source.put("app-data", IN_SYNC)
    source.put("media-assets", {"logo.svg": b"<svg/>"})
    faults.fail("DESTINATION", "HeadBucket", bucket="app-data", code="403", status=403)
    faults.fail("DESTINATION", "CreateBucket", bucket="app-data", code="Unexpected")

    code, output = run(config)

    assert code == 1, output
    assert "Failed to check bucket on destination" in output
    assert "Skipping bucket due to HeadBucket failure" in output
    assert "Unexpected" not in output
    assert destination.buckets() == ["media-assets"]
    assert "Status: COMPLETED WITH ERRORS" in output


def test_a_missing_bucket_reported_as_no_such_bucket_is_created(
    source, destination, config, run, faults
):
    """Some services answer HeadBucket with a NoSuchBucket code, which is a 404 too."""
    source.put("app-data", IN_SYNC)
    faults.fail("DESTINATION", "HeadBucket", code="NoSuchBucket", status=404)

    code, output = run(config)

    assert code == 0, output
    assert "✓ Created bucket: app-data" in output
    assert destination.objects("app-data") == IN_SYNC


def test_a_bucket_is_created_in_the_destination_region(
    source, destination, config, run
):
    """Outside us-east-1, CreateBucket has to name the region it's sent to."""
    source.put("app-data", IN_SYNC)
    config["destination"]["region_name"] = "eu-west-2"

    code, output = run(config)

    assert code == 0, output
    assert "✓ Created bucket: app-data" in output
    location = destination.client.get_bucket_location(Bucket="app-data")
    assert location["LocationConstraint"] == "eu-west-2"
    assert destination.objects("app-data") == IN_SYNC
