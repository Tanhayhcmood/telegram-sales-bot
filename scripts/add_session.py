"""
Script to authenticate a Telegram user account and save the session.
Run this ONCE on your server before starting the main app.

Usage:
    python scripts/add_session.py --phone +1234567890
"""
import asyncio
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")


async def authenticate(phone: str):
    print(f"\n=== Authenticating Telegram account: {phone} ===\n")

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("Sending code to your Telegram...")
        await client.send_code_request(phone)
        code = input("Enter the code you received: ").strip()

        try:
            await client.sign_in(phone, code)
        except Exception:
            password = input("Two-factor authentication enabled. Enter your password: ").strip()
            await client.sign_in(password=password)

    me = await client.get_me()
    session_string = client.session.save()

    print(f"\n✅ Successfully authenticated as: {me.first_name} (@{me.username})")
    print(f"\n📋 Session String (save this to DB or .env):\n")
    print(session_string)
    print(f"\nAdd this account via API:")
    print(f"""
curl -X POST http://localhost:8000/api/v1/accounts \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"phone": "{phone}", "session_string": "PASTE_SESSION_STRING_HERE", "display_name": "{me.first_name}"}}'
""")

    await client.disconnect()
    return session_string


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Authenticate Telegram UserBot account")
    parser.add_argument("--phone", required=True, help="Phone number in international format (+1234567890)")
    args = parser.parse_args()

    asyncio.run(authenticate(args.phone))
