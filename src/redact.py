"""Redact secrets and connection details before text reaches the UI.

Two sources of text can leak private data into a *public* Streamlit app:

* driver error strings (they may name the database host, e.g.
  ``db.h.aivencloud.com`` or ``cluster.mongodb.net``), and
* values typed into the application (parameters bound to SQL).

:func:`redact` removes those before the text is stored by the SQL Query
Inspector or rendered in an error panel. It is deliberately conservative: it
only rewrites things that look like credentials, connection URLs, certificates
or managed-provider host names, and it leaves SQL placeholders (``%s``,
``%(name)s``, ``?``) untouched so the Inspector keeps showing the real query
template.
"""

from __future__ import annotations

import re

REDACTED = "***REDACTED***"
REDACTED_CERT = "***REDACTED-CERTIFICATE***"
REDACTED_HOST = "***HOST***"

# Managed database providers whose host names must never appear in the UI.
_MANAGED_HOST_SUFFIXES = (
    "aivencloud.com",
    "mongodb.net",
    "proxy.rlwy.net",
    "rlwy.net",
)

_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----",
    re.DOTALL,
)

# scheme://user:password@host  ->  scheme://***:***@host
_URI_CREDENTIALS_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"
)

# password=..., secret: '...', token = "...", api_key=...
_SECRET_KV_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b"
    r"(\s*[:=]\s*)"
    r"(['\"]?)"
    r"([^\s'\";,)]+)"
    r"(['\"]?)"
)

_HOST_RE = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9._-]*\.(?:"
    + "|".join(re.escape(s) for s in _MANAGED_HOST_SUFFIXES)
    + r")\b"
)

# SQL placeholders must survive redaction.
_PLACEHOLDERS = {"%s", "%d", "%f", "%(", "?", "()", ""}


def redact(text) -> str:
    """Return ``text`` with secrets, URLs, certificates and hosts removed."""

    if text is None:
        return text

    out = str(text)

    out = _PEM_RE.sub(REDACTED_CERT, out)
    out = _URI_CREDENTIALS_RE.sub(r"\1***:***@", out)
    out = _HOST_RE.sub(REDACTED_HOST, out)

    def _secret(match: "re.Match[str]") -> str:
        value = match.group(4)
        if value in _PLACEHOLDERS or value.startswith("%("):
            return match.group(0)
        return (
            f"{match.group(1)}{match.group(2)}"
            f"{match.group(3)}{REDACTED}{match.group(5)}"
        )

    return _SECRET_KV_RE.sub(_secret, out)
