## Jak tworzyć endpointy w llm-proxy-api – przewodnik

Poniżej zebrano kluczowe informacje o tym, jak definiować i konfigurować endpointy (EP) na podstawie klas z `endpoints.*`, z odniesieniem do logiki wykonywania w `endpoint_i.EndpointWithHttpRequestI.run_ep(...)`. Uwzględniono też role atrybutów/stałych takich jak `self._map_prompt`, `self._prompt_str_postfix`, `_prepare_response_function`, `_prompt_str_force`, `SYSTEM_PROMPT_NAME`, `REQUIRED_ARGS`, `OPTIONAL_ARGS` oraz parametry konstruktora.

1) Hierarchia i warianty bazowe
- EndpointI: baza dla EP (gdy serwis nie działa jako proxy). Definiuje ogólne API i walidację argumentów, ale nie implementuje run_ep.
- EndpointWithHttpRequestI: rozszerza EndpointI o wysyłkę żądań HTTP do zewnętrznego LLM. Ma pełną implementację run_ep, obsługę streamingu i wstrzykiwania promptu systemowego.
- PassthroughI: dziedziczy z EndpointWithHttpRequestI i domyślnie “przepuszcza” payload (prepare_payload zwraca parametry bez zmian). Użyteczne dla OpenAI‑kompatybilnych EP, gdzie chcemy prosto forwardować żądania.

Dlaczego w openai.py dziedziczymy z PassthroughI?
- Bo endpointy OpenAI‑kompatybilne często wymagają minimalnej logiki – wystarczy przekazać dalej to, co przyszło. PassthroughI upraszcza implementację (brak wymuszonych argumentów, brak system promptu, gotowy run_ep proxy).

2) Cykl wykonania – co robi run_ep w EndpointWithHttpRequestI
W dużym skrócie:
- Inicjalizacja zegara i wyzerowanie atrybutów promptu: `_map_prompt`, `_prompt_str_force`, `_prompt_str_postfix`.
- Wywołanie prepare_payload(params): tu podklasa ma przekształcić wejście do formatu, jaki rozumie backend (np. ułożyć messages, przepisać model_name → model, ustawić stream itp.). Jeśli zwróci strukturę z `"status": False`, run_ep zwróci ją bez dalszego przetwarzania.
- Jeśli ustawiono direct_return=True, zwracany jest wynik prepare_payload bez proxy.
- Tryb “simple proxy”: jeżeli klasa nie definiuje REQUIRED_ARGS (pusta lista) – traktujemy EP jako bezpośredni proxy do odpowiednika po stronie modelu. Wtedy:
  - `_set_model` wybiera model na podstawie pól z MODEL_NAME_PARAMS.
  - Jeżeli typ API modelu jest zgodny z typami EP (`api_types`), payload jest przekazywany dalej do odpowiedniego URL (z opcjonalnym stream).
- Jeżeli to nie simple proxy:
  - `_resolve_prompt_name(...)` przygotowuje system prompt (opisane w pkt 3).
  - `__dispatch_external_api_model(params)` ustawia `_api_model` na podstawie nazwy modelu.
  - Wyznaczamy docelowy URL przez `ApiTypesDispatcher` (np. chat_ep dla danego `api_type`).
  - Obsługa stream=False/True (w tym wariancie streaming może być ograniczony – komunikat o braku wsparcia).
  - `_call_http_request(...)` wykonuje POST/GET do hosta modelu, składając finalny payload (w tym system message, jeśli jest).

Dodatkowe ścieżki:
- `call_for_each_user_msg=True`: dla zadań wielotekstowych – wysyłamy osobne żądanie dla każdej wiadomości użytkownika, a wynik agregujemy przez `_prepare_response_function`.

3) System prompt i modyfikacje treści – jak działają pola
- SYSTEM_PROMPT_NAME: słownik { "pl": prompt_id, "en": prompt_id }. W prepare_payload ustawiasz wymagania EP, a run_ep w `_resolve_prompt_name`:
  - wybiera język z parametru LANGUAGE_PARAM (z defaultem DEFAULT_EP_LANGUAGE),
  - pobiera treść promptu systemowego przez `PromptHandler` jeśli zdefiniowano nazwę,
  - stosuje `_map_prompt` – słownik zamian {placeholder: tekst}, np. wstrzyknięcie liczby pytań, treści zapytania użytkownika,
  - dokleja `_prompt_str_postfix` na końcu system promptu (np. dodatkowa instrukcja),
  - jeśli `_prompt_str_force` jest ustawione – nadpisuje całą treść system promptu (pomija nazwę/system prompt z plików).
Efekt: jeśli `_prompt_str` ostatecznie jest zbudowany, to zostaje dodany do messages jako pierwszy element: {"role": "system", "content": self._prompt_str}.

Kiedy to ustawiać?
- W prepare_payload:
  - self._map_prompt: gdy chcesz w promptach z zasobów podmienić znaczniki (np. ##QUESTION_NUM_STR##).
  - self._prompt_str_postfix: gdy EP potrzebuje dokleić końcową uwagę/regułę do system promptu.
  - self._prompt_str_force: gdy chcesz zignorować pliki system promptów i podać treść wprost (np. gdy przychodzi z parametru system_prompt).

Wpływ na wykonanie EP:
- To, co zbudujesz jako `_prompt_str`, zostanie dołączone jako system message do każdej prośby HTTP (chyba że `call_for_each_user_msg` → wtedy system message łączony jest każdorazowo z pojedynczym user message).

4) Funkcje/hooki
- `_prepare_response_function`: opcjonalny hook do post‑przetwarzania odpowiedzi HTTP:
  - Jeśli ustawiony i wywołujemy pojedyncze żądanie – zostanie użyty do transformacji `Response` na docelowy obiekt (zamiast response.json()).
  - Jeśli `call_for_each_user_msg=True`, MUSI być ustawiony – wtedy dostaje listę Response oraz listę treści wejściowych i zwraca końcową strukturę odpowiedzi złożoną z wielu wyników.
Wpływ: pozwala kontrolować format odpowiedzi (np. spłaszczyć choices → content, policzyć czas generacji, zmapować odpowiedzi do oryginalnych tekstów itp.).

5) Walidacja parametrów – REQUIRED_ARGS i OPTIONAL_ARGS
- REQUIRED_ARGS: lista nazw parametrów wymaganych przez EP. Dekorator/walidacja wywoła `_check_required_params`, co skutkuje błędem 400 przy brakach. Jeśli lista jest pusta, EP może pracować w trybie simple proxy (opis wyżej).
- OPTIONAL_ARGS: lista parametrów opcjonalnych – semantyczna informacja/konwencja, przydatna w walidatorach/modelach danych (wbudowane EP korzystają z Pydanticowych modeli w prepare_payload).

Wpływ: ustalenie REQUIRED_ARGS bezpośrednio wpływa na ścieżkę run_ep – pusta lista aktywuje logikę “simple proxy”.

6) Parametry konstruktora EP – co ustawiają i jaki mają wpływ
Konstruktor (sumarycznie z EndpointI i EndpointWithHttpRequestI):

- ep_name: ścieżka URL dla EP. Rejestrator dołoży prefix (chyba że wyłączysz).
- api_types: lista typów API (np. ["openai", "ollama", "builtin"]). Używane do:
  - walidacji wsparcia (musi przecinać się z globalnym API_TYPES),
  - prostego proxy (gdy typ modelu == typ EP).
- method: "GET" lub "POST". Wpływa na sposób ekstrakcji parametrów i wysyłkę requests.get/post.
- logger_level, logger_file_name: konfiguracja logowania tego EP.
- prompt_handler: potrzebny, jeśli używasz SYSTEM_PROMPT_NAME i chcesz ładować prompty z zasobów.
- model_handler: wymagany do mapowania nazw modeli na konfigurację hosta/typ API/nazwę modelu. Bez niego EP proxy nie wybierze poprawnie backendu.
- dont_add_api_prefix: True → endpoint rejestrowany bez globalnego prefixu (np. chcemy wystawić “/” lub “/models” bez “/api”). Wpływa na finalny adres.
- direct_return: True → run_ep zwróci wynik prepare_payload bez proxy (przydatne dla EP, które same generują odpowiedź lub zwracają dane lokalne).
- timeout (EndpointWithHttpRequestI): limit czasu dla requests do backendów.
- call_for_each_user_msg: True → rozbija messages na osobne żądania dla każdej wiadomości “user” i łączy wynik przez `_prepare_response_function`.

7) Jak dodać nowy endpoint – kroki
- Wybierz bazę:
  - Gdy chcesz tylko forwardować (OpenAI‑like) → dziedzicz z PassthroughI.
  - Gdy potrzebujesz przetwarzania (walidacji, budowy promptów, mapowania pól) → dziedzicz z EndpointWithHttpRequestI.
- Ustal wartości klasowe:
  - REQUIRED_ARGS i OPTIONAL_ARGS (lista lub None).
  - SYSTEM_PROMPT_NAME: {"pl": "...", "en": "..."} lub None.
- Zaimplementuj prepare_payload(self, params):
  - Wykonaj walidację i transformację wejścia (np. Pydantic).
  - Ustaw pola promptu, jeśli potrzebne: self._map_prompt, self._prompt_str_postfix, self._prompt_str_force.
  - Zbuduj payload pod backend:
    - Ustal "model" (często z "model_name"),
    - Ustal "messages" (z system promptem doda się automatycznie),
    - Obsłuż "stream" (True/False).
  - Jeśli EP ma działać jako stała odpowiedź lub jako lokalny handler – ustaw self.direct_return=True i zwróć gotowy obiekt (str/dict).
- Jeśli chcesz per‑wiadomość użytkownika (batch na wielu tekstach):
  - Ustaw w konstruktorze call_for_each_user_msg=True.
  - Zdefiniuj self._prepare_response_function – funkcję, która z listy odpowiedzi i listy treści zbuduje końcowy wynik.
- Skonstruuj klasę EP z parametrami:
  - ep_name, method, api_types, dont_add_api_prefix, direct_return, timeout.
- Autorejestracja:
  - Klasa zostanie znaleziona i zainstancjonowana przez autoloader (o ile konstruktor pasuje do wzorca bez‑argumentowego z przekazywanymi dependency – patrz autoloader) lub z konfiguracji. Alternatywnie możesz dodać ją do listy rejestracji ręcznie.
- Po uruchomieniu, rejestrator Flask’a zarejestruje trasę zgodnie z ep_name i add_api_prefix.

8) Najczęstsze wzorce użycia
- Prosty proxy OpenAI:
  - Dziedzicz z PassthroughI, REQUIRED_ARGS=None, SYSTEM_PROMPT_NAME=None.
  - prepare_payload nie robi nic (zwraca params).
  - api_types zawiera typy zgodne z backendami, które chcesz wspierać.
- EP z wbudowanym promptem systemowym:
  - Dziedzicz z EndpointWithHttpRequestI.
  - Ustal SYSTEM_PROMPT_NAME (pl/en).
  - W prepare_payload ustaw mapowania/self._prompt_str_postfix/force wg potrzeb, przebuduj “messages” i “model”.
  - Jeśli chcesz wielokrotne wywołania – call_for_each_user_msg=True i ustaw `_prepare_response_function`.

9) Szybkie wyjaśnienie wymienionych pól
- self._map_prompt: mapowanie placeholderów w treści promptu systemowego; wpływa na finalny “system content”.
- self._prompt_str_postfix: tekst doklejany na końcu system promptu; rozszerza instrukcje.
- self._prepare_response_function: hak do post‑przetwarzania odpowiedzi HTTP (pojedynczej lub wielu); decyduje o finalnym kształcie JSON.
- self._prompt_str_force: pozwala całkowicie nadpisać system prompt (np. gdy klient przysłał własny).
- SYSTEM_PROMPT_NAME: nazwy promptów per język; determinuje, co `_resolve_prompt_name` pobierze z repozytorium promptów.
- REQUIRED_ARGS: jeśli puste → EP może pracować jako simple proxy; jeśli niepuste → brak tych argumentów da błąd i wyłączy tryb proxy.
- OPTIONAL_ARGS: informacyjne – pomocne przy modelach danych/validacji.

10) Dodatkowe uwagi praktyczne
- Streaming:
  - Jeśli payload ma "stream": True i EP działa jako simple proxy – run_ep przełączy się na tryb strumieniowania i zwróci iterator NDJSON.
  - W trybie niestandardowym (nie simple proxy) streaming może być ograniczony – zwróć odpowiedni komunikat lub zaimplementuj `_call_http_request_stream`.
- Prefix URL:
  - dont_add_api_prefix=True → wystawiasz endpoint bez globalnego prefiksu (np. “/”, “/models”).
- Modele:
  - `_set_model` i `__dispatch_external_api_model` wymagają obecności jednego z kluczy z MODEL_NAME_PARAMS (np. “model”, “model_name”, zależnie od konfiguracji). Upewnij się, że prepare_payload ujednolica to do “model” przed wywołaniem requests.

## Propozycja EP: BatchFileSummaries – podsumowania plików z listy

Cel: przyjmuje listę “plików” (np. już wczytane treści lub krótkie metadane z treścią), przetwarza każdy osobno i zwraca ustrukturyzowane podsumowania + kluczowe punkty. Wspiera per‑wiadomość wywołania (jeden request do modelu na jeden plik) i agreguje wynik.

- Ścieżka: POST /api/batch_file_summaries
- Dziedziczenie: EndpointWithHttpRequestI
- API types: ["builtin"] (lub inne, których używacie)
- REQUIRED_ARGS:
  - model_name: str
  - language: "pl" | "en"
  - files: List[ { "name": str, "content": str } ]
- OPTIONAL_ARGS:
  - stream: bool = False
  - max_points: int = 5
  - style_hint: Optional[str] (np. “zwięźle, bez marketingu”)

Prompt (system): dwa warianty językowe, zapisane jako szablon z placeholderami:
- pl (SYSTEM_PROMPT_NAME["pl"] = "builtin/system/pl/batch-file-summaries"):
  Jesteś asystentem do analizy dokumentów. Dla KAŻDEGO wejściowego dokumentu zrób:
  1) 3–5 zdań podsumowania.
  2) Wypunktuj maksymalnie ##MAX_POINTS## kluczowych informacji.
  3) Styl: ##STYLE_HINT##.
  Odpowiadaj precyzyjnie i operuj tylko na przekazanej treści.
- en (SYSTEM_PROMPT_NAME["en"] = "builtin/system/en/batch-file-summaries"):
  You are a document analysis assistant. For EACH input document:
  1) Provide a 3–5 sentence summary.
  2) Bullet up to ##MAX_POINTS## key points.
  3) Style: ##STYLE_HINT##.
  Be precise and rely only on the provided content.

Wykorzystanie hooków:
- call_for_each_user_msg=True – każdy plik → osobne “messages” → osobny call.
- self._map_prompt:
  - "##MAX_POINTS##" ← wartość max_points,
  - "##STYLE_HINT##" ← style_hint lub “neutralny”/“neutral”.
- self._prepare_response_function – agreguje listę odpowiedzi w strukturę: [{name, summary, key_points: []}, …].

Schemat payloadu wejściowego (przykład):
{
  "model_name": "google/gemma-3-12b-it",
  "language": "pl",
  "files": [
    {"name": "umowa_1.txt", "content": "…"},
    {"name": "raport_q2.pdf", "content": "…"}
  ],
  "max_points": 5,
  "style_hint": "zwięźle i rzeczowo",
  "stream": false
}

Schemat odpowiedzi (przykład):
{
  "response": [
    {
      "name": "umowa_1.txt",
      "summary": "…",
      "key_points": ["…", "…"]
    },
    {
      "name": "raport_q2.pdf",
      "summary": "…",
      "key_points": ["…", "…"]
    }
  ],
  "generation_time": 1.234
}

Implementacja – klasa EP (skrót):

- Konstruktor:
  - ep_name="batch_file_summaries"
  - api_types=["builtin"]
  - method="POST"
  - call_for_each_user_msg=True
  - SYSTEM_PROMPT_NAME ustawione jak wyżej
- prepare_payload:
  - Walidacja pól (model_name, language, files).
  - self._map_prompt z MAX_POINTS/STYLE_HINT.
  - Zbuduj messages = [{"role": "user", "content": file["content"]} dla każdego pliku] – ważne: to lista wiadomości USER, jedna na plik (bo call_for_each_user_msg).
  - Zachowaj równolegle listę nazw plików (do agregacji).
  - Ustaw model = model_name, stream domyślnie False.
- _prepare_response_function(responses, contents):
  - Każdy response → wyciągnij “message.content”.
  - Prosta heurystyka: rozdziel treść na “summary” i “key points” (np. szukając pierwszej listy wypunktowanej po podsumowaniu); lub przyjąć, że model zwróci sekcję “Podsumowanie:” i “Kluczowe punkty:”.
  - Złącz z oryginalnymi nazwami plików (paruj po indeksie).

Minimalny prompt user (per plik), który model otrzyma:
Treść dokumentu:
<content>

Instrukcja (wynika z system promptu).

Wariant bez plików binarnych
- Endpoint zakłada, że “files” zawiera już tekst (np. OCR/ekstrakcja wcześniej).
- Jeśli w przyszłości dojdzie upload, należy dodać warstwę ekstrakcji tekstu przed wywołaniami LLM (poza tym EP).

---

```python
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, validator

# Wymagane i opcjonalne argumenty dla EP
BFS_REQ: List[str] = ["model_name", "language", "files"]
BFS_OPT: List[str] = ["stream", "max_points", "style_hint"]

class BatchFileInput(BaseModel):
    name: str = Field(..., description="Nazwa pliku (np. raport.pdf)")
    content: str = Field(..., description="Tekstowa treść pliku")

class BatchFileSummariesModel(BaseModel):
    model_name: str
    language: str = Field(..., description="Kod języka: 'pl' lub 'en'")
    files: List[BatchFileInput] = Field(..., description="Lista plików do przetworzenia")
    stream: bool = False
    max_points: int = 5
    style_hint: Optional[str] = None

    @validator("language")
    def _lang_check(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in {"pl", "en"}:
            raise ValueError("language must be 'pl' or 'en'")
        return v

    @validator("max_points")
    def _points_check(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_points must be > 0")
        return v
```

```python
from typing import Optional, Dict, Any, List
import time

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import EndpointWithHttpRequestI
from llm_proxy_rest.core.data_models.batch_file_summaries import (
    BatchFileSummariesModel,
    BFS_REQ,
    BFS_OPT,
)


class BatchFileSummariesHandler(EndpointWithHttpRequestI):
    """
    POST /api/batch_file_summaries

    Przetwarza listę plików (każdy jako osobny user message) i zwraca
    listę podsumowań oraz kluczowych punktów.
    """

    REQUIRED_ARGS = BFS_REQ
    OPTIONAL_ARGS = BFS_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/batch-file-summaries",
        "en": "builtin/system/en/batch-file-summaries",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "batch_file_summaries",
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=True,
        )

        # Hook do agregacji wyników per plik
        self._prepare_response_function = self.__prepare_response_function

        # bufor nazw plików (indeksy zgodne z kolejnością messages[user])
        self.__file_names: List[str] = []

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Buduje payload do backendu:
        - mapuje model_name -> model
        - przygotowuje messages: każdy plik jako osobny user message
        - ustawia mapowania do promptu systemowego (max_points, style_hint)
        """
        options = BatchFileSummariesModel(**(params or {}))
        payload = options.model_dump()

        # mapowania do promptu
        style_hint = (payload.get("style_hint") or "").strip()
        self._map_prompt = {
            "##MAX_POINTS##": str(payload["max_points"]),
            "##STYLE_HINT##": (style_hint if style_hint else ("neutralny" if payload["language"] == "pl" else "neutral")),
        }

        # przygotuj user messages (po jednym na plik)
        self.__file_names = [f["name"] for f in payload["files"]]
        messages = [{"role": "user", "content": f["content"]} for f in payload["files"]]

        # finalny payload do calla
        out = {
            "model": payload["model_name"],
            "stream": bool(payload.get("stream", False)),
            "messages": messages,
            # dodatkowe parametry modelu można tu dodać, jeśli wymagane
        }
        return out

    def __prepare_response_function(self, responses, contents):
        """
        Agregacja odpowiedzi z wielu wywołań (per user message).
        responses: List[requests.Response]
        contents: List[str] -> tu to zawartość plików (kolejność == messages)
        """
        assert len(responses) == len(contents) == len(self.__file_names)

        result = []
        for idx, response in enumerate(responses):
            _, _, text = self._get_choices_from_response(response=response)
            parsed = self.__parse_summary_and_points(text)
            result.append(
                {
                    "name": self.__file_names[idx],
                    "summary": parsed["summary"],
                    "key_points": parsed["key_points"],
                }
            )

        return {
            "response": result,
            "generation_time": time.time() - self._start_time,
        }

    @staticmethod
    def __parse_summary_and_points(text: str) -> Dict[str, Any]:
        """
        Prosta heurystyka: zakładamy format:
        Podsumowanie:/Summary:
        ...
        Kluczowe punkty:/Key points:
        - ...
        - ...
        Jeśli model zwróci inaczej, zwracamy całość jako summary.
        """
        if not text:
            return {"summary": "", "key_points": []}

        t = text.strip()
        lower = t.lower()

        # Znaczniki sekcji w PL/EN
        markers = [
            ("podsumowanie:", "kluczowe punkty:"),
            ("summary:", "key points:"),
        ]

        for sum_m, pts_m in markers:
            i_sum = lower.find(sum_m)
            i_pts = lower.find(pts_m)
            if i_sum != -1 and i_pts != -1 and i_sum < i_pts:
                sum_part = t[i_sum + len(sum_m): i_pts].strip()
                pts_part = t[i_pts + len(pts_m):].strip()
                key_points = [
                    p.strip(" -•\t").strip()
                    for p in pts_part.splitlines()
                    if p.strip()
                ]
                # odfiltruj puste/wstępne wiersze
                key_points = [p for p in key_points if len(p)]
                return {"summary": sum_part, "key_points": key_points}

        # fallback – całość jako summary
        return {"summary": t, "key_points": []}
```

```
Jesteś asystentem do analizy dokumentów. Dla KAŻDEGO wejściowego dokumentu wykonujesz:
1) Podsumowanie w 3–5 zdaniach.
2) Wypunktowanie maksymalnie ##MAX_POINTS## kluczowych informacji.
3) Styl: ##STYLE_HINT##.

Instrukcje:
- Odpowiadaj precyzyjnie i tylko na podstawie dostarczonej treści.
- Wynik formatuj sekcjami:
Podsumowanie:
<tu wstaw podsumowanie>

Kluczowe punkty:
- punkt 1
- punkt 2
- ...
```

```
You are a document analysis assistant. For EACH input document, produce:
1) A 3–5 sentence summary.
2) Up to ##MAX_POINTS## key points in bullets.
3) Style: ##STYLE_HINT##.

Instructions:
- Be precise and rely only on the provided content.
- Format the result using sections:
Summary:
<put the summary here>

Key points:
- point 1
- point 2
- ...
```
