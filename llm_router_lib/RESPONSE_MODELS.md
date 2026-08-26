# Response models

## Introduction

The router speaks JSON, and every endpoint emits a *different* shape. Before these models,
`LLMRouterClient` handed that JSON straight back as a raw `dict`, so the knowledge of each response schema lived on the
caller side: you had to remember the exact key names, guard against missing fields, and you got no compile‑time or IDE
help.

The response models move that contract into the library. Every client method returns a typed Pydantic model that mirrors
the JSON body the router emits for that endpoint, and the models are defined in one place — [
`data_models/response.py`](data_models/response.py) — next to the existing *request* models (`TranslateModel`,
`Polarity3cModel`, …). Together, request

+ response describe the full contract of an endpoint.

Concretely, the typing is there to do three things:

- **Fix the contract in one place.** `response.py` is the single definition of what each endpoint returns. Change the
  router → change the model → type checkers and tests flag every consumer that still relied on the old shape.
- **Validate at the boundary.** Pydantic checks the body as it comes in, so a malformed or partial response fails there
  with a `ValidationError` instead of as a `KeyError` a few frames deep in your code.
- **Expose static types.** Because the return annotation is a class rather than
  `Dict[str, Any]`, `mypy` and IDEs can resolve `resp.response[0].translated`. The model also exports a JSON Schema via
  `model_json_schema()` for docs, codegen, or contract tests.

```python
# resp is a typed model, not a dict
resp = client.translate(texts=["Hello world"], model="speakleash/Bielik-11B-v2.3-Instruct")
resp.response[0].translated  # str
resp.generation_time  # float | None
resp.model_dump()  # → plain dict, if you still need one
```

---

## 📦 Where the models live and how to import them

All response models are exported from the package root, so either import style works:

```python
# Option 1 – from the package (recommended)
from llm_router_lib.data_models import (
    TranslateResponse,
    Polarity3cResponse,
    ConversationResponse,
    ModelsListResponse,
    # …see the full list in data_models/__init__.py
)

# Option 2 – from the module directly
from llm_router_lib.data_models.response import TranslateResponse
```

They sit alongside (but are independent of) the request models such as
`TranslateModel`, `Polarity3cModel`, etc.

---

## 🗺️ Client method → response model

The table below maps **every** `LLMRouterClient` method to the model it now returns.
`response` is the endpoint‑specific payload; `generation_time` (seconds) is present on all generation endpoints.

| Client method                               | Endpoint                                     | Returns                              | `response` payload                     |
|---------------------------------------------|----------------------------------------------|--------------------------------------|----------------------------------------|
| `ping()`                                    | `GET /api/ping`                              | `PingResponse`                       | `status: bool`, `body: str`            |
| `version()`                                 | `GET /api/version`                           | `VersionResponse`                    | `version: str`                         |
| `models()`                                  | `GET /v1/models`                             | `ModelsListResponse`                 | `object: str`, `data: list[ModelInfo]` |
| `conversation_with_model(payload)`          | `POST /api/conversation_with_model`          | `ConversationResponse`               | `str` (assistant reply)                |
| `extended_conversation_with_model(payload)` | `POST /api/extended_conversation_with_model` | `ExtendedConversationResponse`       | `str` (assistant reply)                |
| `polarity_3c(...)`                          | `POST /api/polarity_3c`                      | `Polarity3cResponse`                 | `list[Polarity3cItem]`                 |
| `translate(...)`                            | `POST /api/translate`                        | `TranslateResponse`                  | `list[TranslateItem]`                  |
| `simplify_text(...)`                        | `POST /api/simplify_text`                    | `SimplifyTextResponse`               | `list[str]`                            |
| `generative_answer(...)`                    | `POST /api/generative_answer`                | `GenerativeAnswerResponse`           | `str` (answer)                         |
| `generate_article_from_text(...)`           | `POST /api/generate_article_from_text`       | `GenerateArticleFromTextResponse`    | `ArticleText`                          |
| `generate_article_from_texts(...)`          | `POST /api/generate_article_from_texts`      | `GenerateArticleFromTextsResponse`   | `ArticleText`                          |
| `create_full_article_from_texts(...)`       | `POST /api/create_full_article_from_texts`   | `CreateFullArticleFromTextsResponse` | `ArticleText`                          |
| `generate_questions(...)`                   | `POST /api/generate_questions`               | `GenerateQuestionsResponse`          | `list[TextQuestions]`                  |
| `generate_label(...)`                       | `POST /api/generate_label`                   | `GenerateLabelResponse`              | `str` (label)                          |

---

## 🧱 Class hierarchy

```text
BaseResponse                 # extra keys ignored (pydantic default)
├── PingResponse
├── VersionResponse
├── ModelInfo
├── ModelsListResponse
├── Polarity3cItem
├── TranslateItem
├── TextQuestions
├── ArticleText
└── GenerationResponse       # adds: generation_time: Optional[float]
    ├── ConversationResponse
    ├── ExtendedConversationResponse
    ├── Polarity3cResponse
    ├── TranslateResponse
    ├── SimplifyTextResponse
    ├── GenerativeAnswerResponse
    ├── GenerateLabelResponse
    ├── GenerateArticleFromTextResponse
    ├── GenerateArticleFromTextsResponse
    └── CreateFullArticleFromTextsResponse
```

* `BaseResponse` – the common base. It does not define payload fields; it only sets the shared model configuration
  (unknown keys are ignored).
* `GenerationResponse` – the base for every **generative** endpoint; it contributes the
  `generation_time` field. Concrete subclasses declare the type of `response`.
* `BaseResponse`/`GenerationResponse` are also the base for the small nested item models (`Polarity3cItem`,
  `TranslateItem`, `TextQuestions`, `ArticleText`, `ModelInfo`).

---

## 📚 Model reference

### Health / meta

```python
class PingResponse(BaseResponse):
    status: bool = True  # True on success
    body: Optional[str] = None  # e.g. "pong"


class VersionResponse(BaseResponse):
    version: str = ""  # e.g. "1.4.2"


class ModelInfo(BaseResponse):
    id: str  # model identifier, e.g. "google/gemma-3-12b-it"
    object: Optional[str] = None
    created: Optional[float] = None
    owned_by: Optional[str] = None


class ModelsListResponse(BaseResponse):
    object: str = "list"
    data: List[ModelInfo] = []

    @property
    def ids(self) -> List[str]:  # convenience: just the identifiers
        ...
```

> `models()` previously returned `List[str]`. It now returns `ModelsListResponse`;
> read `client.models().ids` to get the previous list of names, or
> `client.models().data` for the full entries.

### Conversation

```python
class ConversationResponse(GenerationResponse):
    response: Optional[str] = None  # the assistant's reply text


class ExtendedConversationResponse(GenerationResponse):
    response: Optional[str] = None  # the assistant's reply text
```

### Per‑text (list) utilities

```python
class Polarity3cItem(BaseResponse):
    original: str = ""  # the input text
    polarity: str = ""  # "positive" | "negative" | "ambivalent"


class Polarity3cResponse(GenerationResponse):
    response: List[Polarity3cItem] = []  # one item per input text


class TranslateItem(BaseResponse):
    original: str = ""  # the input text
    translated: str = ""  # the translation


class TranslateResponse(GenerationResponse):
    response: List[TranslateItem] = []  # one item per input text


class SimplifyTextResponse(GenerationResponse):
    response: List[str] = []  # the simplified texts, in input order


class TextQuestions(BaseResponse):
    text: str = ""  # the input text
    questions: List[str] = []  # the generated questions


class GenerateQuestionsResponse(GenerationResponse):
    response: List[TextQuestions] = []  # one entry per input text
```

### Single‑output utilities

```python
class GenerativeAnswerResponse(GenerationResponse):
    response: Optional[str] = None  # the generated answer


class GenerateLabelResponse(GenerationResponse):
    response: Optional[str] = None  # the generated category label
```

### Article utilities

```python
class ArticleText(BaseResponse):
    article_text: Optional[str] = None  # the generated article


class GenerateArticleFromTextResponse(GenerationResponse):
    response: ArticleText = ArticleText()


class GenerateArticleFromTextsResponse(GenerationResponse):
    response: ArticleText = ArticleText()


class CreateFullArticleFromTextsResponse(GenerationResponse):
    response: ArticleText = ArticleText()
```

---

## 🎨 Design decisions

**Tolerance over strictness.** Real router responses can carry extra keys (the
`status`/`body` envelope, book‑keeping fields) and sometimes omit an optional field. The models are therefore
intentionally permissive:

* **Unknown keys are ignored** (Pydantic's default, re‑stated in `BaseResponse` via
  `ConfigDict(extra="ignore")`).
* **Fields have sensible defaults** — `None` for strings, `[]` for lists, and an empty
  `ArticleText` for the article payload — so a partial response still validates.
* **`generation_time` is optional**, because some deployments/versions may omit it.

This means the same model validates both the canonical server payload (`{"response": …, "generation_time": …}`) *and* a
partial/`status`‑wrapped body (`{"status": true, "response": …}`).

**`response` is the single point of variation.** Every generation endpoint returns a
`response` key; only its *type* differs (string vs. list vs. nested object). The subclasses pin that type, so
`resp.response` is always the right shape for the method you called.

**No cross‑model inheritance for payload types.** Each concrete response declares its own
`response` field (rather than a shared `Any`) so the type system and the JSON schema reflect the real payload.

---

## 🚀 Usage examples

### Access fields (typed)

```python
from llm_router_lib import LLMRouterClient

client = LLMRouterClient(api="http://localhost:8080", token="...")

# Conversation — a single reply string
conv = client.conversation_with_model(
    payload={"model_name": "google/gemma-3-12b-it",
             "user_last_statement": "Hello!"}
)
print(conv.response)  # "Hi! How can I help?"
print(conv.generation_time)  # 0.42 (seconds)

# Translate — one item per input text
tr = client.translate(texts=["Hello world", "Thank you"], model="speakleash/Bielik-11B-v2.3-Instruct")
for item in tr.response:
    print(item.original, "->", item.translated)

# Polarity — one item per input text
pol = client.polarity_3c(texts=["Great product!", "Terrible."], model="google/gemma-3-12b-it")
print(pol.response[0].polarity)  # "positive"

# Article — nested object
art = client.generate_article_from_text(text="…", model="google/gemma-3-12b-it")
print(art.response.article_text)
```

### Serialize / export

```python
# To a plain dict
d = tr.model_dump()  # {"response": [{"original":…, "translated":…}], "generation_time": …}

# To JSON
s = tr.model_dump_json()  # '...'

# To a JSON Schema (for docs / codegen / contract tests)
schema = TranslateResponse.model_json_schema()
```

### Round‑trip (validate a stored/`status`‑wrapped body)

```python
from llm_router_lib.data_models.response import TranslateResponse

body = {"status": True,
        "response": [{"original": "Hi", "translated": "Hej"}]}
tr = TranslateResponse.model_validate(body)  # extra "status" key is ignored
print(tr.response[0].translated)  # "Hej"
```

---

## 🔁 Backward compatibility

The change is **source‑breaking** for code that treated the return value as a `dict`:

| Before                              | After                                             | Migration                   |
|-------------------------------------|---------------------------------------------------|-----------------------------|
| `resp["response"]`                  | `resp.response`                                   | attribute access            |
| `resp["response"][0]["translated"]` | `resp.response[0].translated`                     | attribute access            |
| `resp["generation_time"]`           | `resp.generation_time`                            | attribute access            |
| `resp.get("response")`              | `resp.response` (already `None`/`[]` when absent) | no guard needed             |
| `client.models()` → `List[str]`     | `client.models()` → `ModelsListResponse`          | use `.ids` for the old list |

If you still need a `dict`, call `model_dump()` on the result. The integration helper
`llm_router_lib/tests/llm_router_client.py` already does this automatically before
`json.dumps(...)`.

---

## ➕ Adding a new endpoint model

When a new router endpoint is added, mirror the pattern:

1. **Define the model** in `data_models/response.py`:
    * subclass `GenerationResponse` for a generative endpoint and declare `response` with the correct type, or subclass
      `BaseResponse` for a health/meta style endpoint.
2. **Export it** from `data_models/__init__.py` (add the import + the `__all__` entry).
3. **Wire the client method** in `client.py`:
    * import the model,
    * annotate the method's return type,
    * return `YourModel.model_validate(Service(self.http, self.logger).call_post(payload))`.
4. **Document** it in the table above and add the field to the reference section.
5. **Test** both the canonical payload and a partial/`status`‑wrapped payload.

---

## ✅ Testing notes

* `llm_router_api/tests/test_*.py` — the client tests now assert
  `isinstance(resp, <Response>)` **and** check the typed fields (`resp.response`, `resp.response[0].translated`, …)
  rather than dict equality.
* Models validate both the canonical `{"response": …, "generation_time": …}` body and a partial
  `{"status": true, "response": …}` body.
* `llm_router_lib/tests/llm_router_client.py` serialises model results with
  `model_dump()` before printing JSON.

---

## 🧾 File map

| File                                     | Responsibility                                                    |
|------------------------------------------|-------------------------------------------------------------------|
| `llm_router_lib/data_models/response.py` | All response model definitions                                    |
| `llm_router_lib/data_models/__init__.py` | Re‑exports the response models                                    |
| `llm_router_lib/client.py`               | `LLMRouterClient` — every method returns a response model         |
| `llm_router_api/endpoints/builtin/*.py`  | Server side — the source of the response shapes the models mirror |
