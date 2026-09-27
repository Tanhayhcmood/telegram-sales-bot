# Telegram AI User Account Agent

یک ربات هوشمند تلگرام برای کسب‌وکارهای VPS، Cloud و Dedicated Server با پشتیبانی از ۸ زبان.

---

## ساختار پروژه

```
telegram-agent/
├── app/
│   ├── main.py                    ← نقطه ورود FastAPI
│   ├── core/                      ← تنظیمات، لاگ، امنیت
│   ├── db/                        ← SQLAlchemy، مایگریشن‌ها
│   ├── models/                    ← مدل‌های دیتابیس
│   ├── cache/                     ← Redis client
│   ├── api/v1/                    ← REST API endpoints
│   ├── services/
│   │   ├── userbot/               ← Telethon UserBot (اکانت واقعی)
│   │   ├── admin_bot/             ← ربات مدیریت (BotFather)
│   │   ├── ai/                    ← موتور هوش مصنوعی
│   │   ├── content/               ← تولید محتوا
│   │   ├── channel/               ← مدیریت کانال‌ها
│   │   ├── sales/                 ← مدیریت لیدها و فروش
│   │   ├── anti_spam/             ← ضد اسپم
│   │   ├── monitoring/            ← مانیتورینگ
│   │   └── learning/              ← سیستم یادگیری
│   └── workers/                   ← تسک‌های پس‌زمینه (ARQ)
├── data/knowledge/                ← اطلاعات پلن‌ها و سیاست‌ها
├── docker/                        ← Dockerfile و docker-compose
├── scripts/                       ← اسکریپت‌های کمکی
└── alembic/                       ← مایگریشن دیتابیس
```

---

## پیش‌نیازها

- سرور لینوکس (Ubuntu 22.04 توصیه می‌شود)
- Docker + Docker Compose
- حداقل ۲GB RAM
- اینترنت با دسترسی به Telegram

---

## مرحله ۱ — آماده‌سازی محیط

```bash
# کلون پروژه روی سرور
git clone <repo-url> telegram-agent
cd telegram-agent

# کپی فایل تنظیمات
cp .env.example .env

# ویرایش فایل .env
nano .env
```

---

## مرحله ۲ — پر کردن فایل .env

مقادیر ضروری:

```env
# ───── کلیدهای Telegram API ─────
# از https://my.telegram.org بگیرید
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# ───── ربات ادمین ─────
# از @BotFather بسازید (فقط برای مدیران)
ADMIN_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyz
ADMIN_TELEGRAM_IDS=123456789,987654321   # آیدی عددی تلگرام ادمین‌ها

# ───── OpenAI ─────
OPENAI_API_KEY=sk-proj-...

# ───── Groq برای طراحی چیدمان تصویر دسکتاپ ─────
# کلید را فقط در Replit → Secrets با نام GROQ_API_KEY قرار دهید.
# تصویر نهایی از assetهای واقعی Windows پروژه ساخته می‌شود.
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-20b

# ───── امنیت ─────
SECRET_KEY=یک-رشته-تصادفی-۵۰-کاراکتری-اینجا-بگذارید
API_KEY=کلید-API-برای-دسترسی-به-REST

# ───── دیتابیس ─────
# نیازی به تغییر ندارد اگر با Docker اجرا می‌کنید
DATABASE_URL=postgresql+asyncpg://postgres:changeme@db:5432/telegram_agent
POSTGRES_PASSWORD=changeme   # این را حتماً عوض کنید!
```

---

## مرحله ۳ — احراز هویت اکانت تلگرام (UserBot)

این مرحله **یک‌بار** انجام می‌شود تا session ذخیره شود.

```bash
# نصب وابستگی‌های موقت
pip3 install telethon python-dotenv

# اجرای اسکریپت احراز هویت
python3 scripts/add_session.py --phone +989123456789
```

بعد از احراز هویت، session string را کپی کنید. بعداً از طریق API اضافه می‌کنید.

---

## مرحله ۴ — اجرا با Docker

```bash
# ساخت و اجرای همه سرویس‌ها
cd docker
docker compose up -d --build

# بررسی وضعیت
docker compose ps

# مشاهده لاگ‌ها
docker compose logs -f app
docker compose logs -f worker
```

---

## مرحله ۵ — اضافه کردن اکانت Telegram

بعد از راه‌اندازی، اکانت تلگرام را از طریق API اضافه کنید:

```bash
curl -X POST http://YOUR_SERVER_IP/api/v1/accounts \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+989123456789",
    "session_string": "PASTE_SESSION_STRING_FROM_STEP_3",
    "display_name": "Sales Agent"
  }'
```

---

## مرحله ۶ — اضافه کردن کانال‌ها

```bash
curl -X POST http://YOUR_SERVER_IP/api/v1/channels \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "ACCOUNT_UUID_FROM_STEP_5",
    "telegram_channel_id": -1001234567890,
    "username": "my_channel",
    "display_name": "VPS Iran",
    "language": "fa"
  }'
```

---

## API Endpoints

| Method | Path | توضیح |
|--------|------|-------|
| GET | `/api/healthz` | Health check (بدون احراز هویت) |
| GET | `/api/v1/metrics/dashboard` | داشبورد کامل |
| GET | `/api/v1/customers` | لیست مشتریان |
| GET | `/api/v1/conversations` | لیست مکالمات |
| GET | `/api/v1/leads` | لیست لیدها |
| POST | `/api/v1/content/generate` | تولید محتوا |
| POST | `/api/v1/content/generate-desktop-image` | تولید و ذخیره تصویر دسکتاپ Windows |
| POST | `/api/v1/content/posts` | ساخت پست |
| POST | `/api/v1/content/posts/{id}/publish` | انتشار فوری |
| GET | `/api/v1/accounts/status` | وضعیت اکانت‌ها |

مستندات کامل: `http://YOUR_SERVER/api/docs`

---

## دستورات ربات ادمین

```
/start     — منوی اصلی
/status    — وضعیت سیستم
/metrics   — CPU، RAM، Disk
/conversations — آمار مکالمات
/sales     — آمار فروش و لیدها
/publishing — آمار انتشار
/logs      — لاگ‌ها و گزارش‌ها
/alerts    — هشدارهای فعال
/control   — کنترل سرویس‌ها
```

---

## تولید محتوا

```bash
# تولید پست آموزشی فارسی
curl -X POST http://YOUR_SERVER/api/v1/content/generate \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "مزایای VPS نسبت به هاست اشتراکی",
    "content_type": "educational",
    "language": "fa"
  }'

# تولید چندزبانه
curl -X POST http://YOUR_SERVER/api/v1/content/generate-multilingual \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "New NVMe VPS Plans",
    "content_type": "marketing",
    "languages": ["en", "fa", "ar", "tr"]
  }'
```

---

## نگهداری

```bash
# بکاپ دیتابیس
docker exec telegram_agent_db bash -c "PGPASSWORD=changeme pg_dump -U postgres telegram_agent" > backup.sql

# ری‌استارت فقط app
docker compose restart app

# بروزرسانی
git pull
docker compose up -d --build

# مشاهده لاگ‌های خطا
docker compose logs app --tail=100 | grep ERROR
```

---

## زبان‌های پشتیبانی‌شده

| کد | زبان |
|----|------|
| fa | فارسی |
| en | English |
| ar | العربية |
| tr | Türkçe |
| ru | Русский |
| de | Deutsch |
| fr | Français |
| es | Español |

---

## نکات امنیتی

1. فایل `.env` را هرگز در git commit نکنید
2. `SECRET_KEY` و `API_KEY` را حتماً قوی انتخاب کنید
3. Nginx را پشت SSL/TLS قرار دهید
4. پورت ۸۰۰۰ را در فایروال ببندید (فقط Nginx)
5. `ADMIN_TELEGRAM_IDS` را فقط با آیدی خودتان پر کنید
