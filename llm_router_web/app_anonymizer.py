# Pythonind
import os
from web.anonymize import create_anonymize_app

# Konfiguracja – dowolny port, np. 8082
HOST = os.getenv("LLM_ROUTER_WEB_ANO_HOST", "0.0.0.0")
PORT = int(os.getenv("LLM_ROUTER_WEB_ANO_PORT", "8082"))
DEBUG = os.getenv("LLM_ROUTER_WEB_ANO_DEBUG", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

app = create_anonymize_app()

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
