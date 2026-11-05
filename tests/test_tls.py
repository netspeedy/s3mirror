"""TLS certificate checks, against an HTTPS moto server with a self-signed certificate."""

import warnings

import urllib3

from tests.conftest import endpoint_config

OBJECTS = {"exports/2026-11-01.csv": b"export 1"}


def test_certificates_are_checked_by_default(tls_source, destination, run):
    """With verify_ssl left out, a self-signed certificate fails the connection check."""
    tls_source.put("app-data", OBJECTS)
    config = {
        "source": endpoint_config(tls_source, "SOURCE"),
        "destination": endpoint_config(destination, "DEST"),
    }

    code, output = run(config)

    assert code == 1, output
    assert "CERTIFICATE_VERIFY_FAILED" in output
    assert "Connection verification failed - aborting" in output
    assert not destination.buckets()


def test_a_ca_bundle_path_trusts_the_certificate(tls_source, destination, run):
    """verify_ssl can name the CA bundle for a private CA."""
    tls_source.put("app-data", OBJECTS)
    config = {
        "source": {
            **endpoint_config(tls_source, "SOURCE"),
            "verify_ssl": tls_source.ca,
        },
        "destination": endpoint_config(destination, "DEST"),
    }

    code, output = run(config)

    assert code == 0, output
    assert destination.objects("app-data") == OBJECTS
    assert "verification is off" not in output


def test_turning_verification_off_says_so_once(tls_source, destination, run):
    """verify_ssl: false connects, and replaces urllib3's per-request warnings with one line."""
    tls_source.put("app-data", OBJECTS)
    config = {
        "source": {**endpoint_config(tls_source, "SOURCE"), "verify_ssl": False},
        "destination": endpoint_config(destination, "DEST"),
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        code, output = run(config)

    assert code == 0, output
    assert destination.objects("app-data") == OBJECTS
    assert output.count("⚠ TLS certificate verification is off for the source") == 1
    assert "verification is off for the destination" not in output
    insecure = urllib3.exceptions.InsecureRequestWarning
    assert not [w for w in caught if issubclass(w.category, insecure)]


def test_urllib3_warnings_stay_on_when_both_sides_verify(
    source, config, run, monkeypatch
):
    """Nothing is silenced when every endpoint has its certificates checked."""
    source.put("app-data", OBJECTS)
    silenced = []
    monkeypatch.setattr(urllib3, "disable_warnings", silenced.append)

    code, output = run(config)

    assert code == 0, output
    assert not silenced
    assert "verification is off" not in output
