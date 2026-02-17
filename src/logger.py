import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import InteractionLog
import logging

logger = logging.getLogger(__name__)


def _safe_user_id(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

async def log_interaction(
    session: AsyncSession,
    user_id: int,
    username: str,
    message_content: str,
    detected_intent: str = None,
    confidence_score: float = None,
    entities: dict = None,
    action_taken: str = None,
    response_content: str = None
):
    """
    Log a user interaction to the database for debugging and audit purposes.
    """
    try:
        log_entry = InteractionLog(
            user_id=_safe_user_id(user_id),
            username=str(username) if username is not None else None,
            message_content=message_content,
            detected_intent=detected_intent,
            confidence_score=confidence_score,
            entities_json=json.dumps(entities) if entities else None,
            action_taken=action_taken,
            response_content=response_content,
            timestamp=datetime.utcnow()
        )
        session.add(log_entry)
        await session.commit()
    except Exception as e:
        logger.error(f"Failed to log interaction: {e}")
        await session.rollback()
