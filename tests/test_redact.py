"""Tests for the secret/connection redaction helper (src/redact.py)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import redact  # noqa: E402


def test_none_passes_through():
    assert redact.redact(None) is None


def test_removes_pem_certificate_blocks():
    text = (
        "cfg -----BEGIN CERTIFICATE-----\nAAAABBBBCCCC\n"
        "-----END CERTIFICATE-----\ndone"
    )
    out = redact.redact(text)
    assert "-----BEGIN" not in out
    assert "AAAABBBBCCCC" not in out


def test_removes_uri_credentials():
    out = redact.redact("connect mongodb+srv://user:pa55@cl0.mongodb.net/db")
    assert "pa55" not in out
    assert "cl0.mongodb.net" not in out
    assert out.startswith("connect mongodb+srv://***:***@")


def test_removes_mysql_url_credentials():
    out = redact.redact("mysql://root:s3cr3t@127.0.0.1:3306/delivery_db")
    assert "s3cr3t" not in out
    assert out.startswith("mysql://***:***@")


def test_removes_managed_host_names():
    assert "aivencloud.com" not in redact.redact(
        "Can't connect to MySQL server on 'h.aivencloud.com:17436' (10060)"
    )
    assert "rlwy.net" not in redact.redact("server: proxy.rlwy.net:5000")
    assert "***HOST***" in redact.redact("host=cluster0.abc.mongodb.net")


def test_removes_password_style_assignments():
    samples = (
        "password=topsecret",
        "Secret: 'topsecret'",
        "api_key = topsecret",
        "TOKEN=topsecret",
        "passwd:topsecret",
    )
    for text in samples:
        assert "topsecret" not in redact.redact(text), text


def test_keeps_sql_placeholders_intact():
    """The Inspector must keep showing the real query template."""

    tpl = "UPDATE customers SET password = %s WHERE customer_id = %s"
    assert redact.redact(tpl) == tpl

    tpl2 = "INSERT INTO orders (amount) VALUES (%(amount)s)"
    assert redact.redact(tpl2) == tpl2

    tpl3 = "SELECT * FROM t WHERE id = ?"
    assert redact.redact(tpl3) == tpl3


def test_leaves_ordinary_text_untouched():
    text = "password is empty for this user"
    assert redact.redact(text) == text

    text2 = "SELECT order_id FROM orders"
    assert redact.redact(text2) == text2
