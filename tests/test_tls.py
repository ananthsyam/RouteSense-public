"""Tests for the CA resolver (src/tls.py)."""

import os
import sys
from pathlib import Path

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


def test_path_is_returned_unchanged():
    assert tls.resolve_ca(r"C:\certs\ca.pem") == r"C:\certs\ca.pem"
    assert tls.resolve_ca("/etc/ssl/ca.pem") == "/etc/ssl/ca.pem"


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
