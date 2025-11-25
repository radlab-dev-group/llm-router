# LLM Router Web

Web interface for managing LLM Router configurations and text anonymization.

## Overview

`llm_router_web` provides two Flask-based web applications:

1. **Config Manager** – Manage LLM Router model configurations with multi-user support
2. **Anonymizer** – Web UI for text anonymization and chat with anonymization

## Features

### Config Manager (`app_cfg_manager`)

- **User Management**: Admin panel, authentication, role-based access
- **Project Management**: Organize configurations into projects
- **Model Configuration**:
  - Create, edit, import/export configurations (JSON)
  - Manage models across families (Google, OpenAI, Qwen)
  - Configure providers (API hosts, tokens, weights, input sizes)
  - Version control with restore capability
- **Active Model Selection**: Choose which models to activate

### Anonymizer (`app_anonymizer`)

- **Text Anonymization**: Multiple algorithms (fast, GenAI, PrivMasker)
- **Chat Interface**: Interactive chat with optional anonymization
- **Model Selection**: Browse and select available LLM models
- **Real-time Processing**: Direct integration with LLM Router API

## Installation

```bash
pip install -r requirements.txt
```

### Requirements

- Flask
- Flask-SQLAlchemy
- Gunicorn

## Usage

### Config Manager

**Run with Gunicorn (recommended):**

```bash
./run-configs-manager.sh
```

**Run directly:**

```bash
python app_cfg_manager.py
```

**Configuration (environment variables):**

- `LLM_ROUTER_WEB_CFG_HOST` – Bind address (default: `0.0.0.0`)
- `LLM_ROUTER_WEB_CFG_PORT` – Port (default: `8081`)
- `LLM_ROUTER_WEB_CFG_DEBUG` – Debug mode (default: `true`)

**First-time setup:**

1. Access the web interface
2. Create initial admin account via setup page
3. Log in and start managing configurations

**Default URL:** http://localhost:8081

### Anonymizer

**Run with Gunicorn (recommended):**

```bash
./run-anonymizer.sh
```

**Run directly:**

```bash
python app_anonymizer.py
```

**Configuration (environment variables):**

- `LLM_ROUTER_WEB_ANO_HOST` – Bind address (default: `0.0.0.0`)
- `LLM_ROUTER_WEB_ANO_PORT` – Port (default: `8082`)
- `LLM_ROUTER_WEB_ANO_DEBUG` – Debug mode (default: `true`)
- `LLM_ROUTER_HOST` – LLM Router API endpoint (default: `http://192.168.100.65:8080`)
- `LLM_ROUTER_GENAI_MODEL_ANONYMISATION` – Model for GenAI anonymization (default: `gtp-oss:120b`)

**Default URL:** http://localhost:8082/anonymize

## API Endpoints

### Config Manager

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Configuration list (home) |
| `/login` | GET/POST | User login |
| `/logout` | GET | User logout |
| `/setup` | GET/POST | Initial admin setup |
| `/admin/users` | GET/POST | User management (admin) |
| `/projects` | GET/POST | Project management |
| `/configs` | GET | List configurations |
| `/configs/new` | GET/POST | Create configuration |
| `/configs/import` | GET/POST | Import JSON configuration |
| `/configs/<id>` | GET | View configuration |
| `/configs/<id>/edit` | GET/POST | Edit configuration |
| `/configs/<id>/export` | GET | Export configuration (JSON) |
| `/configs/<id>/activate` | POST | Activate configuration |
| `/configs/<id>/delete` | POST | Delete configuration |
| `/configs/<id>/models/add` | POST | Add model |
| `/models/<id>/delete` | POST | Delete model |
| `/models/<id>/providers/add` | POST | Add provider |
| `/providers/<id>/update` | POST | Update provider |
| `/providers/<id>/delete` | POST | Delete provider |

### Anonymizer

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/anonymize/` | GET | Anonymization form |
| `/anonymize/` | POST | Process text anonymization |
| `/anonymize/chat` | GET | Chat interface |
| `/anonymize/chat/message` | POST | Send chat message |
| `/anonymize/models` | GET | List available models |

## Project Structure

```
llm_router_web/
├── app_anonymizer.py          # Anonymizer Flask app entry point
├── app_cfg_manager.py         # Config Manager Flask app entry point
├── run-anonymizer.sh          # Anonymizer startup script (gunicorn)
├── run-configs-manager.sh     # Config Manager startup script (gunicorn)
├── requirements.txt           # Python dependencies
├── instance/
│   └── configs.db             # SQLite database (auto-created)
└── web/
    ├── anonymizer/            # Anonymizer blueprint & routes
    ├── configs_manager/       # Config Manager blueprint, models & routes
    ├── templates/             # HTML templates
    └── static/                # Static assets (CSS, JS)
```

## Database

Config Manager uses SQLite with SQLAlchemy ORM:

- **Models**: `User`, `Project`, `Config`, `Model`, `Provider`, `ActiveModel`, `ConfigVersion`
- **Location**: `instance/configs.db` (auto-created on first run)
- **Version Control**: Automatic configuration snapshots on changes

## Security

- Password hashing via Werkzeug
- Session-based authentication
- Role-based access control (admin/user)
- User account blocking capability
- Per-user project isolation

## Notes

- Config Manager requires initial admin setup on first run
- Anonymizer requires a running LLM Router instance
- Both apps run independently on different ports
- Configurations are stored in SQLite database (Config Manager only)
- All configuration changes are versioned and can be restored
