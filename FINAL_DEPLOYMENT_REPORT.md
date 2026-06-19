# FINAL_DEPLOYMENT_REPORT.md

**Generated:** June 19, 2026
**Scope:** Database initialization failure analysis and exact deployment configurations for all environments

---

## 1. DATABASE CONFIGURATION ANALYSIS

### 1.1 Configuration Entry Points

The database URL is configured through a two-layer system:

```
Layer 1: Environment Variable (highest priority)
         ↓
Layer 2: Code Default (fallback in backend/app/config.py)
```

**File: `backend/app/config.py` (lines 19-20)**
```python
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://reviewer_user:reviewer_password@postgres:5432/code_reviewer"
)
SYNC_DATABASE_URL: str = os.getenv(
    "SYNC_DATABASE_URL",
    "postgresql://reviewer_user:reviewer_password@postgres:5432/code_reviewer"
)
```

### 1.2 Hostname Resolution Issue

| Component | Default Hostname | Resolves Outside Docker? | Resolves Inside Docker? |
|-----------|-----------------|--------------------------|-------------------------|
| `DATABASE_URL` | `postgres` | ❌ **No** | ✅ **Yes** (Docker DNS) |
| `SYNC_DATABASE_URL` | `postgres` | ❌ **No** | ✅ **Yes** (Docker DNS) |

**Root Cause:** The hardcoded default `postgres` is the Docker Compose **service name**, not a real DNS hostname. When running the backend directly on the host machine (without Docker Compose), the system cannot resolve `postgres` to an IP address.

### 1.3 Full Database Configuration Chain

```mermaid
flowchart TD
    ENV[".env / Environment Variables"] --> |DATABASE_URL| CONFIG["backend/app/config.py<br/>Settings.DATABASE_URL"]
    ENV --> |SYNC_DATABASE_URL| CONFIG2["backend/app/config.py<br/>Settings.SYNC_DATABASE_URL"]
    
    CONFIG --> |async| DB_ASYNC["backend/app/database/database.py<br/>create_async_engine(DATABASE_URL)"]
    CONFIG2 --> |sync| DB_SYNC["backend/app/database/database.py<br/>create_engine(SYNC_DATABASE_URL)"]
    
    DB_ASYNC --> |AsyncSession| FASTAPI["FastAPI Routes<br/>(get_async_db fixture)"]
    DB_SYNC --> |Session| CELERY["Celery Worker<br/>(get_sync_db fixture)"]
    DB_SYNC --> |Session| ALEMBIC["Alembic Migrations<br/>(env.py)"]
    DB_SYNC --> |Session| INIT["main.py init_db()<br/>(startup table creation)"]
    
    INIT --> |on startup| FAIL{"postgres hostname<br/>resolvable?"}
    FAIL --> |Yes<br/>Docker/Managed| OK["✅ Database initialized<br/>Tables created<br/>Alembic stamped"]
    FAIL --> |No<br/>Local/Native| ERROR["❌ psycopg2.OperationalError<br/>could not translate hostname<br/>'postgres' to address"]
```

### 1.4 Database URL By Environment

| Variable | Default | Docker Compose | Render | Local Dev | Local Dev (SQLite) |
|----------|---------|---------------|--------|-----------|-------------------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@postgres:5432/code_reviewer` | ✅ Overridden explicitly in `docker-compose.yml` | ✅ Auto-injected by Render via `fromDatabase` | ❌ MUST override to `localhost` | ✅ `sqlite+aiosqlite:///test.db` |
| `SYNC_DATABASE_URL` | `postgresql://user:pass@postgres:5432/code_reviewer` | ✅ Overridden explicitly in `docker-compose.yml` | ✅ Auto-injected by Render via `fromDatabase` | ❌ MUST override to `localhost` | ✅ `sqlite:///test.db` |

---

## 2. VERDICT: IS THIS EXPECTED?

**Yes. This is expected behavior for a Docker-only default configuration.**

The defaults were intentionally set to match the Docker Compose service name `postgres`. This is a common pattern in Docker-centric projects:

- **`docker-compose.yml`** explicitly overrides `DATABASE_URL` and `SYNC_DATABASE_URL` with the same hostname, so the defaults are never used inside Docker.
- **Render** auto-injects the actual database connection string via its `fromDatabase` property, so defaults are never used.
- **Outside Docker**, the defaults fail immediately with a clear error (`could not translate hostname "postgres" to address`), which signals to the developer that they must configure the database URL.

### Architectural Decision

This is a **intentional design trade-off** — the defaults are optimized for Docker Compose development rather than local native development. The project expects developers to either:

1. Use Docker Compose (recommended — one command: `docker-compose up --build`)
2. Override `DATABASE_URL`/`SYNC_DATABASE_URL` in their `.env` file for local development

**This is NOT a bug.** It is a design choice that prioritizes Docker-first development.

---

## 3. EXACT LOCAL DEVELOPMENT CONFIGURATIONS

### 3.1 Option A: Run PostgreSQL Locally (Recommended for Full Feature Testing)

**Prerequisites:** PostgreSQL must be installed and running on your machine.

**Step 1: Create the PostgreSQL database**
```bash
# Connect to PostgreSQL
psql -U postgres

# Inside psql:
CREATE DATABASE code_reviewer;
CREATE USER reviewer_user WITH PASSWORD 'reviewer_password';
GRANT ALL PRIVILEGES ON DATABASE code_reviewer TO reviewer_user;
\q
```

**Step 2: Create `.env` file in project root**
```env
# Database - use localhost instead of Docker service name
DATABASE_URL=postgresql+asyncpg://reviewer_user:reviewer_password@localhost:5432/code_reviewer
SYNC_DATABASE_URL=postgresql://reviewer_user:reviewer_password@localhost:5432/code_reviewer

# Redis - only needed if running locally, otherwise override for Docker
REDIS_URL=redis://localhost:6379/0

# Required: Generate these with:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
JWT_SECRET=your_generated_jwt_secret_here
ENCRYPTION_KEY=your_generated_fernet_key_here

# Optional: Global fallback credentials
GROQ_API_KEY=your_groq_api_key
GITHUB_TOKEN=your_github_token

# CORS for local frontend dev
BACKEND_CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://localhost:8000
```

**Step 3: Start the backend**
```bash
cd backend

# Ensure PYTHONPATH is set correctly
export PYTHONPATH=/:/backend:$PYTHONPATH  # On Windows: set PYTHONPATH=/:/backend

# Run database migrations
alembic -c alembic.ini upgrade head

# Start the server
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Step 4: Start the Celery worker** (in a separate terminal)
```bash
cd backend
celery -A backend.app.tasks.tasks.celery_app worker --loglevel=info
```

**Step 5: Start the frontend** (in a separate terminal)
```bash
cd frontend
npm install
npm run dev
```

### 3.2 Option B: Use SQLite for Development-Only Testing

**When to use:** Quick testing of non-database features, running the test suite, or when PostgreSQL is not available.

**.env configuration:**
```env
# SQLite for local development (NOT for production)
DATABASE_URL=sqlite+aiosqlite:///test.db
SYNC_DATABASE_URL=sqlite:///test.db

# Required: JWT and encryption keys
JWT_SECRET=your_generated_jwt_secret_here
ENCRYPTION_KEY=your_generated_fernet_key_here

# Global credentials
GROQ_API_KEY=your_groq_api_key
GITHUB_TOKEN=your_github_token
```

**Important SQLite limitations:**
| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Concurrent writes | ❌ No (single-writer) | ✅ Yes (MVCC) |
| `asyncpg` driver | ❌ No (uses `aiosqlite`) | ✅ Yes |
| Array/JSON columns | ⚠️ Limited | ✅ Full support |
| Production safety | ❌ Not recommended | ✅ Enterprise-grade |
| Test suite | ✅ Used in tests | ✅ Also works |

### 3.3 Option C: Docker Compose (Easiest, No Local Dependencies)

**Prerequisites:** Docker and Docker Compose installed.

**Step 1: Create `.env` file in project root**
```env
# Only required vars - Docker Compose provides all infrastructure URLs
JWT_SECRET=your_generated_jwt_secret_here
ENCRYPTION_KEY=your_generated_fernet_key_here
GROQ_API_KEY=your_groq_api_key
GITHUB_TOKEN=your_github_token
```

**Step 2: Start all services**
```bash
docker-compose up --build
```

**Step 3: Access the applications**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

**Docker just works because:**
- `docker-compose.yml` explicitly sets `DATABASE_URL=postgresql+asyncpg://reviewer_user:reviewer_password@postgres/code_reviewer`
- The `postgres` hostname is resolved by Docker's built-in DNS on the `acr_network` bridge network
- Alembic migrations run automatically via the backend's `command`: `alembic -c alembic.ini upgrade head && uvicorn ...`

---

## 4. EXACT RENDER DEPLOYMENT CONFIGURATION

### 4.1 Pre-Deployment Checklist

| Item | Status | Action Required |
|------|--------|-----------------|
| `ENCRYPTION_KEY` | ❌ Not set | Must be set manually in Render Dashboard |
| `GROQ_API_KEY` | ❌ Not set | Must be set manually in Render Dashboard |
| `GITHUB_TOKEN` | ❌ Not set | Must be set manually in Render Dashboard |
| `JWT_SECRET` | ✅ Auto-generated | `generateValue: true` in render.yaml |
| `DATABASE_URL` | ✅ Auto-injected | Render managed PostgreSQL via `fromDatabase` |
| `SYNC_DATABASE_URL` | ✅ Auto-injected | Render managed PostgreSQL via `fromDatabase` |
| `REDIS_URL` | ✅ Auto-injected | Render managed Redis via `fromService` |

### 4.2 Steps to Deploy

**Step 1: Push code to GitHub**
```bash
git push origin main
```

**Step 2: Connect repository to Render**

1. Go to https://dashboard.render.com
2. Click **"New +"** → **"Blueprint"**
3. Connect your GitHub repository
4. Render reads `render.yaml` and creates all services:
   - **acr-backend** (Web Service — FastAPI)
   - **acr-worker** (Worker — Celery)
   - **acr-postgres** (Managed PostgreSQL)
   - **acr-redis** (Managed Redis)

**Step 3: Set sensitive environment variables**

In the Render Dashboard, for each service that needs them:

**For acr-backend (Web Service):**
| Variable | Value | Source |
|----------|-------|--------|
| `DATABASE_URL` | ✅ Auto-filled by Render | Render managed PostgreSQL |
| `SYNC_DATABASE_URL` | ✅ Auto-filled by Render | Render managed PostgreSQL |
| `REDIS_URL` | ✅ Auto-filled by Render | Render managed Redis |
| `JWT_SECRET` | ✅ Auto-generated by Render | `generateValue: true` |
| `ENCRYPTION_KEY` | 🔴 **Must be set manually** | Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GROQ_API_KEY` | 🔴 **Must be set manually** | Your Groq API key |
| `GITHUB_TOKEN` | 🔴 **Must be set manually** | Your GitHub PAT |

**For acr-worker:** Same as acr-backend (JWT_SECRET is auto-synced via `fromService:acr-backend`).

**Step 4: Deploy**

Render will:
1. Build the backend image (`pip install -r backend/requirements.txt`)
2. Start the PostgreSQL database
3. Start the Redis cache
4. Start the web service (`uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`)
5. Start the worker (`celery -A backend.app.tasks.tasks.celery_app worker --loglevel=info`)

**Step 5: Deploy frontend to Vercel**

1. Go to https://vercel.com
2. Import your repository
3. Set **Root Directory** to `frontend`
4. Set **Build Command** to `npm run build`
5. Set **Output Directory** to `dist`
6. Set environment variable: `VITE_API_BASE_URL=https://acr-backend.onrender.com`
7. Deploy

### 4.3 Render Runtime Configuration (from render.yaml)

```yaml
# Key configuration that manages database auto-injection:
services:
  - type: web
    name: acr-backend
    envVars:
      - key: DATABASE_URL        # Render auto-injects the PostgreSQL connection string
        fromDatabase:
          name: acr-postgres
          property: connectionString
      - key: SYNC_DATABASE_URL   # Same — Render provides this as postgresql://...
        fromDatabase:
          name: acr-postgres
          property: connectionString
      - key: REDIS_URL           # Render auto-injects the Redis connection string
        fromService:
          type: cache
          name: acr-redis
          property: connectionString
```

**How Render resolves the database hostname:**
1. Render creates a managed PostgreSQL instance at a real DNS address like `dpg-xxxxx.render.com`
2. The `fromDatabase` property injects the full connection string including the correct hostname
3. The backend connects to the real hostname — no `postgres` service name needed

### 4.4 Vercel Frontend Configuration (from vercel.json)

```json
{
  "rewrites": [
    {
      "source": "/api/v1/:path*",
      "destination": "https://acr-backend.onrender.com/api/v1/:path*"
    },
    {
      "source": "/((?!api/v1/).*)",
      "destination": "/index.html"
    }
  ]
}
```

The Vercel frontend proxies API calls to the Render backend. In production, the `VITE_API_BASE_URL` environment variable should be set to `https://acr-backend.onrender.com`.

---

## 5. EXACT DOCKER DEPLOYMENT CONFIGURATION

### 5.1 Complete docker-compose.yml Database Configuration

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: acr_postgres
    environment:
      POSTGRES_DB: code_reviewer
      POSTGRES_USER: reviewer_user
      POSTGRES_PASSWORD: reviewer_password
    ports:
      - "5432:5432"           # Exposed to host for external DB tools
    volumes:
      - pgdata:/var/lib/postgresql/data  # Persistent storage
    networks:
      - acr_network           # Isolated bridge network

  backend:
    build: ./backend
    environment:
      # Explicitly set database URLs — overrides config.py defaults
      - DATABASE_URL=postgresql+asyncpg://reviewer_user:reviewer_password@postgres/code_reviewer
      - SYNC_DATABASE_URL=postgresql://reviewer_user:reviewer_password@postgres/code_reviewer
      - REDIS_URL=redis://redis:6379/0
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}  # From .env file
      - PYTHONPATH=/:/backend
    command: sh -c "alembic -c alembic.ini upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"
    depends_on:
      - postgres              # Ensures postgres starts first
      - redis
    networks:
      - acr_network

volumes:
  pgdata:                     # Named volume for data persistence

networks:
  acr_network:
    driver: bridge            # Internal DNS resolves service names
```

### 5.2 Why Docker DNS Resolves `postgres`

Docker Compose creates a user-defined bridge network (`acr_network`) that provides:

1. **Automatic DNS resolution:** Each container can reach other containers by their service name
2. **Isolation:** Containers on different networks cannot communicate
3. **Orderly startup:** `depends_on` ensures PostgreSQL starts before the backend

When the backend container attempts to connect to `postgres:5432`, Docker DNS resolves it to the PostgreSQL container's internal IP (e.g., `172.18.0.2`).

### 5.3 Steps to Deploy with Docker

```bash
# 1. Create .env file with required secrets
cat > .env << EOF
JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
GROQ_API_KEY=your_groq_api_key
GITHUB_TOKEN=your_github_token
EOF

# 2. Build and start all services
docker-compose up --build

# 3. (Optional) Run in detached mode
docker-compose up --build -d

# 4. View logs
docker-compose logs -f backend

# 5. Stop all services
docker-compose down

# 6. Destroy volumes (removes all data)
docker-compose down -v
```

### 5.4 Production Docker Deployment Considerations

| Concern | Recommendation |
|---------|----------------|
| PostgreSQL password | Change from default `reviewer_password` in production |
| Data persistence | Named volume `pgdata` persists across restarts |
| Resource limits | Add `deploy.resources.limits` to each service |
| Health checks | Add `healthcheck` to PostgreSQL and Redis |
| Logging | Configure `logging.driver` for centralized logging |
| Secrets | Use Docker secrets instead of `.env` in swarm mode |

---

## 6. ENVIRONMENT COMPARISON MATRIX

| Aspect | Docker Compose | Render | Local Development |
|--------|---------------|--------|-------------------|
| **Database hostname** | `postgres` (service name) | `dpg-xxxxx.render.com` (managed) | `localhost` (must override) |
| **DNS resolution** | ✅ Docker internal DNS | ✅ Real DNS | ✅ Localhost |
| **Database setup** | Auto (docker-compose up) | Auto (managed service) | Manual (create DB + user) |
| **Migrations** | Auto (in entrypoint command) | On startup (init_db) | Manual (`alembic upgrade head`) |
| **Redis setup** | Auto (docker-compose up) | Auto (managed service) | Manual (install & run) |
| **Data persistence** | Named volumes | Managed backups | Local PG data directory |
| **Required .env vars** | `JWT_SECRET`, `ENCRYPTION_KEY`, `GROQ_API_KEY`, `GITHUB_TOKEN` | Set via Dashboard | `JWT_SECRET`, `ENCRYPTION_KEY`, `DATABASE_URL`, `SYNC_DATABASE_URL`, `GROQ_API_KEY`, `GITHUB_TOKEN` |
| **Best for** | Development & CI | Production hosting | Development without Docker |

---

## 7. TROUBLESHOOTING

### 7.1 "could not translate hostname 'postgres' to address"

**Cause:** Running the backend outside Docker without overriding `DATABASE_URL`.

**Fix:** Set these in your `.env`:
```env
DATABASE_URL=postgresql+asyncpg://reviewer_user:reviewer_password@localhost:5432/code_reviewer
SYNC_DATABASE_URL=postgresql://reviewer_user:reviewer_password@localhost:5432/code_reviewer
```

### 7.2 "connection refused" when connecting to PostgreSQL

**Cause:** PostgreSQL is not running, or the port/credentials are wrong.

**Fix:**
```bash
# Check if PostgreSQL is running
pg_isready

# Check PostgreSQL status
systemctl status postgresql  # Linux
brew services list           # macOS
sc query state=all | findstr postgres  # Windows

# Verify credentials
psql -U reviewer_user -d code_reviewer -h localhost
```

### 7.3 "database 'code_reviewer' does not exist"

**Cause:** The database has not been created yet.

**Fix:**
```bash
createdb -U postgres code_reviewer
psql -U postgres -c "CREATE DATABASE code_reviewer;"
psql -U postgres -c "CREATE USER reviewer_user WITH PASSWORD 'reviewer_password';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE code_reviewer TO reviewer_user;"
```

### 7.4 Alembic migration fails

**Cause:** Database URL mismatch or outdated migration scripts.

**Fix:**
```bash
# Check current migration state
alembic -c alembic.ini current

# Force stamp to head
alembic -c alembic.ini stamp head

# Run migrations manually
alembic -c alembic.ini upgrade head
```

---

## 8. RECOMMENDED DEVELOPMENT WORKFLOW

```
┌────────────────────────────────────────────────────────────┐
│              RECOMMENDED DEVELOPMENT WORKFLOW                │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Initial Setup                                           │
│     └── docker-compose up --build                           │
│         (Zero configuration — everything just works)        │
│                                                              │
│  2. Daily Development                                       │
│     ├── Backend changes → docker-compose restart backend    │
│     ├── Frontend changes → npm run dev (outside Docker)     │
│     └── Database changes → alembic revision --autogenerate  │
│                                                              │
│  3. Testing                                                 │
│     └── cd backend && pytest                                │
│         (Uses SQLite — no PostgreSQL needed)                │
│                                                              │
│  4. Production Deployment                                    │
│     ├── Frontend → Push to GitHub → Vercel auto-deploys    │
│     ├── Backend → Push to GitHub → Render auto-deploys     │
│     └── Secrets → Set in Render Dashboard (not in repo)    │
│                                                              │
└────────────────────────────────────────────────────────────┘
```

---

## 9. SUMMARY

| # | Question | Answer |
|---|----------|--------|
| 1 | **Why does database initialization fail?** | Default hostname `postgres` is a Docker service name, not a real DNS hostname. Only resolvable inside Docker Compose's bridge network. |
| 2 | **Is this expected?** | **Yes.** The defaults are intentionally Docker-first. The project is designed to run via `docker-compose up --build`. |
| 3 | **What is the local dev fix?** | Override `DATABASE_URL` to `localhost` in `.env`, or use Docker Compose. |
| 4 | **Does Render have this issue?** | **No.** Render auto-injects the real database connection string via `fromDatabase` in `render.yaml`. |
| 5 | **Does Docker have this issue?** | **No.** Docker Compose resolves `postgres` to the PostgreSQL container via internal DNS on the `acr_network` bridge network. |
| 6 | **Is this a bug?** | **No.** This is a deliberate architectural decision for a Docker-first development experience. |

---

*End of FINAL_DEPLOYMENT_REPORT.md*
