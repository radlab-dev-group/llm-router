"""
Implementation of an audit‑log storage backend that encrypts logs using GPG.

The :class:`GPGAuditorLogStorage` class conforms to the
:class:`~llm_router_api.core.auditor.log_storage.log_storage_interface.AuditorLogStorageInterface`
protocol.  It writes each log entry to a timestamped file inside
``logs/auditor`` and encrypts the JSON payload with a public GPG key
located in ``resources/keys``.  This ensures that audit data is stored
at rest in a confidential, tamper‑evident format.

Typical workflow
----------------
1. An instance of :class:`GPGAuditorLogStorage` is created – the public
   key is imported automatically.
2. The :meth:`store_log` method is called with a serialisable ``audit_log``
   and an ``audit_type`` string.
3. The log is JSON‑encoded, encrypted with the imported key, and written to
   ``logs/auditor/<audit_type>__<timestamp>.audit``.
"""

import uuid
import json
import gnupg

from pathlib import Path
from datetime import datetime

from llm_router_api.core.auditor.log_storage.log_storage_interface import (
    AuditorLogStorageInterface,
)

# Base output directory for the auditor
DEFAULT_AUDITOR_OUT_DIR = Path("logs/auditor")
DEFAULT_AUDITOR_OUT_DIR.mkdir(parents=True, exist_ok=True)


class GPGAuditorLogStorage(AuditorLogStorageInterface):
    # Default gpg auditor public key
    AUDITOR_PUB_KEY_DIR = Path("resources/keys")
    AUDITOR_PUB_KEY_FILE = AUDITOR_PUB_KEY_DIR / Path("llm-router-auditor-pub.asc")

    """
    GPG‑backed storage for audit logs.

    The storage writes each log entry to a file under ``DEFAULT_AUDITOR_OUT_DIR``
    and encrypts the content with the public key found at
    ``AUDITOR_PUB_KEY_FILE``.  The key is imported once during initialisation.

    Attributes
    ----------
    _gpg : gnupg.GPG
        Configured GPG instance pointing at ``AUDITOR_PUB_KEY_DIR``.
    _import_result : gnupg.ImportResult
        Result of importing the public key; contains the fingerprint(s) used
        for encryption.
    """

    def __init__(self):
        """
        Create a new GPG‑based audit log storage instance.

        The constructor loads the public key from ``AUDITOR_PUB_KEY_FILE``.
        If the key cannot be imported, a :class:`RuntimeError` is raised.

        Raises
        ------
        RuntimeError
            If the public key file is missing or contains no importable keys.
        """

        self._import_result = None
        self._gpg = gnupg.GPG(gnupghome=str(self.AUDITOR_PUB_KEY_DIR))
        self._gpg.encoding = "utf-8"

        self.__verify()

        with self.AUDITOR_PUB_KEY_FILE.open("r", encoding="utf-8") as f:
            self._import_result = self._gpg.import_keys(f.read())
            if not self._import_result.count:
                raise RuntimeError(
                    f"Failed to import public key from {self.AUDITOR_PUB_KEY_FILE}"
                )

    def store_log(self, audit_log, audit_type: str):
        """
        Encrypt and persist an audit log entry.

        Parameters
        ----------
        audit_log : Any
            JSON‑serialisable object representing the audit record.
        audit_type : str
            Category of the log (e.g., ``"request"``, ``"error"``).  The value
            is incorporated into the output filename.

        The method creates a filename of the form
        ``<audit_type>__<YYYYMMDD_HHMMSS.microseconds>.audit`` inside
        ``DEFAULT_AUDITOR_OUT_DIR``.  The log is JSON‑encoded with indentation
        for readability, encrypted using the previously imported public key,
        and written in ASCII‑armored format.

        Raises
        ------
        Exception
            Propagates any exception raised by the underlying GPG encryption
            or file I/O operations.
        """
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S.%f")
        out_file_name = f"{audit_type}__{date_str}.audit"
        out_file_path = DEFAULT_AUDITOR_OUT_DIR / out_file_name
        with open(out_file_path, "wt") as f:
            audit_str = json.dumps(audit_log, indent=2, ensure_ascii=False)
            encrypted_data = self._gpg.encrypt(
                audit_str,
                recipients=self._import_result.fingerprints,
                always_trust=True,
                armor=True,
            )
            f.write(str(encrypted_data))

    def __verify(self):
        """
        Perform internal sanity checks during initialisation.

        This method verifies that the required GPG public key file exists
        and that the process has write access to ``DEFAULT_AUDITOR_OUT_DIR``.
        It raises an exception if either check fails.
        """
        self.__check_key_exists()
        self.__check_write_permission()

    def __check_key_exists(self):
        """
        Ensure that the GPG public key file specified by
        ``AUDITOR_PUB_KEY_FILE`` is present on the filesystem.

        Raises
        ------
        Exception
            If the public key file does not exist.
        """
        if not self.AUDITOR_PUB_KEY_FILE.exists():
            raise Exception(
                f"GPG public key {self.AUDITOR_PUB_KEY_FILE} does not exists!"
            )

    def __check_write_permission(self):
        """
        Verify that the process can write to ``DEFAULT_AUDITOR_OUT_DIR``.
        Writes a temporary file containing the string ``"llm-router"``,
        then removes it. Raises ``PermissionError`` if any step fails.
        """
        try:
            temp_name = f"perm_check_{uuid.uuid4().hex}.audit"
            temp_path = DEFAULT_AUDITOR_OUT_DIR / temp_name
            with open(temp_path, "wt") as f:
                f.write("llm-router")
            temp_path.unlink()
        except Exception as exc:
            raise PermissionError(
                f"Unable to write to {DEFAULT_AUDITOR_OUT_DIR}: {exc}"
            )
