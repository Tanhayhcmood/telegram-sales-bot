import json
import random
import re
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Topic pool — 30 diverse real-world angles ────────────────────────────────
# Scheduler picks from this list so every 10-hour slot covers a different angle.
CHALLENGE_TOPIC_POOL = [
    "SSH hardening gone wrong: a brute-force attack story and the one config that stopped it",
    "VPS cost optimization: the billing line most people ignore that costs 3x the compute",
    "Docker on VPS at 3 AM: a deployment decision that brought the server back from the dead",
    "DDoS mitigation decision: network-layer vs application-layer protection under real attack",
    "Backup strategy failure: the sysadmin who discovered their backups were empty for 3 months",
    "Firewall misconfiguration: the iptables rule that locked everyone out of production",
    "Linux file system showdown: ext4 vs XFS vs ZFS for a high-traffic VPS database",
    "RDP vs SSH vs VNC: which remote access method actually wins for each real use case",
    "Server monitoring tool choice: Grafana vs Netdata vs Zabbix vs Uptime Robot for a VPS",
    "SSL/TLS certificate trap: Let's Encrypt rate limit that killed HTTPS for a week",
    "Bandwidth billing shock: the AWS egress cost that produced an $800 bill for a small app",
    "IPv6-only VPS: the surprising cost saving and the one service that broke completely",
    "Cron job disaster: the scheduled script that silently corrupted production data for days",
    "Kernel panic during live upgrade: what actually recovers a VPS with no physical access",
    "Cloud provider benchmark: Hetzner vs DigitalOcean vs Vultr under identical load test",
    "PostgreSQL tuning: the single config knob that doubled query speed on a 2 GB VPS",
    "Nginx vs Caddy vs Apache: which proxy survives a sudden 10x traffic spike first",
    "Swap space trap: why adding 4 GB swap to a 2 GB VPS made it 10x slower under load",
    "Reverse proxy + Cloudflare misconfiguration: the setting that blocked real users but not bots",
    "systemd unit file mistake: one wrong line that prevents the entire server from booting",
    "NTP vs chrony on VPS: why clock drift caused payment processing failures at midnight",
    "OOM Killer mystery: the Linux process terminator that killed an app silently for weeks",
    "Snapshot vs incremental backup: the difference that determines recovery time after ransomware",
    "GPU VPS economics: when renting cloud GPU is cheaper than buying hardware for AI workloads",
    "Anycast routing on bare metal: the network trick that cut global latency by 200ms",
    "Port 80/443 block by ISP: the invisible restriction that breaks web hosting unexpectedly",
    "Shared vs VPS vs dedicated: the exact traffic/load threshold that tells you to upgrade",
    "Wireguard vs OpenVPN on VPS: the performance gap that surprises most Linux admins",
    "Let's Encrypt wildcard cert: why the DNS-01 challenge is required and most people fail it",
    "RAID-1 on VPS: when it protects you, when it's pure overhead, and the trap beginners fall into",
]

# ── High-quality fallback challenges (used when AI is unavailable) ────────────
_FALLBACK_POOL = [
    {
        "title": "The 3 AM DDoS Survival Decision",
        "question": (
            "Your VPS is under a 10 Gbps volumetric DDoS attack. The server is completely unreachable. "
            "Every port is timing out and SSH is dead. You have 10 minutes before your SLA breach. "
            "Which single action gives you the fastest path back to service?"
        ),
        "learning_note": (
            "Null-routing (blackholing) the attacked IP at the datacenter level stops inbound traffic before it "
            "reaches your server — usually within 60 seconds. Application-layer tools like fail2ban or iptables "
            "can't help when the upstream pipe is already saturated. Always ask your provider for null-route access "
            "BEFORE an attack happens."
        ),
        "answers": [
            "Request the datacenter to null-route (blackhole) the attacked IP immediately",
            "Restart Nginx to clear the saturated connection queue",
            "Add mass iptables DROP rules targeting the attacking IPs",
            "Reboot the VPS to flush all network state and connections",
        ],
        "correct_answer": 0,
        "reward": "Top 3 fastest correct answers win 1 month VPS upgrade — announced in 4 hours",
        "hashtags": ["#DDoS", "#VPS", "#ServerSecurity", "#SysAdmin", "#UpgradeTeam"],
        "seo_keywords": ["DDoS protection VPS", "null route attack", "volumetric DDoS mitigation"],
    },
    {
        "title": "The SSH Lockout at 2 AM",
        "question": (
            "You SSH into a production server, edit /etc/ssh/sshd_config to change the port from 22 to 2222 "
            "and add 'AllowUsers deploy', then run 'systemctl restart sshd'. "
            "You disconnect to test — and can't reconnect. The server is live, serving real users. "
            "What is your ONLY way back in without wiping data?"
        ),
        "learning_note": (
            "VPS providers offer out-of-band console access (VNC console, IPMI, or rescue mode) that "
            "bypasses the OS network stack entirely. This is the one path that works even when SSH is broken. "
            "Golden rule: always test config changes in a SECOND open session before closing the first one."
        ),
        "answers": [
            "Use the VPS provider's web console or rescue mode — it bypasses the OS",
            "Wait 15 minutes for the SSH daemon to auto-reset its configuration",
            "Reinstall the OS and restore from the most recent snapshot",
            "Ask your ISP to remotely unblock port 2222 on the upstream router",
        ],
        "correct_answer": 0,
        "reward": "First 3 correct responders win a free month of Premium RDP access",
        "hashtags": ["#SSH", "#VPS", "#SysAdmin", "#LinuxTips", "#UpgradeTeam"],
        "seo_keywords": ["SSH locked out VPS", "rescue mode VPS", "SSHD config mistake recovery"],
    },
    {
        "title": "The Silent OOM Killer",
        "question": (
            "Your Node.js API on a 1 GB RAM VPS randomly crashes every night around 2–3 AM. "
            "No error logs, no crash reports, no stack traces. Just a dead process. "
            "After 3 weeks of investigation you find the real culprit. What killed your app every night?"
        ),
        "learning_note": (
            "The Linux OOM (Out-of-Memory) Killer silently terminates the process consuming the most memory "
            "when RAM + swap is exhausted. It logs ONLY to /var/log/syslog or dmesg — never to your app logs. "
            "That's why it hides for weeks. Check 'dmesg | grep -i oom' or 'grep -i oom /var/log/syslog' "
            "to catch it. Fix: add swap as a buffer OR reduce memory leaks."
        ),
        "answers": [
            "Linux OOM Killer terminated the process when RAM + swap was exhausted",
            "A cron job was scheduled to restart the server every night at 2 AM",
            "The VPS provider performs automated nightly maintenance reboots",
            "A Node.js memory leak triggered its own built-in graceful shutdown handler",
        ],
        "correct_answer": 0,
        "reward": "Top 3 fastest correct winners get 1 month RAM-upgraded VPS plan",
        "hashtags": ["#Linux", "#OOMKiller", "#VPS", "#NodeJS", "#UpgradeTeam"],
        "seo_keywords": ["OOM killer Linux VPS", "Node.js crash no logs", "process killed automatically Linux"],
    },
    {
        "title": "The $800 Bandwidth Bill",
        "question": (
            "A developer deploys a video streaming app on AWS EC2 (t3.small) in us-east-1. "
            "The app serves maybe 200 users/day. The next month's bill: $800. "
            "Compute is $17. Where did the other $783 come from?"
        ),
        "learning_note": (
            "AWS charges $0.09/GB for outbound (egress) bandwidth — and it adds up fast for media. "
            "200 users streaming 500 MB each = 100 GB/day = 3 TB/month = $270 in egress alone. "
            "Peak days multiply this further. Hetzner or Vultr include 20 TB/month free. "
            "Egress pricing is the single most common billing shock for AWS newcomers."
        ),
        "answers": [
            "AWS egress (outbound) data transfer fees at $0.09/GB",
            "EC2 CPU credit charges from sustained streaming load",
            "S3 storage and request fees for the video files",
            "Elastic IP and NAT Gateway fees for the public address",
        ],
        "correct_answer": 0,
        "reward": "3 winners each get 2 months of unlimited-bandwidth VPS — results in 4 hours",
        "hashtags": ["#AWS", "#CloudCost", "#VPS", "#BandwidthBill", "#UpgradeTeam"],
        "seo_keywords": ["AWS bandwidth cost egress", "cloud billing shock", "VPS vs AWS pricing comparison"],
    },
    {
        "title": "The Swap Space Trap",
        "question": (
            "Your 2 GB RAM VPS struggles under afternoon traffic spikes. You add 4 GB of swap space, "
            "expecting to handle the overflow gracefully. Under the next traffic spike, "
            "response times jump from 200ms to 18 seconds. The server is technically alive but unusable. "
            "What went wrong?"
        ),
        "learning_note": (
            "VPS swap lives on a network-attached SSD shared with other tenants. "
            "When the OS actively swaps, every memory page fault becomes a disk I/O operation. "
            "Network storage I/O is 50-100x slower than RAM. A server thrashing swap is slower than no server. "
            "Swap is a crash buffer, not extra RAM. The real fix is to upgrade RAM or optimize the app's memory use."
        ),
        "answers": [
            "The VPS network-attached disk is too slow — swap caused catastrophic I/O thrashing",
            "The swap file was formatted with wrong block size, causing data corruption",
            "Adding swap conflicted with the hypervisor's memory ballooning mechanism",
            "Linux prioritized swap over RAM due to a default swappiness=60 setting",
        ],
        "correct_answer": 0,
        "reward": "Top 3 correct + fastest answers win 1 month upgraded VPS — 4 hour deadline",
        "hashtags": ["#Linux", "#Swap", "#VPS", "#Performance", "#UpgradeTeam"],
        "seo_keywords": ["VPS swap slow performance", "Linux swap thrashing", "VPS memory optimization tips"],
    },
]


def _fallback_content(topic: str, language: str) -> dict[str, Any]:
    """Return a random high-quality fallback challenge from the diverse pool."""
    return random.choice(_FALLBACK_POOL)


def _clean_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    payload = fenced.group(1) if fenced else text.strip()
    return json.loads(payload)


import re as _re

def _is_english_only(value: str) -> bool:
    """Reject Arabic, Persian, CJK, Cyrillic, and other non-Latin-script text.

    Allows em dashes, smart quotes, bullet points, currency symbols, and other
    common typographic Unicode that LLMs naturally produce in English prose.
    Only blocks specific script ranges that indicate non-English languages.
    """
    return not _re.search(
        r"[\u0600-\u06FF"   # Arabic / Persian
        r"\u0750-\u077F"    # Arabic Supplement
        r"\u4E00-\u9FFF"    # CJK Unified Ideographs
        r"\u3040-\u30FF"    # Hiragana / Katakana
        r"\uAC00-\uD7AF"    # Hangul
        r"\u0400-\u04FF"    # Cyrillic
        r"\u0590-\u05FF"    # Hebrew
        r"\u0E00-\u0E7F"    # Thai
        r"\u0900-\u097F]",  # Devanagari
        value,
    )


def _validate_content(content: dict[str, Any], topic: str, language: str) -> dict[str, Any]:
    required = (
        "title",
        "question",
        "learning_note",
        "answers",
        "correct_answer",
        "reward",
        "hashtags",
        "seo_keywords",
    )
    if any(key not in content for key in required):
        raise ValueError("AI response is missing required challenge fields")
    answers = content["answers"]
    correct_answer = content["correct_answer"]
    if not isinstance(answers, list) or len(answers) != 4:
        raise ValueError("A challenge must have exactly four answers")
    if not isinstance(correct_answer, int) or correct_answer not in range(4):
        raise ValueError("correct_answer must be an answer index from 0 to 3")
    content["title"] = str(content["title"])[:500]
    content["question"] = str(content["question"])[:4000]
    content["learning_note"] = str(content["learning_note"])[:4000]
    content["answers"] = [str(answer)[:500] for answer in answers]
    content["reward"] = str(content["reward"])[:500]
    content["hashtags"] = [str(tag)[:80] for tag in content["hashtags"][:12]]
    content["seo_keywords"] = [str(keyword)[:120] for keyword in content["seo_keywords"][:12]]
    public_fields = [
        content["title"],
        content["question"],
        content["learning_note"],
        *content["answers"],
        content["reward"],
    ]
    if not all(_is_english_only(value) for value in public_fields):
        raise ValueError("Challenge content must be English-only")
    return content


def pick_next_topic(recent_titles: list[str]) -> str:
    """Pick a topic from CHALLENGE_TOPIC_POOL that hasn't been used recently.

    Shuffles the pool and returns the first entry — combined with recent_titles
    injection into the AI prompt this ensures high variety across consecutive runs.
    """
    pool = list(CHALLENGE_TOPIC_POOL)
    random.shuffle(pool)
    return pool[0]


async def generate_challenge_content(
    topic: str,
    language: str = "en",
    recent_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a unique, engaging, viral-worthy challenge via the AI model.

    Args:
        topic: The specific angle or subject for this challenge.
        language: Target language (always forced to 'en').
        recent_titles: Titles of the last N challenges — injected into the prompt
            so the AI actively avoids repeating them.
    """
    language = "en"
    if not settings.XAI_API_KEY:
        logger.warning("xai_key_not_configured_using_safe_fallback")
        return _fallback_content(topic, language)

    client = AsyncOpenAI(
        api_key=settings.XAI_API_KEY,
        base_url=settings.XAI_BASE_URL,
        timeout=60.0,
        max_retries=1,
    )

    avoid_block = ""
    if recent_titles:
        titles_list = "\n".join(f"  - {t}" for t in recent_titles[:15])
        avoid_block = (
            "\n\nCRITICAL — these challenge titles ran recently. "
            "Your new challenge MUST cover a completely different scenario, tool, and angle. "
            "Do NOT reuse any concept from this list:\n" + titles_list + "\n"
        )

    system = (
        "You are the world's best community growth engineer and senior infrastructure expert "
        "for a high-energy Telegram channel about RDP, VPS, and server infrastructure. "
        "Your challenges run every 4 hours and are legendary — they go viral, spark heated debate, "
        "and make members check back every session to see if they got it right. "
        "\n\n"
        "Every challenge you write must feel like a senior engineer sharing a war story — "
        "not a textbook definition. Use real tool names, real error messages, real numbers. "
        "The scenario must be immediately recognizable to anyone who has managed a server. "
        "The WRONG answers must be what 70% of people would confidently choose. "
        "The learning_note must deliver a genuine 'I had no idea' insight that people screenshot. "
        "\n\n"
        "Return JSON only. Never request passwords, tokens, personal data, spam, fake activity, "
        "or unsafe instructions. Write every user-facing field in clear natural English only. "
        "Never use Persian, Arabic, or any other language."
    )

    prompt = f"""Create one elite-level technical challenge for the Upgrade Team VPS/RDP Telegram community.

The challenge MUST be:
1. A VIVID REAL-WORLD SCENARIO — not a definition or trivia question. Describe a situation
   a sysadmin/developer actually faces: what they were doing, what went wrong, what's at stake.
2. GENUINELY HARD — all 4 options must seem technically plausible to someone with 1-2 years
   of experience. The correct answer should require expert-level knowledge to pick confidently.
3. EDUCATIONAL & SHAREABLE — the learning_note must deliver a surprising, memorable insight
   that people want to screenshot and share in their own server groups.
4. SPECIFIC — use real tool names, real commands, real numbers (GB, ms, $/month, lines of config).
5. VARIED — cover a fresh angle not seen recently.
{avoid_block}
Topic angle to explore: {topic}

Return EXACTLY this JSON (no extra keys):
{{
  "title": "A punchy story-style title, 5-9 words, no question mark. Like: 'The $800 Bandwidth Surprise' or 'Why Swap Killed the VPS'",
  "question": "MAX 2 sentences (under 250 characters total): one sentence sets the scene with a specific detail, one sentence asks the decision question. Be vivid but SHORT.",
  "learning_note": "2-3 sentences explaining WHY the correct answer is right and the key insight the reader should remember.",
  "answers": [
    "Short, specific option — max 70 characters",
    "Short, specific option — max 70 characters",
    "Short, specific option — max 70 characters",
    "Short, specific option — max 70 characters"
  ],
  "correct_answer": 2,
  "reward": "Top 3 fastest correct answers win [specific attractive VPS/RDP prize] — results posted in 4 hours",
  "hashtags": ["#RDP", "#VPS", "#SysAdmin", "#UpgradeTeam", "#ServerTips"],
  "seo_keywords": ["4-6 specific search keywords"]
}}

IMPORTANT: Randomize which index (0, 1, 2, or 3) holds the correct answer each time.
The example above shows index 2 — do NOT always use 0. Vary it unpredictably.
"""

    try:
        response = await client.chat.completions.create(
            model=settings.XAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.95,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        content = _clean_json(response.choices[0].message.content or "")
        return _validate_content(content, topic, language)
    except Exception as exc:
        logger.error("ai_challenge_generation_failed_using_fallback", error=str(exc))
        return _fallback_content(topic, language)
