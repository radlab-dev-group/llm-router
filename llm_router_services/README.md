# llm_router_services

## Overview

`llm_router_services` provides **HTTP services** that implement the core functionality used by the LLM‑Router’s plugin system.  
The services expose guardrail and masking capabilities through Flask applications 
that can be called by the corresponding plugins in `llm_router_plugins`.

Key components:

| Sub‑package | Primary purpose |
|-------------|-----------------|
| **guardrails/** | Hosts the NASK‑PIB guardrail service (`nask_pib_guard_app.py`). It receives a JSON payload, chunks the text, runs a Hugging‑Face classification pipeline, and returns a safety verdict (`safe` flag + detailed per‑chunk results). |
| **maskers/** | Contains the **BANonymizer** (`banonymizer.py`) – a lightweight Flask service that performs token‑classification based anonymisation of input text. |
| **run_*.sh** scripts | Convenience wrappers to start the services (Gunicorn for the guardrail, plain Flask for the anonymiser). |
| **requirements‑gpu.txt** | Lists heavy dependencies (e.g., `transformers`) required for GPU‑accelerated inference. |

The services are **stateless**; they load their models once at start‑up and then serve requests over HTTP.

---

*Happy masking and safe routing!*
