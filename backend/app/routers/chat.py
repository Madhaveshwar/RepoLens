"""AI Review Assistant – Smart Chatbot Router.

Provides both blocking and streaming chat endpoints. Accepts a user message
and optional page context (current page, finding info, scan results, etc.)
and returns an AI-generated response using the user's configured LLM provider.

Streaming endpoint (/chat/ask/stream) uses Server-Sent Events (SSE) to stream
tokens one by one for a real-time typing effect.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Any, AsyncGenerator
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User, Analysis, Repository, SecurityFinding, CodeSmell
from app.auth.security import get_current_user
from app.config import settings
from app.database.database import get_async_db
from app.services.llm_client import build_llm_client, get_model_name, friendly_llm_error
from app.utils.logger import get_logger

logger = get_logger("chat_router")

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    message: str
    current_page: Optional[str] = None           # e.g. "dashboard", "repository", "local-review", "settings"
    finding_context: Optional[dict[str, Any]] = None  # Current finding/report info
    beginner_mode: bool = False
    conversation_history: Optional[list[dict[str, str]]] = None


class ChatResponse(BaseModel):
    reply: str
    suggested_questions: list[str] = []


ASSISTANT_SYSTEM_PROMPT = """You are the AI Assistant of RepoLens AI — an AI repository analyzer that scans GitHub repositories and reports security findings, code quality issues, tests, and insights.

Your role is to help users understand:
- Code review findings (security vulnerabilities, code smells, performance issues)
- AI-generated fix suggestions
- Repository scan results
- Code quality metrics and health scores
- Best practices for writing clean, secure code
- How to use the platform's features

**Grounding rules (highest priority):**
- When scan context is provided, answer about THAT repository using the actual repository name, file paths, line numbers, finding titles, severities and code snippets from the context. Never invent findings, files, or numbers.
- When asked "why is this issue?" / "what does this finding mean?" / "how can I fix this?" — explain THAT specific finding directly, not a generic tutorial.
- If a question needs information not in the context (or no scan has been run), say: "Not enough repository information was available to determine this. How about running a scan first?"
- Do not assume command injection, SQL injection, path traversal etc. unless the actual finding states it.
- Do not claim tools or scans were used that were not part of RepoLens AI.

**Answer style (efficiency rules, highest priority after grounding):**
- Answer the user's EXACT question in the first sentence. Do not open with restatements, disclaimers, or summaries of the repository context.
- Be concise: default to under 200 words unless the user explicitly asks for detail or depth.
- Do not repeat the repository context back (do not list all findings/files again); cite only the 1-3 pieces of evidence that answer the question, with file paths/line numbers when available.
- Never pad with generic advice, filler sentences, or repetition of earlier turns.
- When reusing results already present in the context (scan stats, findings, scores), prefer them over producing new numbers.

**Guidelines:**
1. Be concise but thorough. Use simple language for beginners and precise terms for experts.
2. When explaining security issues, always explain WHY it's a risk (not just what).
3. Use code examples in markdown code blocks when relevant.
4. Never reveal API keys, tokens, or secrets — if asked, say they are encrypted and secure.
5. If you don't know something, say so honestly.
6. Reference the user's current page context when available to give relevant answers.
7. When suggesting fixes, prefer safe, well-documented approaches.
8. When the context includes repository scan data (security findings, code quality issues, risk score), use THAT actual data to answer — cite specific files, severities and counts. Never invent findings that are not in the context.
9. If the user asks to "summarize this scan" and scan context is available, summarize the actual findings: total counts, most severe issues, affected files, and concrete next steps.

**Beginner Mode** (when enabled):
- Explain concepts in plain language
- Avoid jargon or define it
- Use analogies
- Be encouraging and educational

**Response Format:**
Respond in markdown with clear sections. Keep responses under 200 words unless more detail is needed; lead with the direct answer, then the key evidence, then (only if asked) next steps."""


# ── Resolve provider and API key (same pattern as analysis.py) ──

def _resolve_llm_key(current_user: User) -> tuple[str, str]:
    from app.auth.encryption import encryptor as _enc
    provider = (current_user.llm_default_provider or "groq").lower().strip()
    _key_map = {
        "groq":       current_user.groq_api_key_encrypted,
        "openai":     current_user.openai_api_key_encrypted,
        "anthropic":  current_user.claude_api_key_encrypted,
        "claude":     current_user.claude_api_key_encrypted,
        "gemini":     current_user.gemini_api_key_encrypted,
        "openrouter": current_user.openrouter_api_key_encrypted,
    }
    _env_map = {
        "groq":       settings.GROQ_API_KEY,
        "openai":     settings.OPENAI_API_KEY,
        "anthropic":  settings.ANTHROPIC_API_KEY,
        "claude":     settings.ANTHROPIC_API_KEY,
        "gemini":     settings.GEMINI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
    }
    enc_key = _key_map.get(provider)
    llm_api_key = _enc.decrypt(enc_key) if enc_key else _env_map.get(provider, "")
    if not llm_api_key:
        provider = "groq"
        groq_enc = current_user.groq_api_key_encrypted
        llm_api_key = _enc.decrypt(groq_enc) if groq_enc else settings.GROQ_API_KEY
    return provider, llm_api_key


# ── Latest-scan context loader (so shortcuts like "Summarize this scan" work
#    even from the Dashboard, using the user's most recent completed scan) ──

async def _load_latest_scan_context(db: AsyncSession, user_id) -> Optional[dict[str, Any]]:
    """Load the user's most recent completed repository scan with its findings.

    Returns a dict in the same shape the frontend sends for repository_scan
    context, or None when the user has no completed scans.
    """
    try:
        result = await db.execute(
            select(Analysis)
            .join(Repository, Analysis.repository_id == Repository.id)
            .where(
                (Repository.user_id == user_id)
                & (Analysis.status == "completed")
                & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
            )
            .order_by(Analysis.timestamp.desc())
            .limit(1)
        )
        analysis = result.scalars().first()
        if not analysis:
            return None

        repo_res = await db.execute(select(Repository).where(Repository.id == analysis.repository_id))
        repo = repo_res.scalars().first()

        sec_total_res = await db.execute(
            select(func.count(SecurityFinding.id)).where(SecurityFinding.analysis_id == analysis.id)
        )
        sec_total = sec_total_res.scalar() or 0
        smell_total_res = await db.execute(
            select(func.count(CodeSmell.id)).where(CodeSmell.analysis_id == analysis.id)
        )
        smell_total = smell_total_res.scalar() or 0

        sec_res = await db.execute(
            select(SecurityFinding)
            .where(SecurityFinding.analysis_id == analysis.id)
            .order_by(SecurityFinding.severity.asc(), SecurityFinding.file.asc())
            .limit(8)
        )
        sec_findings = [
            {
                "issue": f.issue,
                "severity": f.severity,
                "file": f.file,
                "line": f.line,
                "suggestion": (f.suggestion or "")[:300],
            }
            for f in sec_res.scalars().all()
        ]

        smell_res = await db.execute(
            select(CodeSmell)
            .where(CodeSmell.analysis_id == analysis.id)
            .limit(8)
        )
        code_smells = [
            {
                "issue": s.issue,
                "severity": s.severity,
                "file": s.file,
                "line": s.line,
            }
            for s in smell_res.scalars().all()
        ]

        return {
            "type": "repository_scan",
            "repository": repo.name if repo else "unknown",
            "risk_score": analysis.risk_score,
            "status": analysis.status,
            "timestamp": analysis.timestamp.strftime("%Y-%m-%d %H:%M UTC") if analysis.timestamp else None,
            "model_name": analysis.model_name,
            "files_analyzed_count": analysis.files_analyzed_count,
            "health_score": None,
            "security_findings_count": sec_total,
            "code_smells_count": smell_total,
            "security_findings": sec_findings,
            "code_smells": code_smells,
            "insights_excerpt": (analysis.insights or "")[:1200],
        }
    except Exception as e:
        logger.warning(f"Failed to load latest scan context for user {user_id}: {e}")
        return None


# ── Context-aware system prompt builder ──

def _format_scan_context(scan: dict[str, Any]) -> list[str]:
    """Serialize a repository-scan context dict (from the frontend or the DB)
    into readable prompt lines so the assistant can answer questions about
    the actual scan results."""
    parts = []
    parts.append(f"- Repository: {scan.get('repository', 'unknown')}")
    if scan.get("status"):
        parts.append(f"- Scan status: {scan['status']}")
    if scan.get("risk_score") is not None:
        parts.append(f"- Risk score: {scan['risk_score']}/100 (higher = riskier; security health ≈ {max(0, 100 - int(scan['risk_score'] or 0))}/100)")
    if scan.get("health_score") is not None:
        parts.append(f"- Health score: {scan['health_score']}/100")
    if scan.get("model_name"):
        parts.append(f"- Model used: {scan['model_name']}")
    if scan.get("files_analyzed_count") is not None:
        parts.append(f"- Files analyzed: {scan['files_analyzed_count']}")
    if scan.get("timestamp"):
        parts.append(f"- Scan date: {scan['timestamp']}")

    sec_count = scan.get("security_findings_count")
    sec_findings = scan.get("security_findings") or []
    if sec_count is not None:
        parts.append(f"- Total security findings: {sec_count}")
    if sec_findings:
        parts.append("- Top security findings:")
        for f in sec_findings[:8]:
            if isinstance(f, dict):
                parts.append(
                    f"  • [{f.get('severity', '?')}] {f.get('issue', '?')} "
                    f"(file: {f.get('file', '?')}, line: {f.get('line', '?')})"
                    + (f" → Fix: {f.get('suggestion', '')}" if f.get("suggestion") else "")
                )

    smell_count = scan.get("code_smells_count")
    smells = scan.get("code_smells") or []
    if smell_count is not None:
        parts.append(f"- Total code quality issues: {smell_count}")
    if smells:
        parts.append("- Top code quality issues:")
        for s in smells[:8]:
            if isinstance(s, dict):
                parts.append(
                    f"  • [{s.get('severity', '?')}] {s.get('issue', '?')} "
                    f"(file: {s.get('file', '?')}, line: {s.get('line', '?')})"
                )

    if scan.get("insights_excerpt"):
        parts.append(f"- Qualitative report excerpt: {scan['insights_excerpt']}")

    return parts


def _build_context_prompt(
    current_page: Optional[str],
    finding_context: Optional[dict],
    latest_scan: Optional[dict] = None,
) -> str:
    parts = []

    if current_page:
        page_guides = {
            "dashboard": "The user is on their Dashboard — showing repository health scores, security metrics, vulnerability trends, and recent scan activity.",
            "repository": "The user is viewing a specific repository detail page — showing scan history, security findings, code quality issues, and the code explorer.",
            "repositories": "The user is viewing a specific repository detail page — showing scan history, security findings, code quality issues, and the code explorer.",
            "local-review": "The user is using the Local Snippet Review — pasting code to get AI analysis, explanations, tests, refactoring, security scans, or complexity metrics.",
            "settings": "The user is on the Settings page — configuring API keys for LLM providers (Groq, OpenAI, Claude, Gemini, OpenRouter) and GitHub PAT.",
            "pr-review": "The user is reviewing a Pull Request — analyzing changed files, reviewing AI findings, and generating fixes.",
        }
        guide = page_guides.get(current_page, "")
        if guide:
            parts.append(f"**Current page:** {guide}")

    if finding_context:
        finding_type = finding_context.get("type", "unknown")

        if finding_type == "repository_scan":
            # Full scan context sent by the frontend — format it completely so
            # the assistant can actually summarize and answer questions about it.
            parts.append("\n**Current repository scan context:**")
            parts.extend(_format_scan_context(finding_context))
        elif finding_context.get("message"):
            parts.append(f"\n**Page context:** {finding_context['message']}")
        else:
            severity = finding_context.get("severity", "")
            issue = finding_context.get("issue", "")
            suggestion = finding_context.get("suggestion", "")
            file_path = finding_context.get("file", "")
            before_code = finding_context.get("before_code", "")
            after_code = finding_context.get("after_code", "")

            parts.append(f"\n**Active finding context:**")
            parts.append(f"- Type: {finding_type}")
            parts.append(f"- Severity: {severity}")
            parts.append(f"- Issue: {issue}")
            if suggestion:
                parts.append(f"- Suggestion: {suggestion}")
            if file_path:
                parts.append(f"- File: {file_path}")
            if before_code:
                parts.append(f"\n**Before code:**\n```\n{before_code}\n```")
            if after_code:
                parts.append(f"\n**After code (suggested fix):**\n```\n{after_code}\n```")

    if latest_scan:
        # Injected server-side so shortcuts like "Summarize this scan" work
        # even from pages that don't have scan data in the frontend store.
        parts.append("\n**Latest completed repository scan (from database):**")
        parts.extend(_format_scan_context(latest_scan))

    if parts:
        return "\n".join(parts)
    return ""


# ── Page-specific suggested questions ──

PAGE_SUGGESTIONS: dict[str, list[str]] = {
    "dashboard": [
        "Explain my health score",
        "What do the severity colors mean?",
        "How do I improve my security score?",
        "What's the most critical issue?"
    ],
    "repository": [
        "Summarize this scan",
        "What's the risk score mean?",
        "How do I fix these findings?",
        "Explain this vulnerability"
    ],
    "repositories": [
        "Summarize this scan",
        "What's the risk score mean?",
        "How do I fix these findings?",
        "Explain this vulnerability"
    ],
    "local-review": [
        "Explain this code",
        "Is this code secure?",
        "How can I improve performance?",
        "Suggest tests for this code"
    ],
    "settings": [
        "Which LLM provider should I use?",
        "How are my keys stored?",
        "How do I get a Groq API key?",
        "Why use a GitHub PAT?"
    ],
    "pr-review": [
        "Summarize this PR",
        "What are the riskiest changes?",
        "Should I approve this PR?",
        "Explain this finding"
    ],
}

DEFAULT_SUGGESTIONS = [
    "What can you help me with?",
    "How do scans work?",
    "Give me best practices",
    "Explain beginner mode"
]


@router.post("/ask", response_model=ChatResponse)
async def chat_ask(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Send a message to the AI Review Assistant and get a contextual reply."""
    logger.info(f"Chat request from user {current_user.id}: page={req.current_page}, msg_len={len(req.message)}")

    provider, llm_api_key = _resolve_llm_key(current_user)
    if not llm_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No LLM API key is configured. Please add one in Settings."
        )

    # Load the user's latest completed scan from the DB when the frontend
    # didn't send scan data itself (e.g. Dashboard has none) so questions like
    # "Summarize this scan" always have real data to answer from.
    has_scan_context = bool(req.finding_context and req.finding_context.get("type") == "repository_scan")
    latest_scan = None if has_scan_context else await _load_latest_scan_context(db, current_user.id)

    # Build context
    context_str = _build_context_prompt(req.current_page, req.finding_context, latest_scan)

    # Build system prompt
    system = ASSISTANT_SYSTEM_PROMPT
    if req.beginner_mode:
        system += "\n\n**⚠️ Beginner mode is ON** — explain everything in simple terms. Define technical terms. Use analogies. Be encouraging."
    if context_str:
        system += f"\n\n## Current Context\n{context_str}"

    # Build messages
    messages = [{"role": "system", "content": system}]

    # Include conversation history (last 10 messages)
    if req.conversation_history:
        for msg in req.conversation_history[-10:]:
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": req.message})

    try:
        client = build_llm_client(provider, llm_api_key)
        model = get_model_name(provider, current_user.llm_default_model)

        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=900,
        )

        reply = chat_completion.choices[0].message.content or "I'm sorry, I couldn't generate a response."

        # Get page-specific suggestions
        page = req.current_page or ""
        suggested = PAGE_SUGGESTIONS.get(page, DEFAULT_SUGGESTIONS)

        logger.info(f"Chat reply generated for user {current_user.id} ({len(reply)} chars)")
        return ChatResponse(reply=reply, suggested_questions=suggested)

    except Exception as e:
        logger.error(f"Chat failed for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=friendly_llm_error(provider, e)
        )


# ── Streaming SSE Endpoint ──────────────────────────────────────────────────

async def _stream_tokens(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    current_page: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 900,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted token chunks from the LLM stream."""
    try:
        client = build_llm_client(provider, api_key)
        stream = client.chat.completions.create(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                # SSE format: data: <json>\n\n
                yield f"data: {json.dumps({'token': delta.content})}\n\n"
        # Get page-specific suggestions
        suggested = PAGE_SUGGESTIONS.get(current_page or "", DEFAULT_SUGGESTIONS)
        # Signal end of stream with suggested questions
        yield f"data: {json.dumps({'done': True, 'suggested_questions': suggested})}\n\n"
    except Exception as e:
        logger.error(f"Stream error: {e}", exc_info=True)
        yield f"data: {json.dumps({'error': friendly_llm_error(provider, e)})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"


@router.post("/ask/stream")
async def chat_ask_stream(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).
    Returns tokens one by one as they're generated by the LLM.
    """
    logger.info(f"Streaming chat request from user {current_user.id}: page={req.current_page}")

    provider, llm_api_key = _resolve_llm_key(current_user)
    if not llm_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No LLM API key is configured. Please add one in Settings."
        )

    # Load the user's latest completed scan from the DB when the frontend
    # didn't send scan data itself (e.g. Dashboard has none) so questions like
    # "Summarize this scan" always have real data to answer from.
    has_scan_context = bool(req.finding_context and req.finding_context.get("type") == "repository_scan")
    latest_scan = None if has_scan_context else await _load_latest_scan_context(db, current_user.id)

    # Build context
    context_str = _build_context_prompt(req.current_page, req.finding_context, latest_scan)

    # Build system prompt
    system = ASSISTANT_SYSTEM_PROMPT
    if req.beginner_mode:
        system += "\n\n**⚠️ Beginner mode is ON** — explain everything in simple terms. Define technical terms. Use analogies. Be encouraging."
    if context_str:
        system += f"\n\n## Current Context\n{context_str}"

    # Build messages
    messages = [{"role": "system", "content": system}]
    if req.conversation_history:
        for msg in req.conversation_history[-10:]:
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": req.message})

    model = get_model_name(provider, current_user.llm_default_model)

    return StreamingResponse(
        _stream_tokens(
            provider=provider,
            api_key=llm_api_key,
            model=model,
            messages=messages,
            current_page=req.current_page,
            temperature=0.3,
            max_tokens=900,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
