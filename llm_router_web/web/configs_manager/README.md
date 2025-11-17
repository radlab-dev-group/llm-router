# llm_router_web.configs_manager

**llm_router_web: configs manager** is the web interface component of
the **[llm-router](https://github.com/radlab-dev-group/llm-router)
** project.  
It provides a Flask‑based UI for managing LLM model configurations, users, and version history.

## Features

- **User Management** – Admins can create, edit, block/unblock users and assign roles (`admin` / `user`).
- **Configuration CRUD** – Create, import, edit, view, export, activate and delete model configurations.
- **Model & Provider Management** – Add/remove models, manage multiple providers per model, reorder providers via
  drag‑and‑drop.
- **Versioning** – Automatic snapshot of each change; view history and restore previous versions.
- **Theme Switching** – Light / dark UI themes toggled client‑side.
- **Responsive UI** – Built with HTML, CSS, HTMX and Alpine.js for a smooth, single‑page‑like experience.

---

## Installation

The project uses **Python 3.10.6** and **virtualenv**.

```shell script
# Clone the repository
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router/llm_router_web

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

> **Note:** The only required packages are listed in `requirements.txt` (`flask` and `flask_sqlalchemy`). All other
> libraries are part of the broader `llm-router` repository.

---

## Running the Application

``` shell script
# Start the Flask development server
python app.py
```

The UI will be available at `http://localhost:8081`.  
The first run will redirect you to a **setup** page where you must create an initial admin user.

### Running with **gunicorn** (recommended for production)

The project now includes a small launch script that reads the host, port and debug
mode from environment variables prefixed with `LLM_ROUTER_WEB_`.

``` bash
LLM_ROUTER_WEB_CFG_HOST=0.0.0.0 \
LLM_ROUTER_WEB_CFG_PORT=8081 \
LLM_ROUTER_WEB_CFG_DEBUG=true \
./run-llm-router-web.sh
```

* `LLM_ROUTER_WEB_CFG_HOST` – address to bind (default: `0.0.0.0`).
* `LLM_ROUTER_WEB_CFG_PORT` – numeric port (default: `8081`).
* `LLM_ROUTER_WEB_CFG_DEBUG` – any truthy value (`true`, `1`, `yes`, `on`) enables Flask debug mode
  (default: `true`).

The script will automatically start the application with four gunicorn workers.
Adjust the number of workers or other gunicorn options inside `run.sh` as needed.

### Additional Flask environment variables

| Variable           | Description                                   | Default                |
|--------------------|-----------------------------------------------|------------------------|
| `FLASK_SECRET_KEY` | Secret key for session signing                | `change-me-local`      |
| `DATABASE_URL`     | SQLAlchemy database URL (SQLite by default)   | `sqlite:///configs.db` |
| `FLASK_ENV`        | Set to `production` for HTTPS scheme handling | –                      |

---

## Configuration

All Flask configuration is performed in `web/__init__.py` via `create_app()`.  
Key settings:

- `SQLALCHEMY_DATABASE_URI` – points to the SQLite DB (`configs.db`) unless overridden.
- `SQLALCHEMY_TRACK_MODIFICATIONS` – disabled for performance.
- `PREFERRED_URL_SCHEME` – set to `https` when `FLASK_ENV=production`.

The database schema is automatically created on first launch. If the `order` column is missing from the `provider`
table (e.g., after a schema change), the helper `_ensure_provider_order_column()` adds it on startup.

---

## Endpoints Overview

| URL                                    | Methods   | Description                                            |
|----------------------------------------|-----------|--------------------------------------------------------|
| `/setup`                               | GET, POST | One‑time admin creation (first run).                   |
| `/login`                               | GET, POST | User authentication.                                   |
| `/logout`                              | GET       | End session.                                           |
| `/admin/users`                         | GET, POST | List users / add new user (admin only).                |
| `/admin/users/<id>/edit`               | POST      | Edit role or password (admin only).                    |
| `/admin/users/<id>/toggle_block`       | POST      | Block / unblock a user (admin only).                   |
| `/`                                    | GET       | Dashboard – list of user’s configs.                    |
| `/configs`                             | GET       | Same as dashboard (alternative view).                  |
| `/configs/new`                         | GET, POST | Create a new empty configuration.                      |
| `/configs/import`                      | GET, POST | Import configuration from JSON file or text.           |
| `/configs/<id>`                        | GET       | Preview configuration (JSON view).                     |
| `/configs/<id>/export`                 | GET       | Download configuration as `models-config.json`.        |
| `/configs/<id>/edit`                   | GET, POST | Edit active models, rename config, add providers, etc. |
| `/configs/<id>/models/add`             | POST      | Add a new model to a configuration.                    |
| `/models/<id>/delete`                  | POST      | Delete a model.                                        |
| `/models/<id>/providers/add`           | POST      | Add a provider (JSON payload).                         |
| `/models/<id>/providers/reorder`       | POST      | Reorder providers (drag‑and‑drop).                     |
| `/providers/<id>/update`               | POST      | Update provider fields (JSON payload).                 |
| `/providers/<id>/delete`               | POST      | Delete a provider.                                     |
| `/configs/<id>/activate`               | POST      | Mark a configuration as the default for the user.      |
| `/configs/<id>/delete`                 | POST      | Delete a configuration.                                |
| `/configs/<id>/versions`               | GET       | List version history (JSON).                           |
| `/configs/<id>/versions/<ver>/restore` | POST      | Restore a previous version.                            |
| `/check_host`                          | POST      | Verify reachability of an API host (used by the UI).   |

All routes are protected by session‑based authentication. Admin‑only routes require the `admin` role.

---

## Development

### Code structure

```
llm_router_web/
├─ web/
│  ├─ static/        # CSS files (dark/light themes)
│  ├─ templates/    # Jinja2 HTML templates
│  ├─ __init__.py   # Flask app factory
│  ├─ constants.py
│  ├─ models.py     # SQLAlchemy models
│  ├─ routes.py     # All view functions & API endpoints
│  └─ utils.py      # Helper utilities (JSON export, snapshots, DB migration)
├─ app.py            # Entry point (creates the Flask app)
└─ requirements.txt
```

### Adding new features

1. **Routes** – Add view functions to `web/configs_manager/routes.py` and register them on the `bp` blueprint.
2. **Templates** – Place new Jinja2 files in `web/configs_manager/templates/`.
3. **Static assets** – Add CSS/JS files to `web/static/` and reference them via `url_for('static', filename='…')`.
4. **Database changes** – Extend `web/models.py` and, if needed, modify `_ensure_provider_order_column()` to handle
   migrations for SQLite.

---

## License

`llm_router_web.configs_manager` is part of the **llm-router** project and is released under the same license
as the parent repository. See the repository’s `LICENSE` file for details.
