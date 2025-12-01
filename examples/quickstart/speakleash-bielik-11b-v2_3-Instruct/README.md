# 🚀 **Przewodnik Szybkiego Startu** dla `speakleash/Bielik-11B-v2.3-Instruct` z **vLLM** & **LLM‑Router**

Ten przewodnik prowadzi Cię krok po kroku przez:

1. **Instalację vLLM** i modelu `speakleash/Bielik-11B-v2.3-Instruct`.
2. **Instalację LLM‑Router** (bramki API).
3. **Uruchomienie routera** z konfiguracją modeli dostarczoną w `models-config.json`.

Wszystkie polecenia zakładają, że pracujesz na systemie Unix‑like (Linux/macOS) z **Python 3.10.6**, `virtualenv` oraz (
opcjonalnie) kartą GPU obsługującą CUDA 11.8.

---  

## 📋 **Wymagania wstępne**

| Wymaganie     | Szczegóły                                                    |
|---------------|--------------------------------------------------------------|
| **OS**        | Ubuntu 20.04 + (lub dowolna nowsza dystrybucja Linux/macOS)  |
| **Python**    | 3.10.6 (domyślna wersja projektu)                            |
| **GPU**       | CUDA 11.8 + (minimum 12 GB VRAM) **lub** środowisko CPU‑only |
| **Narzędzia** | `git`, `curl`, `jq` (opcjonalnie, przydatne do testowania)   |
| **Sieć**      | Dostęp do PyPI oraz Hugging Face w celu pobrania modelu      |

---  

## 1️⃣ **Utworzenie i aktywacja wirtualnego środowiska**

```shell script
# (opcjonalnie) utwórz katalog demo i przejdź do niego
mkdir -p ~/bielik-demo && cd $_

# Inicjalizacja venv
python3 -m venv .venv
source .venv/bin/activate

# Aktualizacja pip (zawsze dobry pomysł)
pip install --upgrade pip
```

---  

## 2️⃣ Instalacja **vLLM** oraz pobranie modelu Bielik

> Pełną instrukcję znajdziesz w pliku [`VLLM.md`](./VLLM.md).

---  

## 3️⃣ **Uruchomienie serwera vLLM**

Skopiuj do bieżącego katalogu dostarczony skrypt Bash (dostosuj ścieżkę, jeśli potrzebujesz) i uruchom go:

```shell script
cp path/to/llm-router/examples/quickstart/speakleash-bielik-11b-v2_3-Instruct/run-bielik-11b-v2_3-vllm.sh .
chmod +x run-bielik-11b-v2_3-vllm.sh

# Uruchom (warto w tmux/screen)
./run-bielik-11b-v2_3-vllm.sh
```

Serwer nasłuchuje na **`http://0.0.0.0:7000`** i udostępnia endpoint zgodny z OpenAI pod `/v1/chat/completions`.

Możesz szybko go przetestować:

```shell script
curl http://localhost:7000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "speakleash/Bielik-11B-v2.3-Instruct",
        "messages": [{"role": "user", "content": "Cześć, jak się masz?"}],
        "max_tokens": 100
      }' | jq
```

Powinieneś otrzymać odpowiedź w formacie JSON.

---  

## 4️⃣ Instalacja **LLM‑Router**

```shell script
# Sklonuj repozytorium (jeśli jeszcze go nie masz)
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router

# Instalacja core + API (w tym samym venv)
pip install .[api]

# (Opcjonalnie) wsparcie dla Prometheus
pip install .[api,metrics]
```

> **Uwaga:** Router używa tego samego wirtualnego środowiska, które utworzyłeś wcześniej, więc wszystkie zależności
> pozostają odizolowane.

---  

## 6️⃣ **Przygotowanie konfiguracji routera**

Plik `models-config.json` znajdujący się w katalogu **speakleash‑bielik** już zawiera definicję naszego modelu:

```json
{
  "speakleash_models": {
    "speakleash/Bielik-11B-v2.3-Instruct": {
      "providers": [
        {
          "id": "bielik-11B_v2_3-vllm-local:7000",
          "api_host": "http://localhost:7000/",
          "api_type": "vllm",
          "input_size": 56000,
          "weight": 1.0
        }
      ]
    }
  },
  "active_models": {
    "speakleash_models": [
      "speakleash/Bielik-11B-v2.3-Instruct"
    ]
  }
}
```

Skopiuj go (lub przenieś) do katalogu `resources/configs/` routera:

```shell script
mkdir -p resources/configs
cp path/to/speakleash-bielik/models-config.json resources/configs/
```

---  

## 6️⃣ Uruchomienie **LLM‑Router**

### Lokalny Gunicorn

W repozytorium znajduje się pomocniczy skrypt `run-rest-api-gunicorn.sh`. Upewnij się, że jest wykonywalny, a następnie
go uruchom:

```shell script
chmod +x run-rest-api-gunicorn.sh
./run-rest-api-gunicorn.sh
```

Domyślne zmienne środowiskowe (można zmienić w skrypcie):

| Zmienna                     | Domyślna wartość                       | Opis                              |
|-----------------------------|----------------------------------------|-----------------------------------|
| `LLM_ROUTER_SERVER_TYPE`    | `gunicorn`                             | Backend serwera                   |
| `LLM_ROUTER_SERVER_PORT`    | `8080`                                 | Port nasłuchiwania routera        |
| `LLM_ROUTER_MODELS_CONFIG`  | `resources/configs/models-config.json` | Ścieżka do pliku konfiguracyjnego |
| `LLM_ROUTER_USE_PROMETHEUS` | `1` (jeśli zainstalowano `metrics`)    | Włącza endpoint `/api/metrics`    |

Router będzie dostępny pod **`http://0.0.0.0:8080/api`**.
Pełna lista dostępnych zmiennych środowiskowych znajduje się w
[opisie zmiennych środowiskowych](../../../llm_router_api/README.md#environment-variables)

---  

## 7️⃣ **Test pełnego stosu (router → vLLM)**

```shell script
curl http://localhost:8080/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "speakleash/Bielik-11B-v2.3-Instruct",
        "messages": [{"role": "user", "content": "Opowiedz krótki żart."}],
        "max_tokens": 80
      }' | jq
```

Zapytanie przechodzi przez **LLM‑Router**, który przekazuje je do lokalnego serwera vLLM, a odpowiedź zostaje zwrócona w
formacie JSON.

---  

## 🚀 **Uruchamianie przykładów**

W folderze [`examples/`](../../../examples) znajduje się szereg przykładów (LangChain, LlamaIndex, OpenAI SDK, LiteLLM,
Haystack). Aby je uruchomić:

1. **Ustaw adres routera** – w środowisku (`LLM_ROUTER_HOST`) lub w pliku `examples/constants.py`:

```shell script
export LLM_ROUTER_HOST="http://localhost:8080/api"

# lub w Pythonie (constants.py):
HOST = "http://localhost:8080/api"
```

2. **Zainstaluj zależności przykładów**

```shell script
pip install -r examples/requirements.txt
```

3. **Uruchom wybrany przykład**

```shell script
python examples/langchain_example.py
python examples/llamaindex_example.py
python examples/openai_example.py
python examples/litellm_example.py
python examples/haystack_example.py
```

Wszystkie pozostałe szczegóły konfiguracji (obsługa promptów, strumieniowanie, użycie wielu modeli, obsługa błędów itp.)
są udokumentowane w poszczególnych plikach przykładów oraz w plikach [`examples/README.md`](../../README.md) i [
`examples/README_LLAMAINDEX.md`](../../README_LLAMAINDEX.md). Dostosuj jedynie zmienną `HOST`/`LLM_ROUTER_HOST`
(ewentualnie także `MODELS`), a przykłady automatycznie odpytają instancję uruchomionego llm‑routera.

---  

## 🎉 **Co dalej?**

| Obszar                    | Co możesz zrobić                                                                                                             |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------|
| **Prometheus**            | Jeśli włączyłeś `metrics`, dodaj endpoint `/api/metrics` do swojego systemu monitorującego.                                  |
| **Guardrails & Masking**  | Ustaw zmienne `LLM_ROUTER_FORCE_MASKING`, `LLM_ROUTER_FORCE_GUARDRAIL_REQUEST`, itp., aby dodać warstwy ochronne.            |
| **Wiele dostawców**       | Rozbuduj `models-config.json` o kolejne providery (np. Ollama, OpenAI) i eksperymentuj z różnymi strategiami load‑balancing. |
| **Aktualizacje**          | `pip install -U vllm` oraz `pip install -U llm-router` zapewnią najnowsze poprawki i funkcje.                                |
| **Optymalizacja pamięci** | Przy ograniczonej VRAM użyj flagi `--cpu-offload` w skrypcie `run-bielik-11b-v2_3-vllm.sh`.                                  |

---  

**Powodzenia i miłego korzystania z modelu Bielik!**

---