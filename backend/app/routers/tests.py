from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from app.database.database import get_async_db
from app.models.models import User, TestSuggestion, Analysis, Repository, SecurityFinding, CodeSmell
from app.schemas.schemas import TestSuggestionOut
from app.auth.security import get_current_user
from app.auth.encryption import encryptor
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("tests_router")

router = APIRouter(prefix="/tests", tags=["Test Generation"])

@router.get("/analysis/{analysis_id}", response_model=List[TestSuggestionOut])
async def get_test_suggestions(
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Verify user access
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or permission denied."
        )
        
    findings_res = await db.execute(
        select(TestSuggestion).where(TestSuggestion.analysis_id == analysis_id)
    )
    return findings_res.scalars().all()


@router.post("/regenerate/{analysis_id}")
async def regenerate_test_suggestions(
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Regenerate test suggestions for a completed analysis using the LLM.
    Reads the first SecurityFinding or CodeSmell to get representative code,
    then runs the test generator and updates the stored suggestion.
    """
    logger.info(f"User {current_user.id} requested test regeneration for analysis: {analysis_id}")

    # Verify ownership
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if analysis.status != "completed":
        raise HTTPException(status_code=400, detail="Analysis must be completed before regenerating tests.")

    # Resolve the user's LLM provider and API key
    provider = (current_user.llm_default_provider or "groq").lower().strip()
    key_map = {
        "groq": current_user.groq_api_key_encrypted,
        "openai": current_user.openai_api_key_encrypted,
        "anthropic": current_user.claude_api_key_encrypted,
        "claude": current_user.claude_api_key_encrypted,
        "gemini": current_user.gemini_api_key_encrypted,
        "openrouter": current_user.openrouter_api_key_encrypted,
    }
    env_map = {
        "groq": settings.GROQ_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
        "claude": settings.ANTHROPIC_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
    }
    enc_key = key_map.get(provider)
    llm_api_key = encryptor.decrypt(enc_key) if enc_key else env_map.get(provider, "")
    if not llm_api_key:
        provider = "groq"
        groq_enc = current_user.groq_api_key_encrypted
        llm_api_key = encryptor.decrypt(groq_enc) if groq_enc else settings.GROQ_API_KEY
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="No LLM API key configured. Add one in Settings.")

    # Find a code sample from the first security finding or code smell
    code_sample = ""
    sample_file = ""
    sample_lang = "Unknown"
    found = await db.execute(
        select(SecurityFinding).where(SecurityFinding.analysis_id == analysis_id)
    )
    finding = found.scalars().first()
    if finding and finding.before_code:
        code_sample = finding.before_code
        sample_file = finding.file
        ext = sample_file.split(".")[-1].lower() if "." in sample_file else ""
        lang_map = {"py": "Python", "js": "JavaScript", "ts": "TypeScript", "java": "Java",
                     "go": "Go", "rb": "Ruby", "cs": "C#", "php": "PHP", "rs": "Rust"}
        sample_lang = lang_map.get(ext, "Python")
    else:
        found_smell = await db.execute(
            select(CodeSmell).where(CodeSmell.analysis_id == analysis_id)
        )
        smell = found_smell.scalars().first()
        if smell and smell.before_code:
            code_sample = smell.before_code
            sample_file = smell.file

    if not code_sample:
        raise HTTPException(status_code=400, detail="No code samples found in this analysis to generate tests from.")

    # Generate tests via LLM
    from app.services.llm_client import build_llm_client
    client = build_llm_client(provider, llm_api_key)
    from app.services.test_generator import generate_tests
    result_text = generate_tests(client, sample_file, code_sample, sample_lang)

    # Update or create the TestSuggestion record
    existing = await db.execute(
        select(TestSuggestion).where(
            (TestSuggestion.analysis_id == analysis_id) & (TestSuggestion.file == "combined_suggestions")
        )
    )
    existing_sugg = existing.scalars().first()
    if existing_sugg:
        existing_sugg.content = result_text
        existing_sugg.file = sample_file
        db.add(existing_sugg)
    else:
        new_sugg = TestSuggestion(
            analysis_id=analysis_id,
            file=sample_file,
            content=result_text
        )
        db.add(new_sugg)
    await db.commit()

    logger.info(f"Test suggestions regenerated successfully for analysis {analysis_id}")
    return {
        "file": sample_file,
        "content": result_text,
        "message": "Test suggestions regenerated successfully."
    }
