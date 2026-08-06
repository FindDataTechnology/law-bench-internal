# Contract Review Agent

Multi-model contract review system with human-in-the-loop checkpoints, built on LangGraph + CopilotKit.

## Overview

The Contract Review Agent generates legal contracts, sends them to 3 parallel AI reviewers (each with a different lens), synthesizes their suggestions, and guides humans through interactive checkpoints to refine the final output.

### Key Features

- **3 Parallel Reviewers**: Legal accuracy, commercial fairness, and completeness checks
- **3 Human Checkpoints**: 
  - CP1: Triage reviewer suggestions (accept/reject)
  - CP2: Fill contract slots via interactive quiz
  - CP3: Final approval before export
- **Dual Evaluation**: Rubric-based criteria + DeepEval metrics (hallucination, faithfulness, slot relevance)
- **Full Observability**: Per-node timing, model call tracking, token usage, cost estimation
- **Modern Frontend**: CopilotKit chat interface with real-time state panel

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js + CopilotKit)          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Chat Panel  │  │ State Panel  │  │ Checkpoint Forms │  │
│  │              │  │              │  │                  │  │
│  │ • Messages   │  │ • Progress   │  │ • Review Triage  │  │
│  │ • Streaming  │  │ • Metrics    │  │ • Quiz Form      │  │
│  │              │  │ • Reviews    │  │ • Approval       │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↕ AG-UI Protocol
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI + LangGraph)            │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              LangGraph StateGraph                     │  │
│  │                                                       │  │
│  │  START → generate_v1 → review_panel → synthesize     │  │
│  │        → 🚦 CP1 (triage) → generate_quiz             │  │
│  │        → 🚦 CP2 (quiz) → generate_v2                 │  │
│  │        → evaluate → 🚦 CP3 (approval) → export       │  │
│  │        → metrics → END                                │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Checkpoint  │  │   Metrics    │  │    Database      │  │
│  │   Manager    │  │   Tracker    │  │                  │  │
│  │              │  │              │  │ • agent_runs     │  │
│  │ • interrupt  │  │ • timing     │  │ • eval_runs      │  │
│  │ • resume     │  │ • tokens     │  │ • pipeline_runs  │  │
│  │ • state      │  │ • cost       │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 14+
- OpenAI-compatible API endpoint (e.g., Linjie relay)

## Setup

### 1. Clone and Install Dependencies

```bash
cd /Users/chengsishi/law-template

# Backend dependencies (already in shared venv)
# No additional installation needed

# Frontend dependencies
cd contract-review-agent/frontend
npm install
```

### 2. Configure Environment

Copy the example environment file:

```bash
cp contract-review-agent/.env.example contract-review-agent/.env
```

Edit `.env` and configure:

```bash
# Reviewer Models (3 parallel reviewers)
REVIEWER_1_MODEL=openai/kimi-k3
REVIEWER_1_LENS=legal_accuracy
REVIEWER_1_NAME=Legal Reviewer

REVIEWER_2_MODEL=openai/qwen-3.7-plus
REVIEWER_2_LENS=commercial_fairness
REVIEWER_2_NAME=Commercial Reviewer

REVIEWER_3_MODEL=openai/glm-5.2
REVIEWER_3_LENS=completeness
REVIEWER_3_NAME=Completeness Reviewer

# Quiz Generation Model
QUIZ_MODEL=openai/glm-5.2

# OpenAI-compatible API
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://api.example.com/v1

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/law_bench

# Server
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:3000

# CopilotKit
COPILOTKIT_API_KEY=your-copilotkit-key
NEXT_PUBLIC_COPILOTKIT_URL=http://localhost:8000/api/copilotkit
```

### 3. Initialize Database

Apply the agent_runs schema:

```bash
cd /Users/chengsishi/law-template/contract-review-agent
python db/apply_migration.py
```

This creates the `agent_runs` table in your PostgreSQL database.

### 4. Start the Backend

```bash
cd /Users/chengsishi/law-template/contract-review-agent
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will:
- Apply database migrations on startup
- Initialize the LangGraph checkpointer
- Start the FastAPI server with CopilotKit AG-UI endpoint

Verify the backend is running:

```bash
curl http://localhost:8000/api/health
# Should return: {"status": "healthy"}
```

### 5. Start the Frontend

```bash
cd /Users/chengsishi/law-template/contract-review-agent/frontend
npm run dev
```

The frontend will start at `http://localhost:3000`.

## Usage

### 1. Open the Web Interface

Navigate to `http://localhost:3000` in your browser.

You'll see:
- **Left**: Chat interface for interacting with the agent
- **Right**: State panel showing progress, metrics, and reviews

### 2. Start a Contract Review

In the chat, type:

```
生成一份农产品买卖合同
```

The agent will:
1. Generate the initial contract draft (generate_v1)
2. Send it to 3 parallel reviewers
3. Show real-time progress as each reviewer completes

### 3. Checkpoint 1: Triage Reviews

When the review panel completes, you'll see a **Review Triage** form.

For each suggestion:
- ✅ Check the box to accept
- ☐ Leave unchecked to reject

Click **Submit Selections** to continue.

### 4. Checkpoint 2: Fill Quiz

After triage, the agent generates a quiz with questions for each contract slot.

Fill in all required fields:
- 买方名称 (Buyer name)
- 卖方名称 (Seller name)
- 标的物 (Subject matter)
- 数量 (Quantity)
- etc.

Click **Submit All Answers** when complete.

### 5. Checkpoint 3: Final Approval

The agent generates the final contract with your slot values and shows:
- Evaluation results (rubric criteria + DeepEval metrics)
- Full contract preview

Choose:
- **✓ 确认通过** — Approve and export
- **✎ 需要修改** — Request changes (returns to chat)

### 6. Export

After approval, the agent exports the contract as DOCX/PDF and provides download links.

## API Endpoints

### Agent Metrics

```bash
# List recent agent runs
curl http://localhost:8000/api/agent-runs

# Get specific run
curl http://localhost:8000/api/agent-runs/{run_id}

# Store new run (used internally by the agent)
curl -X POST http://localhost:8000/api/agent-runs \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "test-123",
    "contract_type": "sale",
    "tags": {"scenario": "农产品买卖"},
    "node_timings": {"generate_v1": 2.3},
    "model_calls": [{"model": "kimi-k3", "tokens": 100, "cost": 0.01}],
    "total_slots": 5,
    "human_filled_slots": 5
  }'
```

### Health Check

```bash
curl http://localhost:8000/api/health
```

## Configuration

### Reviewer Models

Each reviewer can use a different model and lens:

| Lens | Focus |
|------|-------|
| `legal_accuracy` | Missing legal requirements, enforceability |
| `commercial_fairness` | Balanced risk allocation, market terms |
| `completeness` | All sections present, slots defined |

### Quiz Model

The `QUIZ_MODEL` generates natural-language questions for each slot. Choose a model good at instruction-following.

### Evaluation

The agent uses dual evaluation:
- **Rubric eval**: Existing law-bench criteria (PASS/FAIL)
- **DeepEval metrics**: Hallucination, faithfulness, slot relevance

## Testing

Run the integration tests:

```bash
cd /Users/chengsishi/law-template
pytest contract-review-agent/tests/test_integration.py -v
```

Tests cover:
- Review panel parallel execution
- Quiz generation (all slots extracted)
- Human checkpoint interrupt/resume
- Dual evaluation (rubric + DeepEval)
- Agent metrics persistence
- Error handling (missing env vars, LLM failures)

## Troubleshooting

### Backend won't start

**Error**: `DATABASE_URL is not set`
- **Solution**: Copy `.env.example` to `.env` and fill in database credentials

**Error**: `REVIEWER_1_MODEL is not set`
- **Solution**: Configure all 3 reviewer models in `.env`

### Frontend can't connect to backend

**Error**: `Failed to fetch` in browser console
- **Solution**: Ensure backend is running on port 8000
- **Solution**: Check `NEXT_PUBLIC_COPILOTKIT_URL` in frontend `.env.local`

### Checkpoints not working

**Issue**: Graph doesn't pause at checkpoints
- **Solution**: Verify PostgresSaver checkpointer is initialized
- **Solution**: Check database connection is active

### LLM calls fail

**Error**: `API rate limit exceeded`
- **Solution**: Check your API key and quota
- **Solution**: Reduce concurrent requests

**Error**: `Model not found`
- **Solution**: Verify model names in `.env` match your API provider

## Development

### Project Structure

```
contract-review-agent/
├── agent/                    # LangGraph agent core
│   ├── nodes/               # Graph nodes (generate, review, evaluate, etc.)
│   ├── state.py             # ReviewState TypedDict
│   ├── graph.py             # StateGraph definition
│   ├── checkpointer.py      # PostgresSaver setup
│   ├── config.py            # Reviewer config loader
│   └── store.py             # agent_runs CRUD
├── api/                     # FastAPI backend
│   ├── main.py             # App entry point
│   ├── copilotkit.py       # AG-UI endpoint
│   ├── config.py           # Server settings
│   └── routes/             # HTTP routes
├── db/                      # Database migrations
│   ├── 001_agent_runs.sql  # Schema
│   └── apply_migration.py  # Migration runner
├── frontend/                # Next.js frontend
│   ├── src/
│   │   ├── app/            # Pages
│   │   └── components/     # React components
│   └── package.json
├── tests/                   # Integration tests
├── .env.example            # Environment template
├── pyproject.toml          # Python dependencies
└── README.md               # This file
```

### Adding a New Reviewer

1. Add to `.env`:
   ```bash
   REVIEWER_4_MODEL=openai/gpt-4
   REVIEWER_4_LENS=legal_accuracy
   REVIEWER_4_NAME=Senior Legal Reviewer
   ```

2. The agent automatically picks up the new reviewer (no code changes needed)

### Customizing Lenses

Edit `agent/nodes/prompts.py` to modify lens-specific prompts:

```python
LENS_PROMPTS = {
    "legal_accuracy": "Your custom legal accuracy prompt...",
    "commercial_fairness": "Your custom commercial fairness prompt...",
    "completeness": "Your custom completeness prompt...",
}
```

## License

Part of the law-template project. See main repository for license details.

## Support

For issues or questions, refer to the main law-template documentation or open an issue in the repository.
