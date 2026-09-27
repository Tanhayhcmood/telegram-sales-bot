# راهنمای کامل نصب روی Render (رایگان)

## پیش‌نیازها

قبل از شروع اینا رو آماده کن:

| چیزی که نیاز داری | از کجا بگیری |
|---|---|
| توکن ربات ادمین | از [@BotFather](https://t.me/BotFather) — دستور `/newbot` |
| آیدی عددی تلگرام خودت | از [@userinfobot](https://t.me/userinfobot) |
| کلید API هوش مصنوعی | از [console.groq.com](https://console.groq.com) (رایگان) یا [platform.openai.com](https://platform.openai.com) |
| اکانت Render | از [render.com](https://render.com) (رایگان) |
| اکانت GitHub | برای آپلود کد |

---

## مرحله ۱ — آپلود کد روی GitHub

### ۱.۱ یه ریپو جدید بساز
رو GitHub یه ریپو **خصوصی (Private)** بساز و این فایل‌ها رو داخلش آپلود کن (فقط همین پوشه `telegram-bot`، نه کل چیز دیگه‌ای).

ساختار نهایی ریپو باید اینطوری باشه:
```
your-repo/
├── app/
├── alembic/
├── data/
├── scripts/
├── Dockerfile
├── render.yaml
├── requirements.txt
├── alembic.ini
└── start.sh
```

> **توجه:** محتویات پوشه `telegram-bot` رو آپلود کن، نه خود پوشه رو.

---

## مرحله ۲ — ساخت سرویس روی Render

### ۲.۱ ساخت PostgreSQL رایگان

1. برو به [dashboard.render.com](https://dashboard.render.com)
2. روی **New +** کلیک کن
3. انتخاب کن **PostgreSQL**
4. تنظیمات:
   - **Name:** `telegram-bot-db`
   - **Database:** `telegram_agent`
   - **User:** `telegram_agent`
   - **Plan:** Free
5. روی **Create Database** کلیک کن
6. صبر کن تا بسازه، بعد از صفحه دیتابیس **Internal Database URL** رو کپی کن — بعداً لازم داری

---

### ۲.۲ ساخت Web Service

1. روی **New +** کلیک کن
2. انتخاب کن **Web Service**
3. ریپو GitHub رو متصل کن
4. تنظیمات:
   - **Name:** `telegram-sales-bot`
   - **Region:** هر کدوم که نزدیک‌تره (Frankfurt پیشنهادیه)
   - **Branch:** `main`
   - **Runtime:** `Docker`
   - **Plan:** Free
5. روی **Advanced** کلیک کن تا متغیرهای محیطی رو تنظیم کنی

---

## مرحله ۳ — تنظیم متغیرهای محیطی

در بخش **Environment Variables** اینا رو اضافه کن:

### اجباری — بدون اینا کار نمی‌کنه

| Key | Value | توضیح |
|-----|-------|-------|
| `DATABASE_URL` | `Internal Database URL` که کپی کردی | آدرس دیتابیس |
| `ADMIN_BOT_TOKEN` | `1234567890:ABC...` | توکن ربات از BotFather |
| `ADMIN_TELEGRAM_IDS` | `123456789` | آیدی عددی تلگرام خودت |
| `SECRET_KEY` | یه رشته تصادفی بلند (حداقل ۳۲ کاراکتر) | مثلاً: `my-super-secret-key-2024-telegram-bot` |
| `API_KEY` | یه رشته دلخواه | مثلاً: `my-api-key-2024` |

### برای هوش مصنوعی — یکی از اینا

| Key | Value | توضیح |
|-----|-------|-------|
| `GROQ_API_KEY` | `gsk_...` | **پیشنهاد:** Groq رایگانه |
| `OPENAI_API_KEY` | `sk-...` | یا OpenAI اگه داری |

### اختیاری (پیش‌فرض‌ها مناسبن)

| Key | Value |
|-----|-------|
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `CORS_ORIGINS` | `*` |

---

## مرحله ۴ — Deploy کن

روی **Create Web Service** کلیک کن.

Render شروع می‌کنه به:
1. Docker image ساختن (~۵ دقیقه)
2. پکیج‌ها نصب کردن
3. Migration دیتابیس اجرا کردن
4. سرور راه‌اندازی کردن

**صبر کن تا در logs ببینی:**
```
[start] Running DB migrations...
[start] Starting server on port 10000...
INFO: Application startup complete.
```

---

## مرحله ۵ — اتصال اکانت تلگرام (Userbot)

بعد از اینکه سرویس اجرا شد، باید session تلگرام رو ثبت کنی.

### روش آسان — Session Generator

پوشه `session-gen` یه ابزار وب داره برای این کار:

1. اون رو هم روی Render به عنوان یه Web Service جداگانه deploy کن
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements_session_gen.txt`
   - **Start Command:** `python app.py`
2. آدرس اون رو باز کن
3. شماره تلفنت رو وارد کن
4. کد تأییدیه رو وارد کن
5. Session String رو کپی کن

### ثبت اکانت از طریق API

بعد از دریافت Session String:

```bash
curl -X POST https://YOUR_SERVICE_URL.onrender.com/api/v1/accounts \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+989xxxxxxxxx",
    "session_string": "SESSION_STRING_HERE"
  }'
```

---

## مرحله ۶ — اسکن کانال‌ها

بعد از ثبت اکانت، ربات ادمین رو باز کن:
1. `/start` بزن
2. **📡 Scan Channels** رو انتخاب کن
3. ربات خودش کانال‌هایی که ادمینشی رو پیدا می‌کنه

---

## بررسی اجرای صحیح

```bash
# Health check
curl https://YOUR_SERVICE_URL.onrender.com/api/healthz
# باید برگردونه: {"status":"ok","app":"TelegramAgent"}
```

---

## محدودیت‌های سرور رایگان Render

| موضوع | توضیح |
|-------|-------|
| **Sleep** | بعد از ۱۵ دقیقه بی‌فعالیت سرویس می‌خوابه — اولین درخواست بعد ~۵۰ ثانیه طول می‌کشه |
| **RAM** | ۵۱۲ مگابایت |
| **دیتابیس** | ۱ گیگابایت، بعد از ۹۰ روز expire می‌شه |
| **Redis** | Redis رایگان نیست — ربات از fakeredis (حافظه موقت) استفاده می‌کنه |

> **برای جلوگیری از sleep:** می‌تونی از [UptimeRobot](https://uptimerobot.com) (رایگان) استفاده کنی تا هر ۵ دقیقه یه بار `/api/healthz` رو ping کنه.

---

## مشکلات رایج

### ❌ خطا: `DATABASE_URL not set`
→ مطمئن شو که Internal Database URL رو درست کپی کردی

### ❌ خطا: `ADMIN_BOT_TOKEN not set`
→ توکن ربات رو از BotFather بگیر و تنظیم کن

### ❌ `alembic upgrade head` شکست خورد
→ این معمولاً یعنی دیتابیس هنوز آماده نشده. چند دقیقه صبر کن و دوباره deploy کن

### ❌ ربات ادمین جواب نمی‌ده
→ مطمئن شو `ADMIN_TELEGRAM_IDS` رو با آیدی عددی **خودت** پر کردی (نه username)

### ❌ Userbot connect نمی‌شه
→ باید Session String رو از طریق session-gen ثبت کنی (مرحله ۵)

---

## آپگرید به پلن پولی (اختیاری)

اگه خواستی سرور همیشه بیدار باشه:
- **Starter Plan** در Render: ~$7/ماه
- یا می‌تونی روی **Railway.app** یا **Fly.io** هم deploy کنی که پلن رایگان بهتری دارن
