"""Config values s3mirror checks when it loads the file."""

# pytest passes fixtures as arguments, so a test that needs several takes several.
# pylint: disable=too-many-arguments,too-many-positional-arguments

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


@pytest.mark.parametrize(
    "section, key, value, problem",
    [
        ("performance", "max_workers", "20", "performance.max_workers must be"),
        ("performance", "max_workers", 0, "performance.max_workers must be"),
        ("performance", "multipart_chunksize", -1, "performance.multipart_chunksize"),
        ("performance", "max_concurrency", 2.5, "performance.max_concurrency must be"),
        ("performance", "max_pool_connections", True, "max_pool_connections must be"),
        ("sync", "exclude_buckets", "scratch-bucket", "sync.exclude_buckets must be"),
        ("sync", "exclude_buckets", None, "sync.exclude_buckets must be"),
        ("sync", "exclude_buckets", ["ok", 7], "sync.exclude_buckets must be"),
        ("source", "endpoint_url", 9000, "source.endpoint_url must be"),
        ("source", "endpoint_url", "s3.example.com", "source.endpoint_url must be"),
        ("destination", "region_name", ["eu-west-2"], "destination.region_name must"),
        ("destination", "aws_secret_access_key", None, "must both be set"),
        ("sync", "delete_extranous", False, "sync.delete_extranous isn't a config key"),
        ("source", "verify", False, "source.verify isn't a config key"),
    ],
)
def test_a_value_s3mirror_cant_use_is_a_config_error(
    source, destination, config, run, section, key, value, problem
):
    """Each of these used to be ignored, misread, or fail mid-run as a FATAL ERROR."""
    source.put("scratch-bucket", IN_SYNC)
    destination.put("scratch-bucket", {"stray.txt": b"x"})
    config.setdefault(section, {})[key] = value

    code, output = run(config)

    assert code == 1, output
    assert problem in output
    assert "S3 BUCKET MIRROR" not in output
    assert destination.objects("scratch-bucket") == {"stray.txt": b"x"}


@pytest.mark.parametrize("value", [None, "default", 20, ["source"]])
def test_a_section_that_isnt_a_mapping_is_a_config_error(config, run, value):
    """`sync: null` and the like used to replace the whole section."""
    config["sync"] = value

    code, output = run(config, "--no-delete")

    assert code == 1, output
    assert "sync must be a mapping" in output
    assert "Traceback" not in output


def test_an_unknown_section_is_a_config_error(config, run):
    """A misspelt section name used to leave the real one at its placeholder defaults."""
    config["destinaton"] = config.pop("destination")

    code, output = run(config)

    assert code == 1, output
    assert "destinaton isn't a config key; did you mean destination?" in output


def test_every_problem_is_reported_at_once(config, run):
    """Fixing one problem at a time and rerunning would be tedious."""
    config["performance"] = {"max_workers": "20", "max_concurency": 4}

    code, output = run(config)

    assert code == 1, output
    assert "performance.max_workers must be" in output
    assert "performance.max_concurency isn't a config key" in output
    assert "did you mean performance.max_concurrency?" in output
