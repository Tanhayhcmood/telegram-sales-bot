from app.services.ai.engine import generate_reply
from app.core.logging import get_logger
import json
import re

logger = get_logger(__name__)

CLASSIFIER_PROMPT = """Analyze the following customer message carefully and extract structured data.

Return ONLY a valid JSON object with these exact keys:
{
  "intent": one of [sales, support, inquiry, complaint, spam, greeting, objection, negotiation, comparison, other],
  "service_interest": one of [vps, cloud, dedicated, domain, ssl, backup, general, none],
  "budget_mentioned": true/false,
  "budget_min": number or null (USD per month),
  "budget_max": number or null (USD per month),
  "urgency": one of [critical, high, medium, low],
  "sentiment": one of [very_positive, positive, neutral, negative, very_negative],
  "purchase_readiness": one of [ready_to_buy, considering, exploring, not_interested],
  "tech_level": one of [beginner, intermediate, expert, unknown],
  "use_case": string or null (e.g. "wordpress", "game server", "api backend", "ecommerce"),
  "team_size": string or null (number of users, players, or people),
  "competitor_mentioned": string or null,
  "objection_type": one of [price, trust, features, timing, support, none],
  "language_detected": string (2-letter code),
  "requires_human": true/false
}

Do not infer use_case, budget, or team_size from a plan name, a price question,
or a comparison question. Return null/false when the customer did not state
that fact explicitly in this message. No explanation. Only JSON."""


async def classify_message(text: str, language: str = "en") -> dict:
    try:
        messages = [{"role": "user", "content": f"Message: {text}"}]
        result, _ = await generate_reply(
            messages,
            CLASSIFIER_PROMPT,
            temperature=0.0,
            max_tokens=300,
        )
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return _normalize(data)
    except Exception as e:
        logger.warning("classification_failed", error=str(e))
    return _default_classification()


def _normalize(data: dict) -> dict:
    valid_intents = {"sales", "support", "inquiry", "complaint", "spam", "greeting", "objection", "negotiation", "comparison", "other"}
    valid_services = {"vps", "cloud", "dedicated", "domain", "ssl", "backup", "general", "none"}
    valid_urgency = {"critical", "high", "medium", "low"}
    valid_sentiment = {"very_positive", "positive", "neutral", "negative", "very_negative"}
    valid_readiness = {"ready_to_buy", "considering", "exploring", "not_interested"}
    valid_tech = {"beginner", "intermediate", "expert", "unknown"}
    valid_objection = {"price", "trust", "features", "timing", "support", "none"}

    return {
        "intent": data.get("intent", "inquiry") if data.get("intent") in valid_intents else "inquiry",
        "service_interest": data.get("service_interest", "general") if data.get("service_interest") in valid_services else "general",
        "budget_mentioned": bool(data.get("budget_mentioned", False)),
        "budget_min": _to_float(data.get("budget_min")),
        "budget_max": _to_float(data.get("budget_max")),
        "urgency": data.get("urgency", "low") if data.get("urgency") in valid_urgency else "low",
        "sentiment": data.get("sentiment", "neutral") if data.get("sentiment") in valid_sentiment else "neutral",
        "purchase_readiness": data.get("purchase_readiness", "exploring") if data.get("purchase_readiness") in valid_readiness else "exploring",
        "tech_level": data.get("tech_level", "unknown") if data.get("tech_level") in valid_tech else "unknown",
        "use_case": data.get("use_case"),
        "team_size": data.get("team_size"),
        "competitor_mentioned": data.get("competitor_mentioned"),
        "objection_type": data.get("objection_type", "none") if data.get("objection_type") in valid_objection else "none",
        "language_detected": data.get("language_detected", "en"),
        "requires_human": bool(data.get("requires_human", False)),
    }


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _default_classification() -> dict:
    return {
        "intent": "inquiry",
        "service_interest": "general",
        "budget_mentioned": False,
        "budget_min": None,
        "budget_max": None,
        "urgency": "low",
        "sentiment": "neutral",
        "purchase_readiness": "exploring",
        "tech_level": "unknown",
        "use_case": None,
        "team_size": None,
        "competitor_mentioned": None,
        "objection_type": "none",
        "language_detected": "en",
        "requires_human": False,
    }
