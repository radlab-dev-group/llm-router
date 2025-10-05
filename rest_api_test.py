import os
import json
import requests
from typing import Any, Dict

# Base URL of the llm‑proxy REST API.
# Can be overridden by the environment variable LLM_PROXY_URL.
BASE_URL = os.getenv("LLM_PROXY_URL", "http://192.168.100.66:8080")


def _post(path: str, payload: Dict[str, Any]) -> requests.Response:
    """Helper to POST JSON payload to ``BASE_URL + path``."""
    url = f"{BASE_URL.rstrip('/')}{path}"
    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response


def _get(path: str) -> requests.Response:
    """Helper to GET ``BASE_URL + path``."""
    url = f"{BASE_URL.rstrip('/')}{path}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response


# ----------------------------------------------------------------------
ollama_payload = {
    "model": "",
    "stream": False,
    "messages": [
        {
            "role": "system",
            "content": "Jesteś pomocnym agentem na czacie.",
        },
        {
            "role": "user",
            "content": "Jak się masz?",
        },
    ],
}

generate_news_payload = {
    "model_name": "",
    "text": """
Behörden haben für die Nordseeküste eine Sturmflutwarnung herausgegeben. Auslöser ist das Sturmtief Detlef, das über Deutschland hinwegzieht und in weiten Teilen des Landes starken Wind und Regen mit sich bringt.

Die Flutwarnung des Bundesamtes für Seeschifffahrt und Hydrographie gilt für die Küste von Emden über Hamburg bis nach Sylt. Demnach wird das Hochwasser Emden voraussichtlich am Sonntagmittag erreichen. In Bremen und Hamburg könnte die Flut am Nachmittag eintreffen. Sie dürfte nach Angaben der Behörde voraussichtlich zwei Meter höher ausfallen als das mittlere Hochwasser.

Tanker trieb mit Motorschaden vor niederländischer Küste
Das Sturmwetter beeinträchtigt bereits die Seefahrt. Vor der niederländischen Nordseeküste trieb am Samstagabend ein mit Gasöl beladener Tanker vorübergehend manövrierunfähig im Meer. Die niederländische Küstenwache nannte Sturm als Ursache, wie mehrere Medien unter Berufung auf die Küstenwache berichten.

Das Schiff war demnach rund eineinhalb Meilen von einem Windpark entfernt aufgefunden worden. Es soll ein Problem mit dem Motor gegeben haben. Nach rund 40 Minuten konnte das Schiff den Berichten zufolge vor Anker gehen. Ein Rettungsschlepper liege vorsorglich in der Nähe des 145 Meter langen Schiffes. 

Am Abend rückten zwei Seenotrettungsboote und ein Hubschrauber zu dem Tanker aus. Die 21 Personen zählende Besatzung soll vorerst an Bord bleiben. Der unter der Fahne Singapurs fahrende Tanker Eva Schulte hatte nach Angaben der Website Vesselfinder den Hafen von Amsterdam am Nachmittag verlassen. Ein Ziel wird dort nicht genannt.

Sturmtief zog bereits über Frankreich und Großbritannien – mehrere Tote
Das Sturmtief Detlef, das international den Namen Amy trägt, hatte in den vergangenen Tagen über dem Atlantik Orkanstärke erreicht. In Nordfrankreich starben am Samstag infolge des Sturmtiefs mit Windgeschwindigkeiten von bis zu 131 Stundenkilometern zwei Menschen. Im Küstenort Étretat in der Normandie sei ein 48-Jähriger beim Baden im Atlantik gestorben, teilte die örtliche Feuerwehr mit. Wegen des schlechten Wetters sei keine Rettungsaktion möglich gewesen, die Leiche des Mannes sei bei Ebbe geborgen worden.

Extremwetter: Sturmtief Detlef zieht über Deutschland
Newsletter
Neu: Nur eine Frage
In diesem Newsletter weisen wir auf neue "Nur eine Frage"-Podcast-Folgen hin. Zudem erhalten Sie ergänzendes Material zu den Gesprächen – wie Videos oder Texte.

Registrieren
Im nordfranzösischen Département Aisne starb ein 25-jähriger Autofahrer, als ein großer Ast auf sein Fahrzeug stürzte. Seine Mitfahrerin sei schwer verletzt worden, teilten die örtlichen Behörden mit. In der gesamten Normandie fiel wegen des Sturms in Tausenden Haushalten der Strom aus, wie der Versorger Enedis mitteilte.

Zuvor hatte Amy bereits über den britischen Inseln gewütet. In Irland starb infolge des Unwetters am Freitag ein Mensch, dazu gab es örtliche Überschwemmungen, Stromausfälle und Flugstreichungen. Auch Schulen wurden vorsichtshalber geschlossen.    
""",
}


generate_questions_payload = {
    "model_name": "",
    "language": "en",
    "number_of_questions": 2,
    "texts": [
        generate_news_payload["text"][: int(len(generate_news_payload["text"]) / 2)],
        generate_news_payload["text"][
            int(len(generate_news_payload["text"]) / 2) - 1 :
        ],
    ],
}

conv_with_model_payload = {
    "model_name": "",
    "user_last_statement": "Jaka jest kategoria tekstu: Ala ma kota i psa.",
}

# ----------------------------------------------------------------------
# Endpoint tests
# ----------------------------------------------------------------------


class Ollama:
    @staticmethod
    def test_ollama_home_ep(_, debug: bool = False) -> None:
        """Health‑check endpoint ``/`` (GET)."""
        resp = _get("/")
        if debug:
            print("Ollama home:", resp.text)

    @staticmethod
    def test_ollama_tags_ep(_, debug: bool = False) -> None:
        """Tags endpoint ``/api/tags`` (GET)."""
        resp = _get("/api/tags")
        if debug:
            print("Ollama tags:", resp.json())

    @staticmethod
    def test_lmstudio_models(_, debug: bool = False) -> None:
        """LM‑Studio models list endpoint ``/v0/models`` (GET)."""
        resp = _get("/api/v0/models")
        if debug:
            print("LM Studio models:", resp.json())

    @staticmethod
    def test_ollama_chat_no_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint ``/api/chat`` (POST)."""
        payload = ollama_payload.copy()
        payload["stream"] = False
        payload["model"] = model_name
        resp = _post("/api/chat", payload)
        if debug:
            print("Api chat:", resp.json())

    @staticmethod
    def test_ollama_chat_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint ``/api/chat`` with streaming (POST, stream=True)."""
        payload = ollama_payload.copy()
        payload["stream"] = True
        payload["model"] = model_name
        url = f"{BASE_URL.rstrip('/')}/api/chat"
        with requests.post(url, json=payload, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            if debug:
                print("Streaming chat response:")
            for line in resp.iter_lines(decode_unicode=True):
                if line:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        cleaned = line.lstrip("data: ").strip()
                        try:
                            data = json.loads(cleaned)
                        except json.JSONDecodeError:
                            data = line  # Fallback to raw line

                    if "message" in data:
                        content_str = data["message"]["content"]
                        if debug:
                            print(content_str, end="", flush=True)
                    elif debug:
                        print(data)
        if debug:
            print("")


class VLLM:
    @staticmethod
    def test_chat_vllm_no_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint ``/api/chat`` (POST)."""
        payload = ollama_payload.copy()
        payload["stream"] = False
        payload["model"] = model_name
        resp = _post("/v1/chat/completions", payload)
        if debug:
            print("VLLM chat:", resp.json())

    @staticmethod
    def test_chat_vllm_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint with streaming from an external VLLM server."""
        payload = ollama_payload.copy()
        payload["stream"] = True
        payload["model"] = model_name
        url = f"{BASE_URL.rstrip('/')}/v1/chat/completions"

        with requests.post(url, json=payload, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            if debug:
                print("Streaming chat response:")
            for line in resp.iter_lines():
                if not line:
                    continue

                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")

                cleaned = line.lstrip("data: ").strip()
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError:
                    if "[DONE]" in line.strip().upper():
                        continue
                    print(f"Unparsable line: {line}")
                    continue

                if "choices" in data and data["choices"]:
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content and debug:
                        print(content, end="", flush=True)
                    if delta.get("finish_reason"):
                        break
                elif debug:
                    print(data)
        if debug:
            print("\n")


class Builtin:
    @staticmethod
    def parse_response(response):
        j_resp = response.json()
        if not j_resp.get("status", True):
            if "body" in j_resp:
                j_resp = j_resp["body"]
            raise Exception(json.dumps(j_resp))

    @staticmethod
    def test_builtin_ping(_, debug: bool = False) -> None:
        """Tags endpoint ``/api/ping`` (GET)."""
        resp = _get("/api/ping")
        if debug:
            print("Builtin ping:", resp.json())

    @staticmethod
    def test_builtin_con_with_model_no_stream(
        model_name: str, debug: bool = False
    ) -> None:
        """Chat completion endpoint ``/api/conversation_with_model`` (POST)."""
        payload = conv_with_model_payload.copy()
        payload["model_name"] = model_name
        resp = _post("/api/conversation_with_model", payload)
        if debug:
            print("Builtin conversation_with_model:", resp.json())
        Builtin.parse_response(resp)

    @staticmethod
    def test_builtin_ext_con_with_model_no_stream(
        model_name: str, debug: bool = False
    ) -> None:
        payload = conv_with_model_payload.copy()
        payload["model_name"] = model_name
        payload["system_prompt"] = "Odpowiadaj jak mistrz Yoda."
        resp = _post("/api/extended_conversation_with_model", payload)
        if debug:
            print("Builtin extended_conversation_with_model:", resp.json())
        Builtin.parse_response(resp)

    @staticmethod
    def test_builtin_generate_article_from_text(
        model_name: str, debug: bool = False
    ) -> None:
        """Chat completion endpoint ``/api/generate_article_from_text`` (POST)."""
        payload = generate_news_payload.copy()
        payload["model_name"] = model_name
        resp = _post("/api/generate_article_from_text", payload)
        if debug:
            print("Builtin generate_article_from_text:", resp.json())
        Builtin.parse_response(resp)

    @staticmethod
    def test_builtin_generate_questions(
        model_name: str, debug: bool = False
    ) -> None:
        """Chat completion endpoint ``/api/generate_questions`` (POST)."""
        payload = generate_questions_payload.copy()
        payload["model_name"] = model_name
        resp = _post("/api/generate_questions", payload)
        if debug:
            print("Builtin generate_questions:", resp.json())
        Builtin.parse_response(resp)


def run_all_tests() -> None:
    """Execute all endpoint tests sequentially."""
    models = {
        "ollama20": "gpt-oss:20b",
        "ollama120": "gpt-oss:120b",
        "external_model_name": "google/gemini-2.0-flash",
        "vllm_model": "google/gemma-3-12b-it",
    }

    test_functions = [
        # test_lmstudio_models <- not fully integrated,
        # [Ollama.test_ollama_home_ep, "ollama120", False],
        # [Ollama.test_ollama_tags_ep, "ollama120", False],
        # [Ollama.test_ollama_chat_no_stream, "ollama120", False],
        # [Ollama.test_ollama_chat_stream, "ollama120", False],
        # [VLLM.test_chat_vllm_no_stream, "vllm_model", False],
        # [VLLM.test_chat_vllm_stream, "vllm_model", False],
        # [Builtin.test_builtin_ping, "vllm_model", False],
        # [Builtin.test_builtin_con_with_model_no_stream, "vllm_model", False],
        # [Builtin.test_builtin_ext_con_with_model_no_stream, "vllm_model", False],
        # [Builtin.test_builtin_generate_article_from_text, "vllm_model", False],
        [Builtin.test_builtin_generate_questions, "vllm_model", True],
    ]
    for fn, model_name, debug in test_functions:
        try:
            print(f"Running {fn.__name__} ...")
            fn(models[model_name], debug)
        except Exception as e:
            print(f"❌ {fn.__name__} failed: {e}")
        else:
            print(f"✅ {fn.__name__} succeeded")
        print("-" * 40)


if __name__ == "__main__":
    run_all_tests()
