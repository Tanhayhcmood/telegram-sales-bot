from app.services.ai.engine import generate_reply
from app.core.logging import get_logger
from typing import List

logger = get_logger(__name__)

SUMMARIZE_PROMPT = """Summarize this customer conversation in 2-3 sentences focusing on:
- Customer's main need, use case, and service interest
- Key facts discussed (budget, requirements, objections)
- Outcome and recommended next steps
Be concise, factual, and sales-oriented."""

QUALITY_PROMPT = """Rate this AI sales conversation on a scale of 0.0 to 1.0.
Criteria:
- Did the AI understand the customer's need? (0.3)
- Was the recommendation relevant and accurate? (0.3)
- Was the tone professional and non-pushy? (0.2)
- Did it handle objections well if any? (0.2)

Return ONLY a JSON: {"score": <float>, "reason": "<one sentence>"}"""


async def summarize_conversation(messages: List[dict]) -> str:
    if not messages:
        return ""
    try:
        summary, _ = await generate_reply(messages, SUMMARIZE_PROMPT, temperature=0.2, max_tokens=200)
        return summary.strip()
    except Exception as e:
        logger.error("summarization_failed", error=str(e))
        return ""


async def score_conversation_quality(messages: List[dict]) -> tuple[float, str]:
    if len(messages) < 4:
        return 0.5, "Too short to evaluate"
    try:
        import json, re
        result, _ = await generate_reply(messages, QUALITY_PROMPT, temperature=0.1, max_tokens=100)
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            score = float(data.get("score", 0.5))
            reason = data.get("reason", "")
            return min(max(score, 0.0), 1.0), reason
    except Exception as e:
        logger.warning("quality_scoring_failed", error=str(e))
    return 0.5, "Scoring failed"
