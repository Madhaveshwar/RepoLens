# RepoLens AI — GitHub Repository Analysis Platform

An enterprise-grade, full-stack platform that automates pull request auditing, security vulnerability detection, code quality analysis, test generation, and repository health analytics powered by AI.

> 🎓 **B.Tech Mini Project** — Fully functional, deployment-ready, production-grade architecture.

---

## 📋 Overview

This platform connects to GitHub repositories, analyzes pull requests and source code using AI (Groq LLM), and provides detailed reports on security vulnerabilities, code smells, test coverage gaps, and overall repository health. It features a modern React frontend, a high-performance FastAPI backend, and a background task queue for asynchronous processing.

---

## ✨ Features

### 🔍 GitHub Repository Analysis
- Connect and analyze any public/private GitHub repository
- Recursive file tree traversal and source code extraction
- Repository health scoring (0–100) with itemized deductions

### 🔄 Pull Request Review
- Automated AI-powered review of PR changes
- Security vulnerability detection (OWASP Top 10 aligned)
- Code smell identification and refactoring suggestions
- Inline PR comments posted directly to GitHub

### 🛡️ Security Scanning
- Detects SQL injection, XSS, CSRF, hardcoded secrets, weak cryptography
- Before/after code comparisons with remediation examples
- Severity-based risk scoring (Critical/High/Medium/Low/Info)

### 🔧 Code Quality Analysis
- Detects long methods, duplicate code, magic numbers, deep nesting
- Performance inefficiency detection
- Maintainability and technical debt assessment

### 🧪 Test Generation
- AI-generated unit tests, integration tests, edge cases, and negative tests
- Language-specific test templates

### 📊 Dashboard Analytics
- Real-time scan progress via WebSocket
- Historical scan comparison and trend analysis
- Security score history and health trends
- Repository health score tracking over time

### 📦 Export Reports
- **PDF** — Styled professional reports with severity-colored tables
- **Markdown** — Full detailed analysis with code blocks
- **JSON** — Machine-readable structured data
- **CSV** — Spreadsheet-friendly findings export

### 🔐 Auto-Fix Suggestions
- AI-powered fix generation with before/after code comparison
- Confidence scoring and validation pipeline
- One-click branch creation and PR submission

---

## 🛠️ Tech Stack

### Frontend
| Technology | Purpose |
|-----------|---------|
| **React 19** | UI framework |
| **TypeScript** | Type safety |
| **Vite** | Build tool and dev server |
| **TailwindCSS** | Utility-first styling |
| **Zustand** | State management |
| **TanStack React Query** | Server state & caching |
| **Monaco Editor** | Code editor & diff viewer |
| **Recharts** | Analytics dashboards |
| **Framer Motion** | Animations & transitions |

### Backend
| Technology | Purpose |
|-----------|---------|
| **FastAPI** | Async REST API framework |
| **SQLAlchemy** | ORM with async support |
| **PostgreSQL** | Primary database |
| **Redis** | Caching, Celery broker, WebSocket pub/sub |
| **Celery** | Background task queue |
| **Alembic** | Database migrations |
| **Pydantic** | Data validation & serialization |

### AI & Integrations
| Technology | Purpose |
|-----------|---------|
| **Groq** | Primary LLM provider (free tier) |
| **OpenAI / Claude / Gemini** | Alternative LLM providers |
| **OpenRouter** | Multi-model gateway |
| **PyGithub** | GitHub API client |
| **LangSmith** | LLM observability & tracing |

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    RepoLens AI                              │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌──────────┐     ┌─────────────┐     ┌──────────────┐   │
│  │ React 19 │◄────►│  FastAPI    │◄────►│  PostgreSQL  │   │
│  │ Frontend │ REST │  Backend    │     │  Database    │   │
│  │  (Vite)  │  WS  │  (Celery)   │     │              │   │
│  └──────────┘     └──────┬──────┘     └──────────────┘   │
│                           │                                │
│                    ┌──────▼──────┐    ┌──────────────┐    │
│                    │    Redis    │◄──►│   Celery     │    │
│                    │ Cache/Broker│    │   Worker     │    │
│                    └─────────────┘    └──────┬───────┘    │
│                                              │            │
│                    ┌─────────────────────────▼─────────┐  │
│                    │         External APIs              │  │
│                    │  ├── GitHub API (PyGithub)         │  │
│                    │  ├── Groq LLM API                  │  │
│                    │  ├── OpenAI / Claude / Gemini      │  │
│                    │  └── OpenRouter                    │  │
│                    └───────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### Data Flow
1. **User connects a GitHub repo** → Backend fetches metadata via PyGithub
2. **User triggers a scan** → Celery worker processes files asynchronously
3. **Worker sends code to Groq LLM** → AI analyzes for security, smells, tests
4. **Results stored in PostgreSQL** → Findings, scores, and reports persisted
5. **Frontend polls for updates** → Real-time progress via WebSocket
6. **Reports generated** → PDF, Markdown, JSON, CSV exports available
7. **Fixes applied** → Auto-generated fixes can be committed to GitHub

---

## 🔑 Security

- **Password hashing**: Argon2 (via `passlib`)
- **JWT tokens**: HS256 with configurable expiry
- **API key encryption**: AES-256 Fernet symmetric encryption
- **CSRF protection**: Origin + Referer header validation
- **Rate limiting**: 300 requests/minute per IP
- **HTTP security headers**: HSTS, CSP, X-Frame-Options, X-Content-Type-Options
- **CORS**: Strict allowlist of configured origins

---

## 🚀 Local Setup

### Prerequisites
- **Python 3.10+**
- **Node.js 22+**
- **PostgreSQL** (or Docker for containerized setup)
- **Redis** (optional, for Celery worker)

### Option 1: Docker Compose (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/your-username/AI-Code-Reviewer-with-GitHub-Integration.git
cd AI-Code-Reviewer-with-GitHub-Integration

# 2. Create .env file
cp .env.example .env
# Edit .env with your API keys

# 3. Start all services
docker-compose up --build
```

### Option 2: Local Development

#### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m pytest          # Run tests
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
```

#### Celery Worker (optional)
```bash
cd backend
celery -A app.tasks.tasks.celery_app worker --loglevel=info
```

### Environment Variables
```env
# Required
JWT_SECRET=<your-jwt-secret>
ENCRYPTION_KEY=<your-fernet-key>
GROQ_API_KEY=<your-groq-api-key>
GITHUB_TOKEN=<your-github-pat>

# Database (defaults to postgres on Docker)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/code_reviewer
```

---

## 🌐 Deployment

### Frontend — Vercel
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new)

1. Import your GitHub repository
2. Set root directory to `frontend`
3. Build command: `npm run build`
4. Output directory: `dist`
5. Environment variable: `VITE_API_URL=https://your-backend.onrender.com`

### Backend — Render
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

The `render.yaml` Blueprint auto-configures:
- FastAPI web service
- Celery background worker
- PostgreSQL database
- Redis cache

**Required secrets** (set in Render Dashboard):
- `ENCRYPTION_KEY`
- `GROQ_API_KEY`
- `GITHUB_TOKEN`

---

## 📸 Screenshots

> *Screenshots coming soon. Run the project locally to see the full UI.*

| Page | Description |
|------|-------------|
| **Dashboard** | Repository health scores, security metrics, activity timeline |
| **Repository Detail** | Scan results, file tree, code explorer with Monaco editor |
| **PR Review** | AI-powered pull request analysis with inline comments |
| **Settings** | API key management, LLM provider selection |
| **Reports** | Downloadable PDF, Markdown, JSON, CSV reports |

---

## 🧪 Running Tests

```bash
cd backend
python -m pytest
```

Tests use SQLite in-memory databases — no external dependencies required.

---

## 🏅 Best Practices

- ✅ **TypeScript** throughout frontend (strict mode)
- ✅ **Type hints** throughout Python backend
- ✅ **Async/await** for all I/O operations
- ✅ **Argon2** password hashing (not bcrypt/sha)
- ✅ **AES-256** encryption for stored API keys
- ✅ **Parameterized SQL** via SQLAlchemy ORM
- ✅ **Comprehensive error handling** with graceful degradation
- ✅ **Logging** with secrets masking
- ✅ **Audit logging** for security-sensitive operations
- ✅ **API versioning** (`/api/v1/`)
- ✅ **CORS, CSRF, Rate limiting** middleware

---

## 🔮 Future Enhancements

- [ ] Email notifications for scan completion
- [ ] Scheduled recurring scans
- [ ] Multi-repository comparison dashboard
- [ ] Custom rule engine for organization policies
- [ ] VS Code extension integration
- [ ] Team collaboration features
- [ ] On-premise deployment option
- [ ] Mobile-responsive UI improvements
- [ ] Performance optimizations for monorepo scanning

---

## 📄 License

This project is licensed under the **MIT License**.

---

<div align="center">
  <sub>Built with ❤️ for the open-source community</sub>
</div>
