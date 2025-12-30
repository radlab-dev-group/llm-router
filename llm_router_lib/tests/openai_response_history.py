from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from openai import OpenAI

# ----------------------------
# Konfiguracja klienta
# ----------------------------
client = OpenAI(
    base_url="http://192.168.100.65:8080",
    api_key="ollama",
)

MODEL = "gpt-oss:120b"


# ----------------------------
# Klasa pamięci rozmowy
# ----------------------------
@dataclass
class ChatMemory:
    system_prompt: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    summary: Optional[str] = None
    history_file: Optional[Path] = None  # plik do zapisu/ładowania

    def __post_init__(self) -> None:
        # 1️⃣ Dodajemy systemowy prompt
        self.items.append(
            {
                "role": "system",
                "content": [{"type": "text", "text": self.system_prompt}],
            }
        )

        # 2️⃣ Ładujemy istniejącą historię (jeśli plik istnieje)
        if self.history_file and self.history_file.exists():
            self._load_from_file()

    # -------------------------------------------------
    # Metody dodające wiadomości
    # -------------------------------------------------
    def add_user(self, text: str) -> None:
        self.items.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            }
        )
        self._save_to_file()

    def add_assistant(self, text: str) -> None:
        self.items.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            }
        )
        self._save_to_file()

    def add_tool_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Dodaje wynik wywołania narzędzia do historii"""
        self.items.append(
            {
                "role": "tool",
                "content": [
                    {
                        "type": "text",
                        "text": f" Wynik narzędzia **{tool_name}**:\n{json.dumps(result, ensure_ascii=False, indent=2)}",
                    }
                ],
            }
        )
        self._save_to_file()

    # -------------------------------------------------
    # Budowanie wejścia dla API
    # -------------------------------------------------
    def build_input(self) -> List[Dict[str, Any]]:
        """Zwraca listę wiadomości gotową do wysłania do API.
        Jeśli istnieje streszczenie – wstrzykuje je jako dodatkowy systemowy komunikat.
        """
        if self.summary:
            return [
                self.items[0],  # oryginalny system prompt
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": f"🔔 STRESZCZENIE DOTYCHCZASOWEJ ROZMOWY:\n{self.summary}",
                        }
                    ],
                },
                *self.items[1:],  # cała historia (bez pierwszego systemowego)
            ]
        return self.items

    # -------------------------------------------------
    # Obsługa długiej historii – STRESZCZANIE
    # -------------------------------------------------
    def approx_char_count(self) -> int:
        total = 0
        for msg in self.items:
            for c in msg.get("content", []):
                if c.get("type") == "text":
                    total += len(c.get("text", ""))
        if self.summary:
            total += len(self.summary)
        return total

    def summarize_history(self, keep_last_n: int = 6) -> None:
        """Streszcza starszą część historii, zostawiając ostatnie `keep_last_n` wiadomości."""
        if len(self.items) <= 1 + keep_last_n:
            return  # za krótko – nie streszczamy

        # Wydzielamy część do streszczenia (wszystko POZA ostatnimi `keep_last_n` wiadomościami)
        to_summarize = self.items[1:-keep_last_n]  # pomijamy systemowy prompt
        tail = self.items[-keep_last_n:]  # ostatnie wiadomości (zostają bez zmian)

        # Przygotowanie wejścia dla modelu‑streszczaciela
        summarizer_input = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "Jesteś ekspertem od streszczania rozmów. Stwórz KRÓTKIE podsumowanie (max 8 punktów) dotychczasowej rozmowy. Zachowaj kluczowe decyzje, preferencje użytkownika i ważne dane. Pisz po polsku.",
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "Streść poniższą historię:"}],
            },
            *to_summarize,
        ]

        print("\n🔄 Streszczam historię…\n")
        resp = client.responses.create(
            model=MODEL,
            input=summarizer_input,
            temperature=0.2,
        )
        self.summary = resp.output_text.strip()
        # Zastępujemy starą historię nową (system + ogon)
        self.items = [self.items[0]] + tail
        self._save_to_file()
        print(
            f"✅ Historia została streszczona! (długość: {len(self.summary)} znaków)\n"
        )

    # -------------------------------------------------
    # Zapisywanie / ładowanie historii do pliku JSON
    # -------------------------------------------------
    def _save_to_file(self) -> None:
        if not self.history_file:
            return
        data = {
            "system_prompt": self.system_prompt,
            "items": self.items,
            "summary": self.summary,
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_file(self) -> None:
        with open(self.history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.system_prompt = data["system_prompt"]
        self.items = data["items"]
        self.summary = data.get("summary")


# ----------------------------
# NARZĘDZIA (function calling)
# ----------------------------
def local_time_tool(_: Dict[str, Any]) -> Dict[str, Any]:
    """Zwraca aktualny czas (epoch + czytelny format)."""
    now = time.time()
    return {
        "epoch": now,
        "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "local_time",
            "description": "Zwraca aktualny czas systemowy (godzina, data).",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }
]

TOOL_DISPATCH = {"local_time": local_time_tool}


# ----------------------------
# GŁÓWNA LOGIKA CZATU
# ----------------------------
def run_with_tools(memory: ChatMemory, temperature: float = 0.7) -> str:
    """Wysyła historię do modelu. Obsługuje wywołania narzędzi."""
    # 1️⃣ Pierwsze wywołanie API
    resp = client.responses.create(
        model=MODEL,
        input=memory.build_input(),
        temperature=temperature,
        tools=TOOLS,  # usuń tę linię jeśli Twoje proxy nie obsługuje tools
    )

    # Sprawdzamy, czy model prosi o wywołanie narzędzia
    tool_calls = []
    for item in getattr(resp, "output", []):
        if isinstance(item, dict) and item.get("type") in (
            "tool_call",
            "function_call",
        ):
            tool_calls.append(item)

    if not tool_calls:
        return resp.output_text

    # 2️⃣ Wykonujemy każde narzędzie i dodajemy wynik do historii
    for call in tool_calls:
        # Normalizacja nazwy i argumentów (różne proxy mogą to nazywać inaczej)
        name = call.get("function", {}).get("name") or call.get("name")
        arg_str = call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(arg_str) if isinstance(arg_str, str) else arg_str
        except json.JSONDecodeError:
            args = {}

        if name not in TOOL_DISPATCH:
            result = {"error": f"Nieznane narzędzie: {name}"}
        else:
            result = TOOL_DISPATCH[name](args)

        memory.add_tool_result(name, result)

    # 3️⃣ Dociągnięcie finalnej odpowiedzi (po wynikach narzędzi)
    resp2 = client.responses.create(
        model=MODEL,
        input=memory.build_input(),
        temperature=temperature,
        tools=TOOLS,
    )
    return resp2.output_text


# ----------------------------
# GŁÓWNA PĘTLA CZATU
# ----------------------------
def main() -> None:
    # Ścieżka do pliku z historią (możesz zmienić nazwę)
    HISTORY_FILE = Path("chat_history.json")

    memory = ChatMemory(
        system_prompt=(
            "Jesteś pomocnym asystentem. Odpowiadasz PO POLSKU. "
            "Jesteś uprzejmy, zwięzły i precyzyjny. "
            "Gdy potrzebujesz danych – dopytujesz, ale nie nadużywasz pytań."
        ),
        history_file=HISTORY_FILE,
    )

    # ===================================================================
    #  🔥🔥🔥  POCZĄTKOWA HISTORIA (już wczytana przy starcie!)  🔥🔥🔥
    # ===================================================================
    # Jeśli plik nie istniał – dodajemy przykładową rozmowę.
    # Jeśli plik istnieje – historia zostanie wczytana automatycznie.
    if not HISTORY_FILE.exists():
        print("👋 Tworzę przykładową historię startową…\n")

        # 1️⃣ Użytkownik
        memory.add_user("Cześć! Jak mogę dzisiaj Ci pomóc?")
        # 2️⃣ Asystent
        memory.add_assistant(
            "Cześć! Mogę odpowiadać na pytania, podawać informacje, pomagać z kodem lub planowaniem. Co Cię dzisiaj interesuje?"
        )
        # 3️⃣ Użytkownik
        memory.add_user(
            "Potrzebuję prostego skryptu Python, który czyta plik CSV i liczy wiersze."
        )
    #         # 4️⃣ Asystent (z kodem)
    #         memory.add_assistant(
    #             """Oto gotowy skrypt:
    #
    # ```python
    # import csv
    #
    # with open('dane.csv', 'r', encoding='utf-8') as f:
    #     reader = csv.reader(f)
    #     rows = list(reader)
    #
    # print(f'Liczba wierszy (w tym nagłówek): {len(rows)}')
    # print(f'Liczba wierszy danych: {len(rows)-1}')
    # ```"""
    #         )
    #         # 5️⃣ Użytkownik
    #         memory.add_user("Działa! A jak mogę zapisać wynik do pliku `wynik.txt`?")
    #         # 6️⃣ Asystent
    #         memory.add_assistant(
    #             """Dodaj na końcu:
    #
    # ```python
    # with open('wynik.txt', 'w') as out:
    #     out.write(f'Liczba wierszy danych: {len(rows)-1}')
    # ```"""
    #         )
    #         # 7️⃣ Użytkownik (prośba o czas)
    #         memory.add_user("A teraz pokaż mi aktualny czas, proszę.")
    #         # 8️⃣ Asystent (wywołuje narzędzie `local_time`)
    #         #   (model sam wywoła narzędzie – my tylko symulujemy historię)
    #         memory.add_assistant(
    #             """Wywołuję narzędzie `local_time`…
    # 🔔 Proszę chwilę, sprawdzam aktualny czas…"""
    #         )
    #         # 9️⃣ Wynik narzędzia (symulowany)
    #         memory.add_tool_result(
    #             "local_time", {"epoch": 1717020000, "iso": "2024-06-01 12:00:00"}
    #         )
    #         # 🔟 Końcowa odpowiedź asystenta
    #         memory.add_assistant(
    #             "Aktualny czas to: **2024‑06‑01 12:00:00** (czas lokalny)."
    #         )

    # -------------------------------------------------
    # Jeśli historia jest długa – od razu streszczamy
    # -------------------------------------------------
    if memory.approx_char_count() > 6000:
        memory.summarize_history(keep_last_n=8)

    # -------------------------------------------------
    # Rozpoczęcie interaktywnego czatu
    # -------------------------------------------------
    print("\n📚 Historia rozmowy została wczytana! Wpisz `exit` aby zakończyć.\n")

    while True:
        user_text = input("Ty: ").strip()
        if not user_text:
            continue
        if user_text.lower() in ("exit", "quit"):
            break

        memory.add_user(user_text)

        # Streszczamy, gdy historia rośnie
        if memory.approx_char_count() > 6000:
            memory.summarize_history(keep_last_n=8)

        try:
            assistant_text = run_with_tools(memory, temperature=0.7)
        except Exception as e:
            assistant_text = f"❌ BŁĄD: {e}"

        memory.add_assistant(assistant_text)
        print(f"\nAsystent: {assistant_text}\n")


if __name__ == "__main__":
    main()
