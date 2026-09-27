from typing import Union
import uuid


class CacheKeys:
    RATE_LIMIT_MINUTE = "rate_limit:minute:{user_id}"
    RATE_LIMIT_HOUR = "rate_limit:hour:{user_id}"
    CUSTOMER_PROFILE = "customer:{telegram_id}"
    CUSTOMER_MEMORY = "customer_memory:{customer_id}"
    CONVERSATION_ACTIVE = "conversation:active:{account_id}:{telegram_id}"
    CONVERSATION_HISTORY = "conversation:history:{conversation_id}"
    BLACKLIST = "blacklist:{telegram_id}"
    ACCOUNT_STATUS = "account:status:{account_id}"
    SYSTEM_METRICS = "system:metrics"
    AI_RESPONSE_CACHE = "ai:response:{hash}"
    LANGUAGE_DETECTION = "lang:{text_hash}"
    POST_SCHEDULED = "post:scheduled"
    CHANNEL_STATUS = "channel:status:{channel_id}"
    ADMIN_SESSION = "admin:session:{telegram_id}"
    SPAM_SCORE = "spam:score:{user_id}"
    DAILY_STATS = "stats:daily:{date}"
    LEAD_ACTIVE = "lead:active:{customer_id}"

    @staticmethod
    def rate_minute(user_id: int) -> str:
        return f"rate_limit:minute:{user_id}"

    @staticmethod
    def rate_hour(user_id: int) -> str:
        return f"rate_limit:hour:{user_id}"

    @staticmethod
    def customer(telegram_id: int) -> str:
        return f"customer:{telegram_id}"

    @staticmethod
    def conversation_active(account_id: Union[str, uuid.UUID], telegram_id: int) -> str:
        return f"conversation:active:{account_id}:{telegram_id}"

    @staticmethod
    def blacklist(telegram_id: int) -> str:
        return f"blacklist:{telegram_id}"

    @staticmethod
    def spam_score(user_id: int) -> str:
        return f"spam:score:{user_id}"

    @staticmethod
    def daily_stats(date: str) -> str:
        return f"stats:daily:{date}"
