"""Config values s3mirror checks when it loads the file."""

import pytest

from tests.conftest import endpoint_config

IN_SYNC = {"exports/2026-11-01.csv": b"export 1"}


@pytest.mark.parametrize("value", ["false", "False", " FALSE "])
def test_a_quoted_false_turns_deletion_off(source, destination, config, run, value):
    """A string "false", as JSON or a quoted YAML value gives, means false."""
    source.put("app-data", IN_SYNC)
    destination.put("app-data", {"stray.txt": b"x", **IN_SYNC})
    config["sync"] = {"delete_extraneous": value}

    code, output = run(config)

    assert code == 0, output
    assert "stray.txt" in destination.objects("app-data")


@pytest.mark.parametrize("value", ["no", "0", "", 0, 1, None, []])
def test_anything_else_is_a_config_error(source, destination, config, run, value):
    """Values that aren't clearly true or false stop the run before it connects."""
    source.put("app-data", IN_SYNC)
    destination.put("app-data", {"stray.txt": b"x", **IN_SYNC})
    config["sync"] = {"delete_extraneous": value}

    code, output = run(config)

    assert code == 1, output
    assert "sync.delete_extraneous must be true or false" in output
    assert "S3 BUCKET MIRROR" not in output
    assert "stray.txt" in destination.objects("app-data")


def test_show_config_prints_the_parsed_boolean(config, run):
    """--show-config shows what s3mirror will use, not what the file said."""
    config["sync"] = {"delete_extraneous": "false"}
    config["source"]["verify_ssl"] = "TRUE"

    code, output = run(config, "--show-config")

    assert code == 0, output
    assert '"delete_extraneous": false' in output
    assert '"verify_ssl": true' in output


def test_a_quoted_false_turns_verification_off(tls_source, destination, run):
    """verify_ssl: "false" used to be read as the path to a CA bundle called false."""
    tls_source.put("app-data", IN_SYNC)
    config = {
        "source": {**endpoint_config(tls_source, "SOURCE"), "verify_ssl": "false"},
        "destination": endpoint_config(destination, "DEST"),
    }

    code, output = run(config)

    assert code == 0, output
    assert "TLS certificate verification is off for the source" in output
    assert destination.objects("app-data") == IN_SYNC


@pytest.mark.parametrize("value", [0, None, "", "/nonexistent/ca-bundle.pem"])
def test_a_bad_verify_ssl_is_a_config_error(config, run, value):
    """Neither a boolean nor a CA bundle that exists, so there's no telling what was meant."""
    config["destination"]["verify_ssl"] = value

    code, output = run(config)

    assert code == 1, output
    assert "destination.verify_ssl must be true, false" in output
    assert "S3 BUCKET MIRROR" not in output
