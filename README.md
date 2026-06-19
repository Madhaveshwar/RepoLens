# AI Code Reviewer with GitHub Integration (Enterprise Full-Stack Architecture)

An enterprise-grade, asynchronous full-stack platform that automates pull request auditing, security vulnerability checks, code smell detection, test generation, and repository health analytics.

This architecture upgrades the original Streamlit application into a microservice-ready system featuring a React 19 SPA, a FastAPI async backend, PostgreSQL database persistence, Redis cache caching, and a background Celery worker queue.

---

## 🏗️ Target Architecture Overview

The system is decoupled into isolated layers:
*   **Frontend:** React 19, TypeScript, Vite, TailwindCSS, Zustand (global state), TanStack React Query (data fetching), Monaco Code Editor (diffing and snippet review), and Recharts (SaaS analytics dashboards).
*   **Backend:** FastAPI (async REST routes + WebSockets for live progress tracking), Pydantic (data parsing).
*   **Database:** PostgreSQL (persistence of connected repos, PRs, scans history, security findings, code smells).
*   **Caching & Broker:** Redis (Celery broker, caching, Pub/Sub channels for WebSocket streams).
*   **Background Worker:** Celery (concurrent repository recursion, AI reviews parsing, report creation).
*   **Security:** AES-256 symmetric encryption for user access PATs and Groq Keys using Fernet.

```mermaid
graph TD
    Client[React 19 Frontend] <-->|REST HTTP / WebSockets| API[FastAPI Backend]
    API <--> DB[(PostgreSQL)]
    API <--> Redis[(Redis Cache / Broker)]
    API -->|Queue Job| Worker[Celery Worker]
    Worker <--> DB
    Worker -->|Fetch PR / Repository| GitHub[GitHub API]
    Worker -->|Execute AI Scan| Groq[Groq API]
```

---

## 📁 Project Directory Structure

```text
├── backend/
│   ├── app/
│   │   ├── auth/            # JWT Token generation, hashing, AES-256 encryption
│   │   ├── database/        # Async/Sync connection settings and Base
│   │   ├── models/          # SQLAlchemy Database Models (User, Repo, PR, Finding...)
│   │   ├── schemas/         # Pydantic serialization schemas
│   │   ├── services/        # Relocated Prompt and Review engines (PyGithub, Groq)
│   │   ├── routers/         # Endpoint modules (auth, users, repositories, analysis...)
│   │   ├── tasks/           # Asynchronous Celery task files
│   │   ├── websockets/      # Live Redis Pub/Sub WebSocket handlers
│   │   ├── utils/           # Validation checks and prompt templates
│   │   ├── config.py        # Settings configuration loader
│   │   └── main.py          # FastAPI application entrypoint
│   ├── Dockerfile
│   └── requirements.txt     # Python backend dependencies
│
├── frontend/
│   ├── src/
│   │   ├── components/      # UI components, Sidebar, Monaco layout
│   │   ├── pages/           # Login, Register, Dashboard, Repo Detail, settings, snippet review
│   │   ├── store/           # Zustand state managers (auth, repos, analyses)
│   │   ├── App.tsx          # Client router
│   │   └── main.tsx
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── package.json
│   └── Dockerfile
│
├── .github/
│   └── workflows/
│       └── ci-cd.yml        # CI/CD test automation runner
│
├── docker-compose.yml       # Orchestrates all full-stack services
├── .env.example             # Template for variables setup
└── README.md                # System documentation
```

---

## 🔑 Security and Key Management

User-supplied credentials (GitHub PAT and Groq API Key) are secured:
1.  **Encryption:** When submitted on the `/settings` page, the keys are encrypted on the server using AES-256 symmetric encryption (Fernet).
2.  **Storage:** Only the encrypted strings are persisted in the PostgreSQL database.
3.  **Decryption:** Keys are decrypted on-the-fly inside Celery worker memory only when executing active review scans.
4.  **Master Key:** Make sure to set a safe 32-byte URL-safe base64 `ENCRYPTION_KEY` in your `.env`.

---

## ⚙️ Environment Configuration

Create a `.env` file in the root workspace directory before starting services:

```env
# Database Settings
DATABASE_URL=postgresql+asyncpg://reviewer_user:reviewer_password@postgres/code_reviewer
SYNC_DATABASE_URL=postgresql://reviewer_user:reviewer_password@postgres/code_reviewer

# Caching & Queue Broker
REDIS_URL=redis://redis:6379/0

# Master Encryption Key (32-byte URL-safe base64 key)
ENCRYPTION_KEY=u-3M1t-H3VnJzLox58pZf4lX3z4P4hGZ8Z0K2S-2U_w=

# JWT JWT_SECRET
JWT_SECRET=super_secret_jwt_sign_key_change_me_in_prod_1234567890

# Optional Server-wide Fallback Credentials
GITHUB_TOKEN=your_global_github_token
GROQ_API_KEY=your_global_groq_key
```

---

## 🚀 Getting Started with Docker Compose

Running the entire system inside Docker containers is the recommended option for local testing and production deployments.

### Prerequisites
*   Docker and Docker Compose installed.

### Launching Services
To spin up all services (PostgreSQL, Redis, Backend, Celery Worker, Frontend), run:

```bash
docker-compose up --build
```

### Accessing the Applications
*   **React Frontend:** Open `http://localhost:3000` in your web browser.
*   **FastAPI Documentation:** View fully documented routes at `http://localhost:8000/docs`.

---

## 🛠️ Local Development (Non-Docker Setup)

If you prefer executing services locally outside containers, you must run PostgreSQL and Redis on your local machine.

### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/Scripts/activate  # On Unix use: source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Celery Worker Setup
Ensure Redis is active, then launch worker from the `backend/` directory:
```bash
celery -A app.tasks.tasks.celery_app worker --loglevel=info
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open the Dev Server at `http://localhost:5173`.

---

## 🧪 Running Unit Tests

Unit tests are implemented inside the `backend/app/tests` package. To verify logic using SQLite in-memory connections:

```bash
cd backend
pytest
```

---

## 🛡️ License

This project is licensed under the MIT License.
