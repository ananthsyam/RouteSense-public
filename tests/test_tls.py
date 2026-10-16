"""Tests for the CA resolver (src/tls.py).

Covers: empty value, an existing CA file path, inline PEM content written to a
private temp file, and a clear failure for a misconfigured (missing) path. TLS
certificate verification is never disabled here.
"""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import tls  # noqa: E402

SAMPLE_PEM = """-----BEGIN CERTIFICATE-----
MIIBdummycertificatecontentforunitTESTINGonlynotarealcertificate
-----END CERTIFICATE-----
"""


def test_none_and_empty_return_none():
    assert tls.resolve_ca(None) is None
    assert tls.resolve_ca("") is None


def test_existing_path_passes_through_unchanged(tmp_path):
    cafile = tmp_path / "ca.pem"
    cafile.write_text("-----BEGIN CERTIFICATE-----\nnot-a-real-cert\n", encoding="utf-8")
    assert tls.resolve_ca(str(cafile)) == str(cafile)


def test_missing_path_fails_with_a_clear_message():
    # A non-existent file is a configuration error: it must fail loudly and
    # must never silently fall back to an unverified connection.
    with pytest.raises(ValueError) as excinfo:
        tls.resolve_ca(r"C:\definitely\missing\ca.pem")
    assert "ROUTESENSE_MYSQL_SSL_CA" in str(excinfo.value)


def test_inline_pem_is_written_to_a_private_temp_file():
    path = tls.resolve_ca(SAMPLE_PEM)
    assert path is not None
    assert path.endswith(".pem")
    assert Path(path).exists()
    assert Path(path).read_text(encoding="utf-8").startswith("-----BEGIN CERTIFICATE-----")
    # Cached: same content -> same path
    assert tls.resolve_ca(SAMPLE_PEM) == path
    if os.name != "nt":
        assert (Path(path).stat().st_mode & 0o777) == 0o600


def test_inline_pem_is_not_stored_in_the_repository():
    path = tls.resolve_ca(SAMPLE_PEM)
    assert str(REPO) not in str(Path(path).resolve())
