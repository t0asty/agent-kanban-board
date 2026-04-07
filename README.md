# Agentic Kanban

Agentic Kanban is an AI-assisted project planning board.  
It turns a plain-language project prompt into structured kanban tasks, stores them in a schema-driven backend, and exposes MCP tools so external agents can manage the board programmatically.

## What This Project Includes

- `agentic-kanban/frontend`: Next.js app for generating tasks and managing the board with drag and drop.
- `agentic-kanban/backend`: FastAPI service with card CRUD APIs, schema reload support, and AI generation endpoint.
- `agentic-kanban/mcp`: FastMCP server exposing kanban operations to agent clients.
- `agentic-kanban/card.schema.json`: Source-of-truth schema for card validation and dynamic model generation.

## Core Features

- AI-powered task generation from natural language prompts
- Kanban workflow with statuses: `research`, `planned`, `in-progress`, `blocked`, `done`
- Drag-and-drop card movement with optimistic updates
- Dynamic backend schema loading and runtime schema reload
- ChromaDB-backed persistent storage
- MCP tool interface for agent-driven card operations

## Architecture

1. User submits a project prompt in the frontend.
2. Frontend calls backend `POST /api/generate-cards`.
3. Backend agent service generates cards (Gemini + fallback logic).
4. Cards are validated against `card.schema.json` and stored in ChromaDB.
5. Frontend loads cards via API and renders the kanban board.
6. MCP server can query/update the same backend through standardized tools.

## Prerequisites

- Node.js 18+ (Node.js 20 recommended)
- `pnpm` (recommended; `npm` can also work)
- Python 3.10+
- A Google Gemini API key (`GOOGLE_API_KEY`) for AI card generation

## Quick Start

### 1) Clone and enter project

```bash
git clone <your-repo-url>
cd agent-kanban-board/agentic-kanban
```

### 2) Configure environment

Create environment files from examples:

```bash
cp .env.example .env
cp mcp/.env.example mcp/.env
```

Set at least:

- `GOOGLE_API_KEY=...`
- `KANBAN_BACKEND_BASE_URL=http://localhost:8000`

### 3) Start backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Backend runs at `http://localhost:8000` with docs at:

- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

### 4) Start frontend

In a new terminal:

```bash
cd agentic-kanban/frontend
pnpm install
pnpm dev
```

Frontend runs at `http://localhost:3000`.

### 5) (Optional) Start MCP server

In another terminal:

```bash
cd agentic-kanban/mcp
pip install -r fastmcp_requirements.txt
python fastmcp_server.py
```

## Main API Endpoints

- `GET /` - Health check
- `GET /api/cards` - List cards
- `POST /api/cards` - Create multiple cards
- `PUT /api/cards/{card_id}` - Update card
- `GET /api/cards/{card_id}` - Get single card
- `DELETE /api/cards/{card_id}` - Delete card
- `DELETE /api/cards` - Delete all cards
- `POST /api/generate-cards` - Generate cards from prompt
- `GET /api/schema` - Current schema metadata
- `POST /api/schema/reload` - Reload models from schema

## MCP Tools

The FastMCP server exposes tools including:

- `create_kanban_cards`
- `get_all_kanban_cards`
- `search_kanban_cards`
- `update_kanban_card`
- `get_kanban_schema`
- `get_kanban_stats`

## Development Notes

- Card shape and allowed statuses are defined in `card.schema.json`.
- Backend dynamically builds validation models from the schema.
- Use `POST /api/schema/reload` after schema updates to regenerate models at runtime.
- ChromaDB data persists in the backend storage path (`./chroma_db` by default).

## Project Structure

```text
agentic-kanban/
├── card.schema.json
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── schema_loader.py
│   ├── database.py
│   ├── agent_service.py
│   ├── run.py
│   └── requirements.txt
├── frontend/
│   ├── app/
│   ├── components/
│   ├── hooks/
│   └── package.json
└── mcp/
    ├── fastmcp_server.py
    ├── fastmcp_requirements.txt
    └── .env.example
```

## Troubleshooting

- If AI generation fails, verify `GOOGLE_API_KEY` in `.env`.
- If frontend cannot load data, ensure backend is running on `http://localhost:8000`.
- If schema changes are ignored, call `POST /api/schema/reload`.

## License

This repository is licensed under the terms in `LICENSE`.
