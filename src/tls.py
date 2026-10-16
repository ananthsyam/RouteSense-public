"""Resolve a MySQL TLS CA certificate from a file path or inline PEM text.

Local setups normally pass a *path* to ``ca.pem``. Streamlit Community Cloud
stores secrets as text, so a CA supplied through ``st.secrets`` arrives as the
PEM *content* itself. This helper accepts either form.

The certificate content is public (it is not a secret) but is still never
logged, and inline content is written to a ``0600`` temp file outside the
repository and removed when the process exits.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import tempfile

_TEMP_CA_PATHS: "set[str]" = set()


def _cleanup() -> None:
    for path in list(_TEMP_CA_PATHS):
        try:
            os.remove(path)
        except OSError:
            pass


atexit.register(_cleanup)


def resolve_ca(value: "str | None") -> "str | None":
    """Return a filesystem path to a CA certificate, or ``None``.

    * ``None`` / empty  -> ``None`` (no explicit CA; driver TLS defaults apply)
    * contains ``BEGIN CERTIFICATE`` -> written to a private temp file
    * otherwise     -> treated as a path and returned unchanged

    Raises :class:`ValueError` when the value is neither PEM content nor an
    existing file, so a misconfigured CA fails with a clear (and safe) message
    instead of a driver stack trace. Certificate verification is never
    disabled.
    """

    if not value:
        return None

    value = value.strip()
    if "BEGIN CERTIFICATE" not in value:
        if not os.path.isfile(value):
            raise ValueError(
                "ROUTESENSE_MYSQL_SSL_CA must be PEM certificate content "
                "(including the BEGIN/END lines) or the path to an existing "
                "certificate file. TLS verification was not disabled."
            )
        return value

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(tempfile.gettempdir(), f"routesense_ca_{digest}.pem")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
        _TEMP_CA_PATHS.add(path)
    return path
