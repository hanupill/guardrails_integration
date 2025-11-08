# Guardrails Integration API

FastAPI REST API for running Guardrails validations (local guardrails + Guardrails Hub). Includes setup for Python 3.13, dependencies, Hub validator installation, and example requests.

## Prerequisites

- Python `3.13` installed and on PATH
- PowerShell with `ExecutionPolicy` that allows running local scripts
- Internet access to install Hub validators

Verify Python 3.13 is available:
```
python --version
``

## Quickstart

1) Create and activate a virtual environment:
```
python -m venv venv
venv\Scripts\Activate
```

2) Install dependencies (choose one):

- Via `pyproject.toml`:
```
python -m pip install .
```

- Via `requirements.txt`:
```
python -m pip install -r requirements.txt
```



3) Install Guardrails Hub validators (choose one option below):
- Option A: Use the project’s inline installer (no manifest needed)
- Option B: Use your external installer with the `hub_validators.txt` manifest

### Option A: Project Inline Installer

Runs a predefined list of validators via `python -m guardrails` and falls back to `guardrails` CLI if needed.

To run the inline installer:
```
python -m guardrails
``

option 2 run the external installer:
in one command to create the virtual environment and install the validators:
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -BindHost 127.0.0.1 -Port 8080

-NoStart to skip starting the server.
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoStart

-SkipValidators to skip installing Hub validators.
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -SkipValidators -BindHost 127.0.0.1 -Port 8080

python -m uvicorn main:app --host 127.0.0.1 --port 8080
