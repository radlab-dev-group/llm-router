from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
# Prosta pamięć rozmowy + streszczanie
# ----------------------------
@dataclass
class ChatMemory:
    """
    Trzyma historię jako listę elementów input (Responses API):
    [{role: "system"|"user"|"assistant", content: [...] }, ...]
    plus opcjonalne streszczenie, gdy robi się zbyt długo.
    """

    system_prompt: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    summary: Optional[str] = None

    def __post_init__(self) -> None:
        self.items.append(
            {
                "role": "system",
                "content": [{"type": "text", "text": self.system_prompt}],
            }
        )

    def add_user(self, text: str) -> None:
        self.items.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            }
        )

    def add_assistant(self, text: str) -> None:
        self.items.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            }
        )

    def build_input(self) -> List[Dict[str, Any]]:
        """
        Jeśli mamy streszczenie, wstrzykujemy je jako dodatkowy system note.
        """
        if self.summary:
            return [
                self.items[0],  # oryginalny system
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Streszczenie dotychczasowej rozmowy "
                            f"(pamięć):\n{self.summary}",
                        }
                    ],
                },
                *self.items[1:],
            ]
        return self.items

    def approx_char_count(self) -> int:
        total = 0
        for msg in self.items:
            for c in msg.get("content", []):
                if c.get("type") == "text":
                    total += len(c.get("text", ""))
        if self.summary:
            total += len(self.summary)
        return total


def summarize_history(memory: ChatMemory, keep_last_n: int = 6) -> None:
    """
    Streszcza starszą część historii, zostawia ostatnie N wiadomości bez zmian.
    """
    if len(memory.items) <= 1 + keep_last_n:
        return  # za krótko, nie ma co streszczać

    # wydzielamy część do streszczenia (bez system promptu)
    head = memory.items[1:-keep_last_n]
    tail = memory.items[-keep_last_n:]

    summarizer_input = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "Jesteś narzędziem do streszczania rozmów. "
                    "Pisz krótko i konkretnie po polsku.",
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Streść poniższą historię w 6–10 punktach, zachowując "
                    "kluczowe ustalenia i preferencje użytkownika.",
                }
            ],
        },
        *head,
    ]

    resp = client.responses.create(
        model=MODEL,
        input=summarizer_input,
        temperature=0.2,
    )

    memory.summary = resp.output_text.strip()
    # podmieniamy historię: system + ogon
    memory.items = [memory.items[0], *tail]


# ----------------------------
# Opcjonalne narzędzie (function calling)
# ----------------------------
def local_time_tool(_: Dict[str, Any]) -> Dict[str, Any]:
    """
    Przykładowe narzędzie: zwraca lokalny czas (UTC epoch + czytelny zapis).
    """
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
            "description": "Zwraca bieżący czas na maszynie, na której działa Python.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }
]

TOOL_DISPATCH = {
    "local_time": local_time_tool,
}


def run_with_tools(memory: ChatMemory, temperature: float = 0.7) -> str:
    """
    Wysyła rozmowę do modelu. Jeśli model poprosi o wywołanie narzędzia,
    wykonuje je w Pythonie i dociąga finalną odpowiedź.
    """
    # 1) Pierwsze wywołanie
    resp = client.responses.create(
        model=MODEL,
        input=memory.build_input(),
        temperature=temperature,
        tools=TOOLS,  # jeśli Twoje środowisko nie wspiera tools, usuń tę linię
    )

    # Jeśli backend wspiera tool calling, odpowiedź może zawierać prośby o narzędzie.
    # W różnych implementacjach struktura bywa różna; poniżej ostrożne podejście.
    # Najczęściej da się polegać na output_text, ale narzędzia wymagają dogrania.
    tool_calls = []
    for item in getattr(resp, "output", []) or []:
        # próbujemy znaleźć elementy typu "tool_call" / "function_call"
        if isinstance(item, dict) and item.get("type") in (
            "tool_call",
            "function_call",
        ):
            tool_calls.append(item)

    # Jeśli nie ma tool calls, kończymy
    if not tool_calls:
        return resp.output_text

    # 2) Obsługa narzędzi
    for call in tool_calls:
        # Normalizacja pól (różne proxy mogą to nazywać inaczej)
        name = None
        arguments = {}
        if call.get("type") == "tool_call":
            fn = call.get("function", {}) or {}
            name = fn.get("name")
            arg_str = fn.get("arguments", "{}")
            try:
                arguments = (
                    json.loads(arg_str)
                    if isinstance(arg_str, str)
                    else (arg_str or {})
                )
            except json.JSONDecodeError:
                arguments = {}
        else:
            # fallback
            name = call.get("name") or call.get("function", {}).get("name")

        if not name or name not in TOOL_DISPATCH:
            tool_result = {"error": f"Nieznane narzędzie: {name}"}
        else:
            tool_result = TOOL_DISPATCH[name](arguments)

        # Dopinamy wynik narzędzia do historii jako wiadomość typu tool
        memory.items.append(
            {
                "role": "tool",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(tool_result, ensure_ascii=False),
                    }
                ],
            }
        )

    # 3) Dociągnięcie finalnej odpowiedzi po wynikach narzędzi
    resp2 = client.responses.create(
        model=MODEL,
        input=memory.build_input(),
        temperature=temperature,
        tools=TOOLS,
    )
    return resp2.output_text


# ----------------------------
# Aplikacja: pętla czatu z historią + streszczaniem
# ----------------------------
def main() -> None:
    memory = ChatMemory(
        system_prompt=(
            "Jesteś pomocnym asystentem. Odpowiadasz po polsku. "
            "Gdy brakuje danych, dopytujesz, ale zwięźle. "
            "Jeśli użytkownik poprosi o kod, podajesz go w Pythonie."
        )
    )

    print("Czat: wpisz 'exit' aby zakończyć.\n")

    while True:
        user_text = input("Ty: ").strip()
        if not user_text:
            continue
        if user_text.lower() in ("exit", "quit"):
            break

        memory.add_user(user_text)

        # Gdy historia rośnie, streszczamy (prosty próg po znakach)
        if memory.approx_char_count() > 6000:
            summarize_history(memory, keep_last_n=8)

        # Odpowiedź (z narzędziami; możesz zamienić na prosty create bez tools)
        try:
            assistant_text = run_with_tools(memory, temperature=0.7)
        except Exception as e:
            assistant_text = f"(Błąd wywołania API: {e})"

        memory.add_assistant(assistant_text)
        print(f"\nAsystent: {assistant_text}\n")


if __name__ == "__main__":
    main()
