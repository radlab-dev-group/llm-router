import json
import gnupg
import logging

from pathlib import Path
from datetime import datetime

# Base output directory for the auditor
AUDITOR_OUT_DIR = Path("logs/auditor")
# Create the directory (including any missing parents) the first time the module is imported
# `exist_ok=True` prevents an error if the directory already exists.
AUDITOR_OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDITOR_PUB_KEY_DIR = Path("resources/keys")
AUDITOR_PUB_KEY_FILE = AUDITOR_PUB_KEY_DIR / Path("llm-router-auditor-pub.asc")


class _GPGAuditorLogStorage:
    @staticmethod
    def store_log(audit_log, audit_type: str, gpg, import_result):
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S.%f")
        out_file_name = f"{audit_type}__{date_str}.audit"
        out_file_path = AUDITOR_OUT_DIR / out_file_name
        with open(out_file_path, "wt") as f:
            audit_str = json.dumps(audit_log, indent=2, ensure_ascii=False)
            encrypted_data = gpg.encrypt(
                audit_str,
                recipients=import_result.fingerprints,  # encrypt for this key
                always_trust=True,  # skip “untrusted key” warnings
                armor=True,  # ASCII output (default)
            )
            f.write(str(encrypted_data))


class AnyRequestAuditor:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

        self._import_result = None
        self._gpg = gnupg.GPG(gnupghome=str(AUDITOR_PUB_KEY_DIR))
        self._gpg.encoding = "utf-8"

        with AUDITOR_PUB_KEY_FILE.open("r", encoding="utf-8") as f:
            self._import_result = self._gpg.import_keys(f.read())
            if not self._import_result.count:
                raise RuntimeError(
                    f"Failed to import public key from {AUDITOR_PUB_KEY_FILE}"
                )

    def add_log(self, log):
        """
        Add a log entry to the auditor.
        The log can be a dict (JSON) or any serializable object,
        including a list of such entries.
        """
        audit_type = log["audit_type"]
        self.logger.warning(
            f"[AUDIT] ************ Added {audit_type} audit log! ************ "
        )
        _GPGAuditorLogStorage.store_log(
            audit_log=log,
            audit_type=audit_type,
            gpg=self._gpg,
            import_result=self._import_result,
        )
