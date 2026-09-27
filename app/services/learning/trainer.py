from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.admin import LearningSample
from app.core.logging import get_logger
import json
from pathlib import Path
from datetime import datetime

logger = get_logger(__name__)

TRAINING_DATA_DIR = Path("data/training")


async def export_approved_samples(session: AsyncSession, min_quality: float = 0.7) -> str:
    TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)

    result = await session.execute(
        select(LearningSample).where(
            LearningSample.is_approved == True,
            LearningSample.quality_score >= min_quality,
        ).order_by(LearningSample.quality_score.desc())
    )
    samples = result.scalars().all()

    if not samples:
        logger.info("no_approved_samples_for_export")
        return ""

    training_data = []
    for sample in samples:
        training_data.append({
            "messages": [
                {"role": "user", "content": sample.prompt},
                {"role": "assistant", "content": sample.response},
            ],
            "quality_score": sample.quality_score,
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = TRAINING_DATA_DIR / f"training_{timestamp}.jsonl"

    with open(output_path, "w", encoding="utf-8") as f:
        for item in training_data:
            entry = {"messages": item["messages"]}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    stats_path = TRAINING_DATA_DIR / f"training_{timestamp}_stats.json"
    with open(stats_path, "w") as f:
        json.dump({
            "exported_at": timestamp,
            "total_samples": len(training_data),
            "min_quality": min_quality,
            "avg_quality": sum(s.quality_score or 0 for s in samples) / len(samples),
        }, f, indent=2)

    logger.info("training_data_exported", path=str(output_path), count=len(training_data))
    return str(output_path)


async def get_learning_stats(session: AsyncSession) -> dict:
    result = await session.execute(select(LearningSample))
    all_samples = result.scalars().all()

    approved = [s for s in all_samples if s.is_approved]
    pending = [s for s in all_samples if not s.is_approved]
    high_quality = [s for s in approved if (s.quality_score or 0) >= 0.8]

    avg_quality = sum(s.quality_score or 0 for s in approved) / len(approved) if approved else 0

    return {
        "total": len(all_samples),
        "approved": len(approved),
        "pending_review": len(pending),
        "high_quality": len(high_quality),
        "avg_quality": round(avg_quality, 3),
        "ready_for_finetuning": len(high_quality) >= 10,
    }


async def approve_sample(session: AsyncSession, sample_id) -> bool:
    result = await session.execute(select(LearningSample).where(LearningSample.id == sample_id))
    sample = result.scalar_one_or_none()
    if sample:
        sample.is_approved = True
        await session.commit()
        return True
    return False
