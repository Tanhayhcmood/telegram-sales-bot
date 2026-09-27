from app.services.ai.engine import generate_content
from app.services.content.templates import get_content_prompt, get_all_content_types
from app.core.logging import get_logger
from typing import Optional
import asyncio
import random

logger = get_logger(__name__)

SUPPORTED_LANGUAGES = ["en", "fa", "ar", "tr", "ru", "de", "fr", "es"]

HASHTAG_MAP = {
    "en": [
            "#VPS", "#CloudHosting", "#DedicatedServer", "#Hosting", "#Linux",
            "#DevOps", "#Server", "#WebHosting", "#SysAdmin", "#TechTips",
            "#CloudComputing", "#Cybersecurity", "#ServerManagement", "#VPSHosting",
            "#Ubuntu", "#Docker", "#Nginx", "#ServerAdmin", "#DataCenter",
            "#CloudServer", "#RootServer", "#VirtualServer", "#ITInfrastructure",
            "#NetworkSecurity", "#LinuxAdmin", "#OpenSource", "#SelfHosted",
            "#TechNews", "#ProgrammingTips", "#BackendDev",
    ],
    "fa": [
            "#VPS", "#هاستینگ_ابری", "#سرور_اختصاصی", "#هاستینگ", "#میزبانی_وب",
            "#لینوکس", "#سرور_مجازی", "#امنیت_سایبری", "#کلود", "#دواپس",
            "#ادمین_سرور", "#سرور_لینوکس", "#هاست_ارزان", "#خدمات_ابری",
            "#نتورک", "#دیتاسنتر", "#برنامه_نویسی", "#امنیت_شبکه",
    ],
    "ar": [
            "#VPS", "#استضافة_سحابية", "#خادم_مخصص", "#استضافة", "#لينكس",
            "#الخوادم", "#الأمن_السيبراني", "#تقنية_المعلومات", "#البنية_التحتية",
            "#الحوسبة_السحابية", "#ادارة_الخوادم", "#شبكات",
    ],
    "tr": [
            "#VPS", "#BulutHosting", "#DedicatedSunucu", "#Hosting", "#Linux",
            "#Sibergüvenlik", "#Sunucu", "#WebHosting", "#BulutBilişim",
            "#DevOps", "#SunucuYönetimi", "#VPSHosting",
    ],
    "ru": [
            "#VPS", "#ОблачныйХостинг", "#ВыделенныйСервер", "#Хостинг", "#Linux",
            "#ИнформационныеТехнологии", "#Кибербезопасность", "#ОблачныеВычисления",
            "#АдминистрированиеСерверов", "#DevOps",
    ],
    "de": [
            "#VPS", "#CloudHosting", "#DedicatedServer", "#Hosting", "#Linux",
            "#Cybersicherheit", "#CloudComputing", "#Serveradministration",
            "#DevOps", "#Rechenzentrum",
    ],
    "fr": [
            "#VPS", "#HébergementCloud", "#ServeurDédié", "#Hébergement", "#Linux",
            "#CybersécuritéIT", "#InfrastructureCloud", "#DevOps", "#Serveur",
            "#AdministrationServeur",
    ],
    "es": [
            "#VPS", "#AlojamientoCloud", "#ServidorDedicado", "#Hosting", "#Linux",
            "#CiberseguridadIT", "#ComputaciónEnLaNube", "#DevOps", "#ServidorLinux",
            "#AdministraciónServidor",
    ],
}

TOPIC_HASHTAG_MAP = {
    "docker": ["#Docker", "#DockerCompose", "#ContainerTech", "#Kubernetes"],
    "ssh": ["#SSH", "#SecureShell", "#LinuxSecurity", "#ServerAccess"],
    "security": ["#CyberSecurity", "#ServerSecurity", "#Firewall", "#SecureHosting"],
    "nginx": ["#Nginx", "#WebServer", "#ReverseProxy", "#LoadBalancing"],
    "backup": ["#DataBackup", "#DisasterRecovery", "#ServerBackup", "#DataProtection"],
    "free": ["#FreeVPS", "#FreeHosting", "#FreeServer", "#FreeRDP"],
    "rdp": ["#RDP", "#RemoteDesktop", "#WindowsServer", "#FreeRDP"],
    "windows": ["#WindowsServer", "#RDP", "#WindowsVPS", "#WinServer"],
    "ubuntu": ["#Ubuntu", "#Debian", "#LinuxServer", "#OpenSource"],
    "vps": ["#VPS", "#VirtualServer", "#CloudVPS", "#VPSHosting"],
    "cloud": ["#CloudComputing", "#CloudServer", "#CloudHosting"],
    "speed": ["#ServerPerformance", "#FastHosting", "#NVMeSSD", "#LowLatency"],
    "ssl": ["#SSL", "#HTTPS", "#FreeCertificate", "#WebSecurity"],
    "monitoring": ["#ServerMonitoring", "#Uptime", "#DevOps", "#AlertSystem"],
    "vpn": ["#VPN", "#PrivateNetwork", "#VPNServer", "#PrivacyOnline"],
    "crypto": ["#Crypto", "#CryptoNode", "#BlockchainHosting", "#DeFiServer"],
    "game": ["#GameServer", "#GameHosting", "#LowLatencyServer", "#GamingVPS"],
    "wordpress": ["#WordPress", "#CMS", "#WebHosting", "#WPServer"],
    "database": ["#Database", "#MySQL", "#PostgreSQL", "#DBServer"],
    "python": ["#Python", "#PythonServer", "#AutomationBot", "#ScriptServer"],
}



async def generate_post(
    content_type: str,
    topic: str,
    language: str = "en",
    include_hashtags: bool = True,
    style_hint: str = "",
    forbidden_angles: list[str] | None = None,
    unique_seed: int | None = None,
) -> str:
    # Posts are always in English — enforce it regardless of the caller's language arg.
    language = "en"

    prompt = get_content_prompt(
            content_type, topic, language,
            style_hint=style_hint,
            forbidden_angles=forbidden_angles or [],
            unique_seed=unique_seed,
    )
    try:
            content = await generate_content(prompt)
            if include_hashtags:
                    tags = _pick_hashtags(topic, language, count=6)
                    if tags:
                            content = f"{content}\n\n{' '.join(tags)}"


            logger.info("post_generated", content_type=content_type,
                                    language=language, topic=topic)
            return content
    except Exception as e:
            logger.error("post_generation_failed", error=str(e), topic=topic)
            raise


async def generate_multilingual_post(
    content_type: str,
    topic: str,
    languages: list[str] | None = None,
    include_hashtags: bool = True,
) -> dict[str, str]:
    # All posts are English-only
    languages = ["en"]

    tasks = {
            lang: generate_post(content_type, topic, lang, include_hashtags)
            for lang in languages
    }
    results = {}
    completed = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for lang, result in zip(tasks.keys(), completed):
            if isinstance(result, Exception):
                    logger.error("multilingual_post_failed", lang=lang, error=str(result))
                    results[lang] = f"[Generation failed for {lang}]"
            else:
                    results[lang] = result
    return results


async def generate_post_variants(
    content_type: str,
    topic: str,
    language: str = "en",
    count: int = 2,
) -> list[str]:
    tasks = [
            generate_post(content_type, topic, "en", include_hashtags=False)
            for _ in range(count)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]


def _pick_hashtags(topic: str, language: str, count: int = 6) -> list[str]:
    base = HASHTAG_MAP.get(language, HASHTAG_MAP["en"])
    topic_lower = topic.lower()

    topic_specific = []
    for keyword, tags in TOPIC_HASHTAG_MAP.items():
            if keyword in topic_lower:
                    topic_specific.extend(tags)

    topic_specific = list(set(topic_specific))
    random.shuffle(topic_specific)

    topic_word_tags = []
    for word in topic.split():
            if len(word) > 4 and word.isalpha():
                    tag = f"#{word.capitalize()}"
                    if tag not in base and tag not in topic_specific:
                            topic_word_tags.append(tag)

    shuffled_base = random.sample(base, min(len(base), count))
    combined = list(dict.fromkeys(
            topic_specific[:2] + topic_word_tags[:1] + shuffled_base
    ))
    return combined[:count]


def get_supported_languages() -> list[str]:
    return SUPPORTED_LANGUAGES


def get_content_types() -> list[str]:
    return get_all_content_types()

