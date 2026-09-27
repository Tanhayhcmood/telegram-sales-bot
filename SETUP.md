# راهنمای نصب و راه‌اندازی Telegram Sales Agent

## پیش‌نیازها (روی سرور نصب کن)

```bash
# Ubuntu/Debian
apt update
apt install -y python3 python3-pip redis-server postgresql

# یا با Docker:
docker-compose up -d  # اگه docker-compose.yml داری
```

---

## مراحل نصب

### ۱. نصب پکیج‌های Python

```bash
cd telegram-agent
pip3 install -r requirements.txt
```

---

### ۲. ساختن فایل `.env`

```bash
cp .env.example .env
nano .env   # مقادیر رو پر کن
```

مقادیر **اجباری** که باید پر کنی:

| متغیر | توضیح |
|-------|-------|
| `DATABASE_URL` | آدرس PostgreSQL — مثلاً `postgresql://user:pass@localhost:5432/dbname` |
| `ADMIN_BOT_TOKEN` | توکن ربات ادمین از @BotFather |
| `ADMIN_TELEGRAM_IDS` | آیدی عددی تلگرام خودت — مثلاً `123456789` |
| `GROQ_API_KEY` | کلید API از [console.groq.com](https://console.groq.com) |
| `SECRET_KEY` | یه رشته تصادفی بلند (امنیت session) |
| `API_KEY` | یه رشته دلخواه برای احراز هویت REST API |

---

### ۳. ساختن دیتابیس PostgreSQL

```bash
# وارد postgres بشو
psql -U postgres

# دیتابیس بساز
CREATE DATABASE telegram_agent;
CREATE USER agent_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE telegram_agent TO agent_user;
\q
```

---

### ۴. اجرای Migrations

```bash
cd telegram-agent
alembic upgrade head
```

---

### ۵. اجرای سرور

```bash
bash start.sh
```

سرور روی پورت `5001` بالا میاد.

---

### ۶. اتصال اکانت تلگرام (Userbot)

بعد از اجرا، باید session تلگرام رو ثبت کنی:

#### روش ۱ — از طریق Session Generator:
```bash
# Session Generator رو اجرا کن
cd session-gen
pip3 install -r requirements_session_gen.txt
python3 app.py
# برو به http://localhost:5000 و شماره تلفن رو وارد کن
```

#### روش ۲ — از طریق API:
```bash
# ثبت اکانت
curl -X POST http://localhost:5001/api/v1/accounts \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+989xxxxxxxxx", "session_string": "SESSION_STRING_HERE"}'
```

---

### ۷. اسکن خودکار کانال‌ها

بعد از اتصال اکانت، ربات ادمین رو باز کن و دکمه **📡 Scan Channels** رو بزن.

یا از API:
```bash
curl -X POST http://localhost:5001/api/v1/channels/discover/ACCOUNT_ID \
  -H "X-API-Key: YOUR_API_KEY"
```

فقط کانال‌هایی که **ادمین یا سازنده** اونا هستی ثبت می‌شن.

---

## دستورات ربات ادمین

| دستور | کار |
|-------|-----|
| `/start` | منوی اصلی |
| `/scan_channels` | اسکن و ثبت کانال‌ها |
| `/status` | وضعیت userbot |

---

## ساختار پروژه

```
telegram-agent/
├── app/
│   ├── api/v1/          ← endpoints
│   ├── models/          ← مدل‌های دیتابیس
│   ├── services/
│   │   ├── admin_bot/   ← ربات ادمین (aiogram)
│   │   ├── userbot/     ← userbot (telethon)
│   │   └── channel/     ← پست‌گذاری و discovery
│   └── main.py
├── alembic/             ← migrations
├── .env.example
├── requirements.txt
└── start.sh
```
