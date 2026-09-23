import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import AuditLog
from app.database.database import SessionLocal
from app.utils.logger import get_logger

logger = get_logger("audit_logger")

async def log_audit_event(
    db: AsyncSession,
    action: str,
    user_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None
) -> AuditLog | None:
    """Log an event in the audit_logs table and print to application logs."""
    try:
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            details=details,
            ip_address=ip_address
        )
        db.add(log_entry)
        logger.info(f"[Audit Log] User={user_id} Action={action} Details={details} IP={ip_address}")
        return log_entry
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}", exc_info=True)
        return None

def log_audit_event_sync(
    action: str,
    user_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None
):
    """Log an event in audit_logs synchronously (e.g. from Celery tasks)."""
    db = SessionLocal()
    try:
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            details=details,
            ip_address=ip_address
        )
        db.add(log_entry)
        db.commit()
        logger.info(f"[Audit Log - Sync] User={user_id} Action={action} Details={details} IP={ip_address}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to log audit event synchronously: {e}", exc_info=True)
    finally:
        db.close()
