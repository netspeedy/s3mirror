"""What s3mirror prints of the access key IDs and secret keys."""

import pytest

AWS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def test_show_config_shortens_access_key_ids(config, run):
    """Only the first and last four characters of a full-length key ID are shown."""
    config["source"]["aws_access_key_id"] = AWS_KEY_ID
    config["source"]["aws_secret_access_key"] = AWS_SECRET

    code, output = run(config, "--show-config")

    assert code == 0, output
    assert '"aws_access_key_id": "AKIA...MPLE"' in output
    assert AWS_KEY_ID not in output
    assert AWS_SECRET not in output
    assert output.count('"aws_secret_access_key": "***REDACTED***"') == 2


@pytest.mark.parametrize("key_id", ["minioadmin", "ABCDEFGHIJKLMNOPQRS"])
def test_a_short_key_id_is_hidden_entirely(config, run, key_id):
    """Four and four of a short key ID would give most of it away."""
    config["destination"]["aws_access_key_id"] = key_id

    code, output = run(config, "--show-config")

    assert code == 0, output
    assert '"aws_access_key_id": "***"' in output
    assert key_id[:4] not in output


def test_placeholders_and_null_are_shown_as_they_are(config, run):
    """A placeholder means the key was never set, and null means the credential chain."""
    del config["source"]["aws_access_key_id"]
    config["destination"]["aws_access_key_id"] = None
    config["destination"]["aws_secret_access_key"] = None

    code, output = run(config, "--show-config")

    assert code == 0, output
    assert '"aws_access_key_id": "SOURCE_ACCESS_KEY"' in output
    assert '"aws_access_key_id": null' in output


def test_debug_output_hides_a_short_key_id(source, config, run):
    """The debug log used to show eight of minioadmin's ten characters."""
    source.put("app-data", {"a.txt": b"a"})
    config["source"]["aws_access_key_id"] = "minioadmin"
    config["destination"]["aws_access_key_id"] = AWS_KEY_ID

    code, output = run(config, "--debug")

    assert code == 0, output
    assert "Source access key: ***" in output
    assert "Destination access key: AKIA...MPLE" in output
    assert "mini..." not in output
