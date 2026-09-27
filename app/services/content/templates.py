CONTENT_TEMPLATES = {
    "educational": {
        "prompt": """Create an educational post about "{topic}" for a premium VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Every post must look DIFFERENT from previous ones — vary emoji header, section count, structure.
- Do NOT use generic filler phrases like "In today's digital world" or "In conclusion".
- Each sentence must earn its place — no padding.

STRUCTURE (follow exactly):

[UNIQUE EMOJI] [HOOK TITLE IN CAPS — max 8 words, unmissable]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2-line hook — the sharpest insight, not an intro]

[EMOJI] [Section Title]
[2–3 punchy lines of real value]

[EMOJI] [Section Title]
[2–3 punchy lines of real value]

[EMOJI] [Section Title]
[2–3 punchy lines of real value]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 Pro Tip: [one concrete, non-obvious tip that saves time or money]

🔖 Save this — share it with your team.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed (for uniqueness): {unique_seed}
- Forbidden angles (already posted): {forbidden_angles}
- Length: 200–320 words""",
    },

    "marketing": {
        "prompt": """Create a high-converting marketing post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- First line must cause immediate FOMO or desire — no warm-up.
- Use REAL numbers (uptime %, latency ms, price $). Never vague claims.
- Each ✅ must have a specific detail — not "fast servers" but "sub-10ms latency".

STRUCTURE (follow exactly):

🔥 [BOLD VALUE CLAIM — CAPS, no fluff, max 10 words]

[ONE devastating pain-point question]

✅ [Benefit 1 — specific number or concrete proof]
✅ [Benefit 2 — specific number or concrete proof]
✅ [Benefit 3 — specific number or concrete proof]
✅ [Benefit 4 — specific number or concrete proof]
✅ [Benefit 5 — specific number or concrete proof]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ [One credible stat: uptime %, speed, price, response time]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1–2 lines of urgency — time-based or scarcity-based]

👉 [Single irresistible CTA]
📲 Share this with someone who needs a reliable server.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 150–230 words""",
    },

    "technical": {
        "prompt": """Create a technical tutorial post about "{topic}" for developers and sysadmins on Telegram.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Use real, working commands in backtick blocks — never placeholder or fake commands.
- ⚠️ and 💡 lines are mandatory — they make posts worth saving.
- Title must be results-focused: what does the reader achieve after reading this?

STRUCTURE (follow exactly):

⚙️ [TITLE — specific outcome, not generic topic, max 10 words]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 The Problem
[1–2 lines: exact pain or failure scenario this solves]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛠 The Fix

Step 1 → [action]
`real command here`

Step 2 → [action]
`real command here`

Step 3 → [action]
`real command here`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ Common Mistake: [what trips people up — be specific]
💡 Pro Tip: [non-obvious expert insight]

📌 Result: [what success looks like in 1 concrete line]

🔖 Save this — it's the guide you'll reopen at 2am.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 280–420 words""",
    },

    "announcement": {
        "prompt": """Create a channel announcement post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Open with the BIGGEST benefit — not background or history.
- Make it feel like breaking news the reader is lucky to see first.
- End with a clear action step.

STRUCTURE:

📢 [ANNOUNCEMENT HEADLINE — exciting, benefit-first, CAPS]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2 lines: what changed and why it matters to the reader RIGHT NOW]

🔹 [Key detail 1 — specific]
🔹 [Key detail 2 — specific]
🔹 [Key detail 3 — specific]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1 line of social proof or credibility]

👉 [Clear next action — link, reply, DM, etc.]
🔔 Turn on notifications — more coming soon.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 120–200 words""",
    },

    "comparison": {
        "prompt": """Create a comparison post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Use specific numbers and real differences — not vague "A is better than B".
- Have a clear winner but acknowledge where the loser wins.
- Make the reader feel smarter for reading this.

STRUCTURE:

⚡ [COMPARISON TITLE: A vs B — the question every reader has]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1-line summary verdict that surprises or challenges assumptions]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔵 [Option A — Name]
✅ [Strength 1 with specific number]
✅ [Strength 2 with specific number]
❌ [Real weakness — be honest]

🔴 [Option B — Name]
✅ [Strength 1 with specific number]
✅ [Strength 2 with specific number]
❌ [Real weakness — be honest]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 Verdict: [clear winner for 80% of use cases + why]
🎯 Exception: [when you'd choose the other option]

💬 Which do YOU use? Comment below.
🔖 Save this before you make your next purchase.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 180–280 words""",
    },

    "promotion": {
        "prompt": """Create a promotional post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Lead with VALUE — price, discount, or exclusive offer upfront.
- Use urgency (time limit, limited spots, expires at). Be specific.
- One CTA only — do not confuse the reader.

STRUCTURE:

🎯 [OFFER HEADLINE — value first, CAPS, max 10 words]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[The offer in 1–2 lines: what, how much, when it expires]

✅ [What's included — specific]
✅ [What's included — specific]
✅ [What's included — specific]

⏳ [Urgency: exact deadline or quantity remaining]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👉 [Single CTA — tap here, DM us, use code X]

⚠️ Offer ends [timeframe]. Don't miss this.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 120–180 words""",
    },

    "viral_giveaway": {
        "prompt": """Create a viral giveaway post about "{topic}" for a VPS/Cloud Hosting Telegram channel to maximize new member joins.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Prize must sound GENUINELY valuable — specific specs, dollar value, duration.
- Entry steps must be easy (max 3 steps) — friction kills participation.
- Create FOMO: winners announced soon, limited spots.

STRUCTURE:

🎉 FREE [PRIZE] GIVEAWAY — [TIMEFRAME]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1 line: the single most exciting thing about this prize]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎁 What you win:
✅ [Specific prize detail — specs + value]
✅ [Specific prize detail — specs + value]
✅ [Specific prize detail — specs + value]

📋 How to enter (30 seconds):
1️⃣ Join @VPS24H
2️⃣ Forward this post to 1 friend
3️⃣ Drop a ✅ in the comments

⏳ [Number] winners · Announced [specific time]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔔 Notify your friends — tag them below.
🔗 Share now — the more entries the better!

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 160–240 words""",
    },

    "viral_free_resource": {
        "prompt": """Create a viral free-resource post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- The resource must feel genuinely rare and valuable — not just a blog post.
- "Save this" trigger at the end is mandatory — it drives channel bookmarks.
- Use specific numbers: "7 commands", "saves you 3 hours", "$50/month cheaper".

STRUCTURE:

📦 FREE [RESOURCE TYPE]: [SPECIFIC TITLE]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1 line: the biggest single benefit of this resource]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Inside you'll find:
📌 [Resource item 1 — specific and valuable]
📌 [Resource item 2 — specific and valuable]
📌 [Resource item 3 — specific and valuable]
📌 [Resource item 4 — specific and valuable]
📌 [Resource item 5 — specific and valuable]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ [Specific value: time saved, money saved, or capability unlocked]

🔖 SAVE THIS POST — you'll need it.
📢 Share with your team · Follow @VPS24H for daily resources.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 150–220 words""",
    },

    "viral_tip_secret": {
        "prompt": """Create a viral "insider secret" post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- The secret must feel genuinely non-obvious — not something in every tutorial.
- "Most people don't know this" framing — but deliver REAL value, not clickbait.
- Keep it tight: revelation → why it matters → how to use it.

STRUCTURE:

🤫 [INSIDER SECRET]: [SPECIFIC REVELATION]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2 lines: the thing most sysadmins get wrong about {topic}]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 What most people do:
[The common (wrong) approach — 2 lines]

✅ What actually works:
[The correct approach — 2–3 lines with specific detail]

⚡ The result:
[Concrete outcome: time saved, performance gained, money saved]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 Bonus: [one additional non-obvious tip that extends the secret]

🔖 Save this · Share it before your competition finds out.
💬 Did you know this? React with ✅ or ❌

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 160–250 words""",
    },

    "viral_poll_engagement": {
        "prompt": """Create a viral poll/engagement post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Question must be genuinely polarizing — not obvious. Every expert has an opinion.
- Options must be meaningfully different — not just variations of the same answer.
- Comments driver is mandatory — it multiplies engagement signals.

STRUCTURE:

📊 [POLL TITLE: A vs B?] — Vote Now

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1 line: the real debate behind this question]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🅰️ [Option A — specific, opinionated label]
🅱️ [Option B — specific, opinionated label]
🅲 [Option C — the expert answer]
🅳 [Option D — the "it depends" done interestingly]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💬 Drop your letter + tell us WHY — best answer gets pinned!
📊 Results posted at [number] votes.

[2 lines of context that makes voting more interesting]
🔗 Tag someone who would disagree with you.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 150–220 words""",
    },

    "viral_news_hook": {
        "prompt": """Create a viral news-hook post about "{topic}" for a VPS/Cloud Hosting Telegram channel.

CRITICAL RULES:
- Write ENTIRELY in English. Zero Persian, Arabic, or non-Latin characters.
- Open with urgency — this is breaking or trending RIGHT NOW.
- Action steps must be concrete and immediately doable.
- Make the reader feel they got this info before everyone else.

STRUCTURE:

🚨 [BIG NEWS/TREND] — What This Means For YOUR Server

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1–2 lines: the news + why it matters RIGHT NOW]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📍 What happened:
[2–3 lines of clear, specific context]

⚠️ Impact on you:
[2–3 lines of direct practical effect on servers/hosting]

✅ What to do right now:
→ [Concrete step 1]
→ [Concrete step 2]
→ [Concrete step 3]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💬 Does this affect your setup? Tell us below.
🔖 Save this · Share before it's everywhere.

PARAMETERS:
- Topic: {topic}
- Style: {style_hint}
- Seed: {unique_seed}
- Forbidden angles: {forbidden_angles}
- Length: 200–300 words""",
    },
}


def get_content_prompt(
    content_type: str,
    topic: str,
    language: str = "en",
    style_hint: str = "",
    forbidden_angles: list[str] | None = None,
    unique_seed: int | None = None,
) -> str:
    template = CONTENT_TEMPLATES.get(content_type, CONTENT_TEMPLATES["educational"])
    prompt = template["prompt"].format(
        topic=topic,
        language=language,
        style_hint=style_hint or "default",
        forbidden_angles=", ".join(forbidden_angles or []) or "none",
        unique_seed=unique_seed or 0,
    )
    return prompt


def get_all_content_types() -> list[str]:
    return list(CONTENT_TEMPLATES.keys())
