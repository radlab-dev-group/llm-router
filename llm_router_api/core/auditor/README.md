# Auditing subsystem – `llm-router`

The **auditor** package provides a pluggable, tamper‑evident audit‑log system for the
LLM‑router. All audit entries are written as JSON, encrypted with GPG and stored
under `logs/auditor`. The subsystem is used by the router to record:

* request guard‑rail decisions
* payload masking operations
* custom audit events emitted by the application (e.g. business‑logic logs)

The implementation is deliberately lightweight so it can be swapped out for a
different storage backend (database, cloud bucket, …) without touching the rest
of the code base.

---

## 📁 Directory layout

```

llm_router_api/
└─ core/
   └─ auditor/
      ├─ __init__.py                # package marker
      ├─ auditor.py                 # public API – AnyRequestAuditor
      └─ log_storage/
         ├─ __init__.py
         ├─ log_storage_interface.py   # abstract storage contract
         └─ gpg.py                     # GPG‑backed storage implementation
```

* **`auditor.py`** – high‑level helper that forwards audit records to a
  storage backend. The default backend is `GPGAuditorLogStorage`.
* **`log_storage_interface.py`** – defines the `AuditorLogStorageInterface`
  protocol (`store_log(audit_log, audit_type)`).
* **`gpg.py`** – concrete implementation that encrypts each log entry with the
  public GPG key located at `resources/keys/llm-router-auditor-pub.asc` and
  writes the encrypted payload to a timestamped file
  `logs/auditor/<audit_type>__<timestamp>.audit`.

---

## 🛠️ How the auditor works

1. **Endpoint code** (e.g. `endpoint_i.py`) creates an `AnyRequestAuditor`
   instance with the router’s logger.
2. When an auditable event occurs, the endpoint builds a dictionary that
   contains at least the keys `audit_type` and `payload`.
3. `AnyRequestAuditor.add_log()` forwards the dictionary to the configured
   storage backend.
4. `GPGAuditorLogStorage.store_log()`
    * JSON‑serialises the dictionary (pretty‑printed).
    * Encrypts the JSON string with the imported public key.
    * Writes the encrypted ASCII‑armored data to `logs/auditor/`.
5. The resulting files have the extension `.audit`. They are **confidential**
   and **tamper‑evident** – any modification breaks the GPG decryption.

---

## 🔐 GPG key management

The repository ships two helper scripts under `scripts/`:

| Script                    | Purpose                                                                                                                      |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `gen_and_export_gpg.sh`   | Generates a 4096‑bit RSA key pair (no interactive prompts) and exports the public (`*.asc`) and private (`*-priv.asc`) keys. |
| `decrypt_auditor_logs.sh` | Decrypts all `*.audit` files in `logs/auditor/` and writes the resulting JSON to `*.json`.                                   |

### 1️⃣ Generate a new key pair

``` bash
cd scripts
./gen_and_export_gpg.sh
```

The script will:

* Prompt for an email address (used as the GPG user ID).
* Prompt for a passphrase (protects the private key).
* Create a key pair in the local GPG keyring.
* Export the **public** key to `llm-router-auditor-pub.asc`.
* Export the **private** key to `llm-router-auditor-priv.asc`.

> **Important:** Keep the private key (`*-priv.asc`) and its passphrase safe.  
> Only the public key is required by the router at runtime.

### 2️⃣ Place the public key where the router expects it

``` bash
mkdir -p resources/keys
cp llm-router-auditor-pub.asc resources/keys/
```

The `GPGAuditorLogStorage` class automatically imports the key from this
location when the application starts.

### 3️⃣ Decrypt audit logs

``` bash
cd scripts
./decrypt_auditor_logs.sh
```

For each file `logs/auditor/<type>__<timestamp>.audit` the script produces a
human‑readable `*.json` file next to it:

```
logs/auditor/request__20231129_123456.789012.audit  →  request__20231129_123456.789012.json
```

You will be prompted for the passphrase of the **private** key if it is
encrypted.

---

## 📚 Example: Auditing a request guard‑rail decision

```python
from llm_router_api.core.auditor.auditor import AnyRequestAuditor
import logging

logger = logging.getLogger("router")
auditor = AnyRequestAuditor(logger)

# Somewhere inside an endpoint, after a guard‑rail check:
audit_record = {
    "audit_type": "guardrail_request",
    "payload": {
        "user_id": "12345",
        "input": "…",
        "decision": "blocked",
        "reason": "PII detected"
    }
}
auditor.add_log(audit_record)
```

The record is encrypted and persisted as e.g.:

```
logs/auditor/guardrail_request__20231129_141530.123456.audit
```

---

## 🧩 Extending the auditor

If you need a different storage backend (e.g. a database), implement a new
class that inherits from `AuditorLogStorageInterface` and provides a
`store_log(self, audit_log, audit_type)` method. Then change the constant
`DEFAULT_AUDITOR_STORAGE_CLASS` in `auditor.py` to point to your class.

---

## 📖 Further reading

* **`llm_router_api/core/auditor/gpg.py`** – source code of the GPG storage
  implementation.
* **`scripts/`** – full scripts for key generation and decryption.
* **`README.md`** – overall project documentation.

--- 

*Happy auditing!* 🎯


--- 
00/000000

## 📄 Update to the main `README.md`

Add the following section near the **Features** or **Monitoring & Metrics** part of the main README:

```

Place the snippet where you describe optional runtime features (e.g., after *Monitoring & Metrics*). This gives users a
quick overview and a direct link to the full audit guide.

```
