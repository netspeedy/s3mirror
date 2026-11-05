"""Fixtures for running s3mirror against two in-memory S3 endpoints.

Each endpoint is its own moto server process, so the source and the destination keep
separate state and can hold buckets with the same names, as two real services would.
Nothing here talks to a real S3 service.
"""

# The fault injection wraps S3Mirror._create_client.
# pylint: disable=protected-access

import ipaddress
import json
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.config import Config
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import s3mirror


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _self_signed_certificate(directory) -> tuple:
    """Write a self-signed certificate for 127.0.0.1 and its key, returning both paths.

    It's its own CA, so the certificate file doubles as the CA bundle that trusts it.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "s3mirror test endpoint")]
    )
    now = datetime.now(timezone.utc)
    usage = x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    )
    public = key.public_key()
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(public)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(usage, critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(public), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "endpoint.pem"
    key_path = directory / "endpoint.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


class Endpoint:
    """One moto S3 server, standing in for one side of the mirror.

    With `tls`, a (certificate, key) pair, it serves HTTPS with that certificate, and
    `ca` is the bundle that trusts it.
    """

    def __init__(self, tls=None) -> None:
        port = _free_port()
        command = [
            sys.executable,
            "-m",
            "moto.server",
            "-H",
            "127.0.0.1",
            "-p",
            str(port),
        ]
        self.ca = None
        self._context = None
        if tls:
            self.ca = tls[0]
            self._context = ssl.create_default_context(cafile=self.ca)
            command += ["-c", tls[0], "-k", tls[1]]
        self.url = f"{'https' if tls else 'http'}://127.0.0.1:{port}"
        # pylint: disable-next=consider-using-with
        self._process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.monotonic() + 30
        while not self._ready():
            if self._process.poll() is not None or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError(f"moto server on {self.url} didn't start")
            time.sleep(0.1)
        self.client = boto3.client(
            "s3",
            endpoint_url=self.url,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            region_name="us-east-1",
            verify=self.ca,
            config=Config(s3={"addressing_style": "path"}),
        )

    def _ready(self) -> bool:
        url = f"{self.url}/moto-api/"
        try:
            with urllib.request.urlopen(url, timeout=1, context=self._context):
                return True
        except (urllib.error.URLError, ConnectionError):
            return False

    def reset(self) -> None:
        """Forget every bucket and object."""
        request = urllib.request.Request(f"{self.url}/moto-api/reset", method="POST")
        with urllib.request.urlopen(request, timeout=5, context=self._context):
            pass

    def stop(self) -> None:
        """Stop the server."""
        self._process.terminate()
        self._process.wait(timeout=10)

    def put(self, bucket: str, objects: dict) -> None:
        """Create the bucket if it's missing, then write each {key: body} into it."""
        existing = {b["Name"] for b in self.client.list_buckets()["Buckets"]}
        if bucket not in existing:
            self.client.create_bucket(Bucket=bucket)
        for key, body in objects.items():
            self.client.put_object(Bucket=bucket, Key=key, Body=body)

    def buckets(self) -> list:
        """The bucket names, sorted."""
        return sorted(b["Name"] for b in self.client.list_buckets()["Buckets"])

    def objects(self, bucket: str) -> dict:
        """Every object in the bucket as {key: body}."""
        found = {}
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                body = self.client.get_object(Bucket=bucket, Key=obj["Key"])["Body"]
                found[obj["Key"]] = body.read()
        return found


@pytest.fixture(scope="session", name="endpoints")
def endpoints_fixture():
    """Start the two servers once for the whole test run."""
    started = []
    try:
        started.append(Endpoint())
        started.append(Endpoint())
        yield started[0], started[1]
    finally:
        for endpoint in started:
            endpoint.stop()


@pytest.fixture(scope="session", name="tls_endpoint")
def tls_endpoint_fixture(tmp_path_factory):
    """Start one HTTPS server with a self-signed certificate, for TLS tests."""
    tls = _self_signed_certificate(tmp_path_factory.mktemp("tls"))
    endpoint = Endpoint(tls)
    try:
        yield endpoint
    finally:
        endpoint.stop()


@pytest.fixture(name="tls_source")
def tls_source_fixture(tls_endpoint):
    """An HTTPS source endpoint with a self-signed certificate, emptied before each test."""
    tls_endpoint.reset()
    return tls_endpoint


@pytest.fixture(name="source")
def source_fixture(endpoints):
    """The source endpoint, emptied before each test."""
    endpoints[0].reset()
    return endpoints[0]


@pytest.fixture(name="destination")
def destination_fixture(endpoints):
    """The destination endpoint, emptied before each test."""
    endpoints[1].reset()
    return endpoints[1]


def endpoint_config(endpoint: Endpoint, key: str) -> dict:
    """The config section for one side of the mirror, pointing at `endpoint`."""
    return {
        "endpoint_url": endpoint.url,
        "aws_access_key_id": f"{key}_ACCESS_KEY_ID",
        "aws_secret_access_key": f"{key}_SECRET_ACCESS_KEY",
        "region_name": "us-east-1",
    }


@pytest.fixture(name="config")
def config_fixture(source, destination):
    """A config pointing s3mirror at the two test endpoints."""
    return {
        "source": endpoint_config(source, "SOURCE"),
        "destination": endpoint_config(destination, "DEST"),
    }


@pytest.fixture(name="run")
def run_fixture(tmp_path, monkeypatch, capsys):
    """Run s3mirror's main() with a config and flags, returning (exit code, output)."""

    def run(config: dict, *flags: str):
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["s3mirror", "--config", str(path), *flags])
        capsys.readouterr()
        with pytest.raises(SystemExit) as exited:
            s3mirror.main()
        captured = capsys.readouterr()
        return exited.value.code, captured.out + captured.err

    return run


def _error(code: str, status: int):
    http = AWSResponse("http://fault.invalid/", status, {}, None)
    parsed = {
        "Error": {"Code": code, "Message": f"Injected {code}"},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }
    return http, parsed


class Faults:
    """Make chosen calls from s3mirror's own clients fail, as a faulty endpoint would.

    The rules are attached to the clients S3Mirror creates, so the test's own clients
    for seeding and checking the endpoints aren't affected.
    """

    def __init__(self, monkeypatch) -> None:
        self._rules: dict = {"SOURCE": [], "DESTINATION": []}
        create_client = s3mirror.S3Mirror._create_client

        def create_with_faults(mirror, section, label):
            client = create_client(mirror, section, label)
            for event, handler in self._rules[label]:
                client.meta.events.register(event, handler)
            return client

        monkeypatch.setattr(s3mirror.S3Mirror, "_create_client", create_with_faults)

    def fail(  # pylint: disable=too-many-arguments
        self,
        side: str,
        operation: str,
        *,
        bucket=None,
        after: int = 0,
        code: str = "AccessDenied",
        status: int = 403,
        raises=None,
    ) -> None:
        """Fail `operation` on `side`, optionally only for one bucket, after `after` calls.

        The call gets an S3 error response with `code` and `status`, or with `raises`,
        that exception is raised instead, as a timeout or a dropped connection would be.
        """
        calls = 0

        def handler(params, **_):
            nonlocal calls
            if (
                bucket is not None
                and urlsplit(params["url"]).path.split("/")[1] != bucket
            ):
                return None
            calls += 1
            if calls <= after:
                return None
            if raises is not None:
                raise raises
            return _error(code, status)

        self._rules[side].append((f"before-call.s3.{operation}", handler))

    def page_size(self, side: str, size: int) -> None:
        """Make listings on `side` return at most `size` keys a page."""

        def handler(params, **_):
            params.setdefault("MaxKeys", size)

        self._rules[side].append(("provide-client-params.s3.ListObjectsV2", handler))


@pytest.fixture
def faults(monkeypatch):
    """Inject failures into the calls s3mirror makes."""
    return Faults(monkeypatch)
