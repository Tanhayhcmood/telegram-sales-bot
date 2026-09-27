from app.core.logging import get_logger

logger = get_logger(__name__)

def is_pricing_request(text: str) -> bool:
    """Return whether a customer is directly asking about plans or prices."""
    normalized = " ".join(text.casefold().split())
    pricing_terms = (
        "price",
        "pricing",
        "cost",
        "how much",
        "rate",
        "plan price",
        "قیمت",
        "هزینه",
        "تعرفه",
        "پلن",
        "پلان",
        "چنده",
        "چندن",
        "چقدره",
        "چقدر",
        "چند میشه",
        "سعر",
        "أسعار",
        "fiyat",
        "ücret",
        "цена",
        "стоимость",
        "prix",
        "precio",
    )
    return any(term in normalized for term in pricing_terms)

PLANS = {
    "vps": [
        {
            "name": "ENTRY LEVEL",
            "price": 11,
            "original_price": 16,
            "cpu": 4,
            "ram": 8,
            "disk": 120,
            "bandwidth": "1 Gbps",
            "tier": "Entry Level",
            "best_for": [
                "personal", "testing", "small blog", "dev environment", "bot",
                "script", "light project",
            ],
        },
        {
            "name": "POWER",
            "price": 20,
            "original_price": 28,
            "cpu": 6,
            "ram": 16,
            "disk": 250,
            "bandwidth": "2 Gbps",
            "tier": "Standard",
            "best_for": [
                "wordpress", "small website", "small api", "panel", "cpanel",
                "directadmin", "ecommerce", "medium traffic", "nodejs app",
                "django", "laravel", "medium game server", "several bots",
            ],
        },
        {
            "name": "ELITE",
            "price": 31,
            "original_price": 45,
            "cpu": 8,
            "ram": 32,
            "disk": 500,
            "bandwidth": "2 Gbps",
            "tier": "Advanced",
            "best_for": [
                "shop", "store", "woocommerce", "magento", "react", "next.js",
                "high traffic", "multiple apps", "busy game server",
                "public game server", "saas", "telegram bot heavy", "heavy processing",
            ],
        },
        {
            "name": "ULTRA",
            "price": None,
            "original_price": None,
            "cpu": 12,
            "ram": 64,
            "disk": 1000,
            "bandwidth": "5 Gbps",
            "tier": "Highest",
            "best_for": ["professional", "high traffic", "large scale", "enterprise"],
        },
    ],
    "cloud": [
        {
            "name": "Cloud Starter",
            "price": 10,
            "cpu": 2,
            "ram": 4,
            "disk": 100,
            "bandwidth": "10TB",
            "best_for": ["startups", "auto-scaling apps", "microservices small", "staging"],
        },
        {
            "name": "Cloud Business",
            "price": 35,
            "cpu": 8,
            "ram": 16,
            "disk": 300,
            "bandwidth": "20TB",
            "best_for": [
                "growing business", "high availability", "ecommerce enterprise",
                "saas platform", "crm", "erp small",
            ],
        },
        {
            "name": "Cloud Enterprise",
            "price": 100,
            "cpu": 32,
            "ram": 64,
            "disk": 700,
            "bandwidth": "Unlimited",
            "best_for": ["large scale", "enterprise apps", "big data", "kubernetes", "docker swarm"],
        },
    ],
    "dedicated": [
        {
            "name": "Dedicated Entry",
            "price": 60,
            "cpu": "Intel Xeon E3 4-core / 8-thread",
            "ram": 32,
            "disk": "2×500GB SSD",
            "bandwidth": "Unlimited",
            "best_for": ["database server", "game server", "bare metal performance", "proxy", "vpn server"],
        },
        {
            "name": "Dedicated Business",
            "price": 110,
            "cpu": "Intel Xeon E5 8-core / 16-thread",
            "ram": 64,
            "disk": "2×1TB NVMe",
            "bandwidth": "Unlimited",
            "best_for": [
                "high performance web", "video streaming", "fintech",
                "large database", "heavy api", "render farm small",
            ],
        },
        {
            "name": "Dedicated Enterprise",
            "price": 200,
            "cpu": "Dual Intel Xeon 16-core / 32-thread",
            "ram": 128,
            "disk": "4×2TB NVMe",
            "bandwidth": "Unlimited",
            "best_for": [
                "machine learning", "ai training", "big data analytics",
                "enterprise erp", "massive scale", "video encoding", "render farm",
            ],
        },
    ],
}

USE_CASE_SERVICE_MAP = {
    # VPS use cases
    "wordpress": "vps",
    "blog": "vps",
    "personal": "vps",
    "testing": "vps",
    "dev": "vps",
    "vpn": "vps",
    "bot": "vps",
    "script": "vps",
    "panel": "vps",
    "cpanel": "vps",
    "directadmin": "vps",
    "woocommerce": "vps",
    "shop": "vps",
    "store": "vps",
    # Cloud use cases
    "ecommerce": "cloud",
    "saas": "cloud",
    "startup": "cloud",
    "microservices": "cloud",
    "kubernetes": "cloud",
    "docker": "cloud",
    "crm": "cloud",
    "erp": "cloud",
    "staging": "cloud",
    # Dedicated use cases
    "machine learning": "dedicated",
    "ml": "dedicated",
    "ai": "dedicated",
    "game server": "dedicated",
    "database": "dedicated",
    "streaming": "dedicated",
    "fintech": "dedicated",
    "mining": "dedicated",
    "render": "dedicated",
    "encoding": "dedicated",
    "proxy": "dedicated",
}

COMPARISON_LANGS = {
    "en": {
        "header": "📦 *Plans picked for your use case:*",
        "footer": "💬 Questions? Want a custom config? Just say the word.",
        "month": "mo",
        "cpu": "CPU",
        "ram": "RAM",
        "disk": "Storage",
        "bw": "Bandwidth",
        "best": "Ideal for",
    },
    "fa": {
        "header": "📦 *پلن‌های مناسب برای کار شما:*",
        "footer": "💬 سوالی داری؟ می‌خوای تنظیم سفارشی؟ بگو تا حلش کنیم.",
        "month": "ماه",
        "cpu": "پردازنده",
        "ram": "RAM",
        "disk": "فضا",
        "bw": "پهنای باند",
        "best": "مناسب برای",
    },
    "ar": {
        "header": "📦 *الخطط المناسبة لاحتياجك:*",
        "footer": "💬 أي سؤال؟ تريد إعداداً خاصاً؟ قل لي.",
        "month": "شهر",
        "cpu": "المعالج",
        "ram": "الذاكرة",
        "disk": "التخزين",
        "bw": "النطاق",
        "best": "مثالي لـ",
    },
    "tr": {
        "header": "📦 *Kullanımınıza özel planlar:*",
        "footer": "💬 Soru var mı? Özel yapılandırma ister misiniz? Söyleyin.",
        "month": "ay",
        "cpu": "İşlemci",
        "ram": "RAM",
        "disk": "Depolama",
        "bw": "Bant Genişliği",
        "best": "İdeal kullanım",
    },
    "ru": {
        "header": "📦 *Планы под ваш сценарий:*",
        "footer": "💬 Вопросы? Нужна кастомная конфигурация? Пишите.",
        "month": "мес",
        "cpu": "ЦПУ",
        "ram": "RAM",
        "disk": "Диск",
        "bw": "Трафик",
        "best": "Идеально для",
    },
}


def recommend_plans(
    service_type: str,
    budget_max: float = None,
    requirements: dict = None,
) -> list[dict]:
    requirements = requirements or {}
    use_case = (requirements.get("use_case") or "").lower()

    if use_case and service_type in ("general", "none"):
        for keyword, svc in USE_CASE_SERVICE_MAP.items():
            if keyword in use_case or use_case in keyword:
                service_type = svc
                break

    plans = PLANS.get(service_type, [])
    if not plans:
        plans = PLANS["vps"]

    if budget_max:
        affordable = [p for p in plans if isinstance(p.get("price"), (int, float)) and p["price"] <= budget_max]
        if affordable:
            plans = affordable

    if use_case:
        def use_case_score(plan):
            best_for = plan.get("best_for", [])
            return sum(1 for kw in best_for if kw in use_case or use_case in kw)
        plans_with_scores = sorted(plans, key=use_case_score, reverse=True)
        if plans_with_scores:
            plans = plans_with_scores

    tech_level = requirements.get("tech_level", "unknown")
    if tech_level == "beginner" and len(plans) > 1:
        plans = plans[:2]
    elif tech_level == "expert":
        plans = plans[-3:]

    # Return max 2 most relevant plans — cleaner, less overwhelming
    return plans[:2]


def format_plan_recommendation(plans: list[dict], language: str = "en") -> str:
    if not plans:
        return ""

    lang_data = COMPARISON_LANGS.get(language, COMPARISON_LANGS["en"])

    lines = [lang_data["header"], ""]
    for i, plan in enumerate(plans, 1):
        price = plan.get("price", "N/A")
        price_str = f"${price}/{lang_data['month']}" if isinstance(price, (int, float)) else str(price)
        lines.append(f"**{i}. {plan['name']}** — {price_str}")
        lines.append(f"   ├ {lang_data['cpu']}: {plan.get('cpu', 'N/A')}")
        lines.append(f"   ├ {lang_data['ram']}: {plan.get('ram', 'N/A')} GB")
        disk_val = plan.get('disk', 'N/A')
        disk_str = f"{disk_val} GB" if isinstance(disk_val, (int, float)) else str(disk_val)
        lines.append(f"   ├ {lang_data['disk']}: {disk_str}")
        lines.append(f"   └ {lang_data['bw']}: {plan.get('bandwidth', 'N/A')}")
        best_for = plan.get("best_for", [])
        if best_for:
            lines.append(f"   ✦ {lang_data['best']}: {', '.join(best_for[:3])}")
        lines.append("")

    lines.append(lang_data["footer"])
    return "\n".join(lines)


def get_all_plans_summary() -> dict:
    return {svc: [{"name": p["name"], "price": p["price"]} for p in plans] for svc, plans in PLANS.items()}
