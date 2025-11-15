# llm_router_web.anonymizer

**llm_router_web: anonymizer** is a lightweight Flask web interface that provides a simple UI for text anonymization.  
It forwards the supplied text to an external LLM‑router anonymization service (`/api/fast_text_mask`)
and displays the masked result, with on‑the‑fly highlighting of detected tags (`{{…}}`).

**llm_router_web.anonymizer** is the web interface component of the
[llm-router](https://github.com/radlab-dev-group/llm-router) library.

## Features

- **Web form** – Paste text and trigger anonymization with a single click.
- **HTMX‑powered UI** – Asynchronous request/response without a full page reload.
- **Result highlighting** – Detected placeholders are wrapped in a colored span for easy spotting.
- **Spinner indicator** – Visual feedback while the request is in progress.
- **Error handling** – Returns clear messages for missing input or communication problems.
- **Configurable backend** – Target anonymization service URL is supplied via `LLM_ROUTER_HOST` environment variable.

## Installation

The project follows the same conventions as the rest of the **llm‑router** repository and uses
**Python 3.10.6** with **virtualenv**.

```shell script
# Clone the repository (if not already done)
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router/llm_router_web

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies (the base requirements already contain Flask)
pip install -r requirements.txt
```

> **Note:** The only additional packages required for the anonymizer are already listed in `requirements.txt` (`flask`,
`requests`, `htmx`, `alpine.js` are loaded from CDN).

## Running the Application

### Development server

```shell script
# Start the Flask development server for the anonymizer module
python -m web.anonymizer
```

The UI will be reachable at `http://localhost:5000/anonymize`.  
The root path (`/`) redirects to the form page.

### Production (Gunicorn)

A small launch script is included in the main repository. Example:

```shell script
LLM_ROUTER_HOST=http://localhost:8000 \
FLASK_SECRET_KEY=super-secret \
gunicorn -w 4 -b 0.0.0.0:8082 "web.anonymizer:create_anonymize_app()"
```

- `LLM_ROUTER_HOST` – base URL of the external anonymization service (default: `http://localhost:8000`).
- `FLASK_SECRET_KEY` – secret key for session signing (default: `change-me-anonymizer`).

Adjust the number of workers (`-w`) as needed.

## Configuration

All configuration is performed via environment variables:

| Variable           | Description                               | Default                 |
|--------------------|-------------------------------------------|-------------------------|
| `FLASK_SECRET_KEY` | Secret key for Flask session signing      | `change-me-anonymizer`  |
| `LLM_ROUTER_HOST`  | URL of the external anonymization service | `http://localhost:8000` |

The variables are read in `web/anonymizer/__init__.py` when `create_anonymize_app()` is called.

## Endpoints Overview

| URL              | Methods | Description                                                                                                                        |
|------------------|---------|------------------------------------------------------------------------------------------------------------------------------------|
| `/` (root)       | GET     | Redirects to `/anonymize/`.                                                                                                        |
| `/anonymize/`    | GET     | Renders the anonymization form (`anonymize.html`).                                                                                 |
| `/anonymize/`    | POST    | Accepts `text` form field, forwards it to the external service, and returns the rendered result (`anonymize_result_partial.html`). |
| *Error handlers* | –       | Returns JSON payloads for 400, 404, and 500 errors.                                                                                |

### Request flow (POST `/anonymize/`)

1. The form posts the `text` field via HTMX.
2. The server builds the target URL: `"{LLM_ROUTER_HOST.rstrip('/')}/api/fast_text_mask"`.
3. It sends a JSON payload `{ "text": "<raw text>" }` to the external service.
4. On success the response text (or the `text` field from JSON) is injected back into the page, where JavaScript
   highlights any `{{…}}` tags.

## Development

### Project layout

```
web/
└─ anonymizer/
   ├─ templates/
   │   ├─ anonymize.html                # Main form page (HTMX enabled)
   │   ├─ anonymize_result_partial.html # Partial used to render the result
   │   └─ base_anonymizer.html          # Base layout shared by both templates
   ├─ __init__.py                       # Flask app factory (create_anonymize_app)
   └─ routes.py                         # Blueprint with view functions
```

### Adding new features

1. **New routes** – Define them in `routes.py` and register on `anonymize_bp`.
2. **Templates** – Place additional Jinja2 files in `templates/` and extend `base_anonymizer.html`.
3. **Static assets** – Add CSS/JS to the main `static/` directory; they are automatically served because the Flask app
   points to the parent static folder.
4. **Configuration** – Extend `create_anonymize_app()` to read extra environment variables as needed.

## License

`llm_router_web.anonymizer` is part of the **llm-router** project and is released under the same license
as the parent repository. See the repository’s `LICENSE` file for details.
