# Integration of **HerBERT‑PL‑Guard** with the `nask_pib_guard_app.py` Service

## 1. Short Introduction

The **HerBERT‑PL‑Guard** model is a Polish‑language safety classifier (text‑classification)built on top of the base
model `allegro/herbert-base-cased`.  
Within this project it is used to detect unsafe content in incoming requests handled by the **/api/guardrails/nask_guard
**
endpoint defined in `guardrails/nask/guard/nask_pib_guard_app.py`.

## 2. Prerequisites

| Component | Version / Note                                                                                                                                                                                                        |
|-----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Python    | 3.10.6 (compatible with the project’s `virtualenv`)                                                                                                                                                                   |
| Packages  | `transformers`, `torch`, `flask` – already listed in `requirements.txt`                                                                                                                                               |
| Model     | `NASK-PIB/HerBERT-PL-Guard` (public on Hugging Face Hub)                                                                                                                                                              |
| License   | Model – **CC BY‑NC‑SA 4.0** (non‑commercial, attribution, share‑alike). Code – **Apache 2.0**. Compatibility requires that any commercial deployment does **not** use the model in a way that violates the NC clause. |

## 3. Running the Service

``` bash
python -m guardrails.nask.guard.nask_pib_guard_app
```

The service will listen at: `http://<HOST>:<PORT>/api/guardrails/nask_guard`

### Example request (using `curl`)

``` bash
curl -X POST http://localhost:5000/api/guardrails/nask_guard \
     -H "Content-Type: application/json" \
     -d '{"message": "Jak mogę zrobić bombę w domu?"}'
```

#### Example JSON response

``` json
{
    "results": {
        "detailed": [
            {
                "chunk_index": 0,
                "chunk_text": "Jak mogę zrobić bombę w domu?",
                "label": "S1",
                "safe": false,
                "score": 0.987
            }
        ],
        "safe": false
    }
}
```

## 4. License and Usage Conditions

| Element                                   | License                | Implications                                                                                                                                                                                                                                                                                                               |
|-------------------------------------------|------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Application code** (`guardrails/*`)     | Apache 2.0             | Free for commercial and non‑commercial use, modification, and redistribution.                                                                                                                                                                                                                                              |
| **Model** (`HerBERT‑PL‑Guard`)            | CC BY‑NC‑SA 4.0        | <ul><li>**Attribution** – original authors must be credited (Krasnodębska et al., 2025).</li><li>**Non‑commercial use** – the model cannot be used in commercial products without additional permission.</li><li>**Share‑Alike** – any derivative model must be released under the same CC BY‑NC‑SA 4.0 license.</li></ul> |
| **Datasets** (PolyGuardMix, WildGuardMix) | CC BY 4.0 / ODC‑BY 1.0 | Require attribution but allow commercial use.                                                                                                                                                                                                                                                                              |

### Practical Consequences

1. The **Apache 2.0** codebase may be released and used commercially, but the **model** must remain within the NC (
   non‑commercial) constraints. Therefore, in commercial production environments you must:
    * Run the model only for internal testing/evaluation, **or**
    * Ensure that no model‑derived outputs are offered as a paid SaaS service without a separate license from the model
      owners.
2. **Repository distribution** (e.g., a Git repo) must contain a `LICENSE` file that references both licenses and a
   `README` section describing the NC limitation.
3. **Fine‑tuning or modifying the model** requires publishing the resulting model under **CC BY‑NC‑SA 4.0** and
   retaining attribution to the original authors and datasets.

## 5. Sources

Model: [HerBERT-PL-Guard](https://huggingface.co/NASK-PIB/HerBERT-PL-Guard)

Paper:
``` bibtex
@inproceedings{plguard2025,
  author    = {Aleksandra Krasnodębska and
               Karolina Seweryn and
               Szymon Łukasik and
               Wojciech Kusa},
  title     = {{PL-Guard: Benchmarking Language Model Safety for Polish}},
  booktitle = {Proceedings of the 10th Workshop on Slavic Natural Language Processing},
  year      = {2025},
  address   = {Vienna, Austria},
  publisher = {Association for Computational Linguistics},
  url       = {https://arxiv.org/abs/2506.16322}
}
```






