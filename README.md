# AI-Powered Agentic Software Engineering Platform

This platform connects repository understanding, AI-assisted engineering work,
verification, and human review into one traceable workflow.

## Run the backend locally

Prerequisites: Python 3.11+ and Docker with Docker Compose.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
docker compose up -d
cd backend
uvicorn app.main:app --reload
```

The health endpoint is available at `http://127.0.0.1:8000/api/v1/health` and
returns `{"status":"ok","version":"1.0.0"}`. The published API contract is
available at `http://127.0.0.1:8000/openapi.json`, with interactive docs at
`http://127.0.0.1:8000/docs`.

Do not commit `.env` or any real credentials. Use `.env.example` only as the
safe list of required configuration keys.
