from app.db.session import AsyncSessionLocal
from app.services.learning.analyzer import analyze_successful_conversations, analyze_failed_conversations
from app.services.learning.trainer import get_learning_stats
from app.core.logging import get_logger

logger = get_logger(__name__)


async def task_analyze_conversations(ctx) -> dict:
    try:
        async with AsyncSessionLocal() as session:
            count = await analyze_successful_conversations(session, limit=20)
            failed_patterns = await analyze_failed_conversations(session, limit=5)
            stats = await get_learning_stats(session)

        if count > 0:
            logger.info("learning_analysis_done", samples_created=count, stats=stats)

        if stats.get("ready_for_finetuning"):
            logger.info("finetuning_data_ready", high_quality=stats.get("high_quality"))

        return {
            "status": "ok",
            "samples_created": count,
            "total_approved": stats.get("approved", 0),
            "high_quality": stats.get("high_quality", 0),
            "failed_patterns_analyzed": len(failed_patterns),
            "ready_for_finetuning": stats.get("ready_for_finetuning", False),
        }
    except Exception as e:
        logger.error("learning_task_failed", error=str(e))
        return {"status": "error", "error": str(e)}
