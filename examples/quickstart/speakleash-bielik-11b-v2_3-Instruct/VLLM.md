# vLLM + `speakleash/Bielik-11B-v2.3-Instruct-FP8` – Przewodnik Szybkiego Startu (Ubuntu)

> **Wymagania wstępne**
> - Ubuntu 20.04 lub nowszy
> - Python 3.10 (w projekcie używamy 3.10.6)
> - `virtualenv` (zainstalowany)
> - CUDA 11.8 + GPU **lub** środowisko tylko CPU

---  

## 1️⃣ Utwórz i aktywuj wirtualne środowisko

```
mkdir -p ~/bielik && cd ~/bielik
python3 -m venv .venv
source .venv/bin/activate
```

> Powoduje to utworzenie katalogu projektu, przygotowanie wirtualnego środowiska w folderze `.venv` oraz jego
> aktywację (w promptcie pojawi się `(.venv)`).

---  

## 2️⃣ Zainstaluj **vLLM**

```
pip install --upgrade pip
pip install "vllm[cuda]"
```

> Instalacja najnowszej wersji **vLLM** z obsługą GPU (CUDA zostanie wykryte automatycznie).  
> Jeśli nie masz GPU, użyj wersji CPU: `pip install vllm[cpu]`.

---  

### Sprawdź instalację

```
python -c "import vllm; print(vllm.__version__)"
```

Powinieneś zobaczyć wersję, np. `0.11.2`.

---  

## 4️⃣ Przygotuj środowisko do pobierania modelu

```
pip install huggingface_hub
```

---  

## 6️⃣ Pobierz model `speakleash/Bielik-11B-v2.3-Instruct-FP8`

```
mkdir -p ./speakleash/Bielik-11B-v2.3-Instruct-FP8
hf download speakleash/Bielik-11B-v2.3-Instruct-FP8 \
    --local-dir ./speakleash/Bielik-11B-v2.3-Instruct-FP8
```

> Model zostanie pobrany do wskazanego katalogu. Pliki będą także buforowane domyślnie w `~/.cache/huggingface/hub`.

---  

### (Opcjonalnie) Ustaw własny katalog cache

Jeśli chcesz, aby wszystkie modele były przechowywane wewnątrz projektu, ustaw zmienną przed pobraniem:

```
export HF_HOME=$PWD/.cache/huggingface   
# np. ./bielik/.cache/huggingface
```

---  

## 7️⃣ Uruchom serwer **vLLM**

Skopiuj gotowy skrypt Bash (przykładowa ścieżka – dostosuj do swojego projektu):

```
cp path/to/llm-router/examples/quickstart/speakleash-bielik-11b-v2_3-Instruct/run-bielik-11b-v2_3-vllm.sh .
bash run-bielik-11b-v2_3-vllm.sh
```

> **Wskazówka:** uruchom serwer w sesji `tmux` lub `screen`, aby pozostawał aktywny po rozłączeniu się z terminalem.

---  

## 8️⃣ Przetestuj endpoint

> > **INFO**: `curl` i `jq` to narzędzia systemowe.


```
curl http://localhost:7000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "speakleash/Bielik-11B-v2.3-Instruct-FP8",
        "messages": [{"role": "user", "content": "Cześć, jak się masz?"}],
        "max_tokens": 100
      }' | jq
```

Powinieneś otrzymać odpowiedź w formacie JSON, np.:

```json
{
  "id": "chatcmpl-xxxx",
  "object": "chat.completion",
  "created": 1764516430,
  "model": "speakleash/Bielik-11B-v2.3-Instruct-FP8",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Cześć! Jestem w pełni sprawny i gotowy do rozmowy. Jak mogę Ci pomóc?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 15,
    "total_tokens": 66,
    "completion_tokens": 51
  }
}
```

---  

## 9️⃣ Przydatne wskazówki

| Temat                       | Rekomendacja                                                                                                                              |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| **Pamięć**                  | `speakleash/Bielik-11B-v2.3-Instruct-FP8` potrzebuje ok. 12GB VRAM. Użyj `--cpu-offload` (jeśli wspierane) przy ograniczonej pamięci GPU. |
| **Lokalizacja cache**       | Ustaw `HF_HOME=$PWD/.cache/huggingface`, aby wszystkie pliki modelu znajdowały się w katalogu projektu.                                   |
| **Równoległość tokenizera** | `export TOKENIZERS_PARALLELISM=false` wyciszy ostrzeżenia tokenizera.                                                                     |
| **Wybór GPU**               | `export CUDA_VISIBLE_DEVICES=0` (lub inny indeks) przy wielu kartach GPU.                                                                 |
| **Aktualizacja**            | `pip install -U vllm` odświeża bibliotekę; przy następnym uruchomieniu serwera zostaną pobrane nowsze pliki modelu, jeśli są dostępne.    |
| **Dezaktywacja**            | Po zakończeniu pracy wystarczy wpisać `deactivate`, aby opuścić wirtualne środowisko.                                                     |

---  

## 🎉 Gotowe!

Masz już w pełni działające API kompatybilne z OpenAI, oparte na **vLLM** i modelu
**speakleash/Bielik-11B-v2.3-Instruct-FP8**.