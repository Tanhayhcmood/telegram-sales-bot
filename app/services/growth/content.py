import hashlib
import random
import re
from difflib import SequenceMatcher

from app.core.logging import get_logger

logger = get_logger(__name__)

ANGLES = {
    "share_post": [
        "a specific recent VPS tip shared with a relevant tech group",
        "a short server-maintenance post shared with a sysadmin community",
        "a useful Linux troubleshooting post shared with a developer group",
        "a practical hosting tip shared with a group that would value it",
    ],
    "invite_friends": [
        "a personal invitation to a friend who uses remote servers",
        "a one-to-one recommendation to someone setting up a VPS",
        "a direct invitation to a colleague interested in hosting",
        "a small, genuine invite to a friend who likes Linux tools",
    ],
    "story_status": [
        "a brief personal status about a useful server tip",
        "a low-key story recommending a practical VPS resource",
        "a short status about a lesson learned while managing servers",
        "a personal note pointing friends to a helpful hosting channel",
    ],
    "tech_quiz": [
        "a quick SSH and Linux knowledge check unlocked in the channel",
        "a short VPS troubleshooting quiz available after joining",
        "a practical server-security question unlocked by channel membership",
        "a quick hosting-cost quiz found in the channel post",
    ],
}

TASKS = {
    "share_post": "Choose one specific recent post from the channel and share it in a relevant group that allows it. Send a screenshot with the group name visible.",
    "invite_friends": "Use your personal round invite link to invite a friend who would genuinely find the channel useful. Send a screenshot of the invitation or their join confirmation.",
    "story_status": "Post a short, honest story or status recommending one useful channel resource. Send a screenshot showing the published status.",
    "tech_quiz": "Join the channel to unlock its quick VPS quiz, answer the question in the round post, then send a screenshot of your answer with the channel visible.",
}


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def normalized_text_hash(text: str) -> str:
    return hashlib.sha256(_normalized(text).encode("utf-8")).hexdigest()


def _similar(candidate: str, history: list[str]) -> bool:
    new = _normalized(candidate)
    if not new:
        return True
    for old_text in history[-60:]:
        old = _normalized(old_text)
        if not old:
            continue
        if new == old or (min(len(new), len(old)) > 60 and SequenceMatcher(None, new, old).ratio() >= 0.76):
            return True
        left, right = set(new.split()), set(old.split())
        if left and right and len(left & right) / min(len(left), len(right)) >= 0.82:
            return True
    return False


def _fallback(challenge_type: str, angle: str, username: str | None, sister: str, salt: int) -> str:
    destination = f"@{username}" if username else "the Growth bot"
    task = TASKS[challenge_type]
    openers = (
        "A quick community task for this round:",
        "Try this if it fits your day:",
        "Here is one useful action for this round:",
        "Keep it simple for this round:",
    )
    if challenge_type == "tech_quiz":
        task += " Quiz: Which is safer for remote administration, password-only SSH or SSH keys with password login disabled?"
    return f"{openers[salt % len(openers)]} {task} Send your proof privately to {destination}. {sister}".strip()


async def generate_growth_copy(challenge_type: str, angle: str, history: list[str],
                               username: str | None, sister: str) -> tuple[str, str]:
    if challenge_type not in TASKS:
        raise ValueError("Unknown Growth Challenge type")
    angle = random.choice(ANGLES[challenge_type])
    recent = "\n".join(f"- {item[:450]}" for item in history[-60:])
    destination = f"@{username}" if username else "the Growth bot"
    system = (
        "Write natural, concise English for a Telegram channel community. Sound like a person, "
        "not an advertisement. No emoji, hype, spam, false claims, or pressure. Do not add the prize, "
        "rules, time, or entry count; the publisher adds those."
    )
    for attempt in range(1, 4):
        prompt = (
            f"Write one fresh Growth Challenge for the exact task below.\nType: {challenge_type}\n"
            f"Angle: {angle}\nExact participant task: {TASKS[challenge_type]}\n"
            f"Proof goes privately to {destination}. Keep the action honest and suitable for a relevant group.\n"
            f"Natural related-channel mention to include once: {sister or 'our sister channel for server tips'}.\n"
            "Use 2-4 short sentences and stay under 420 characters. Vary the opening and sentence rhythm. "
            "For tech_quiz, include one clear quick question and its answer options, but do not disclose the correct answer. "
            "Return only the copy. Do not repeat the text or angle of these recent posts:\n"
            f"{recent or '- none'}"
        )
        try:
            from app.services.ai.engine import generate_content
            result = await generate_content(prompt, system=system, temperature=0.9)
            text = (result or "").strip().strip(chr(96)).strip()
        except Exception as exc:
            logger.warning("growth_content_ai_attempt_failed", attempt=attempt,
                           exception_type=type(exc).__name__, message=str(exc)[:160])
            continue
        if 60 <= len(text) <= 460 and not re.search(r"[\u0600-\u06FF\u0750-\u077F]", text) and not _similar(text, history):
            return text, angle
        logger.info("growth_content_regenerate", attempt=attempt, reason="similar_or_invalid")
    for salt in range(8):
        text = _fallback(challenge_type, angle, username, sister, salt)
        if not _similar(text, history):
            return text, angle
    text = _fallback(challenge_type, angle + "; new variation", username, sister, random.randrange(1000, 100000))
    return text[:460], angle


try:
    from app.services.growth import publishing as _publisher
    _publisher._hash_text = normalized_text_hash
except Exception:
    pass
