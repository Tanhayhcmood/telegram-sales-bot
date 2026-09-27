import os
import asyncio
import threading
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = os.urandom(24)

_clients = {}
_loops = {}

TELEGRAM_API_ID = 2040
TELEGRAM_API_HASH = "b18441a1ff607e10a989891a5462e627"


def get_or_create_loop(sid):
    if sid not in _loops:
        loop = asyncio.new_event_loop()
        _loops[sid] = loop
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()
    return _loops[sid]


def run_async(sid, coro):
    loop = get_or_create_loop(sid)
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


BASE = "/session-gen"


@app.route(f"{BASE}/")
@app.route(f"{BASE}")
@app.route("/")
def index():
    return render_template("index.html", base=BASE)


@app.route(f"{BASE}/send-code", methods=["POST"])
@app.route("/send-code", methods=["POST"])
def send_code():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import FloodWaitError, PhoneNumberInvalidError

    data = request.json
    phone = data.get("phone", "").strip()

    if not phone:
        return jsonify({"ok": False, "error": "شماره تلفن را وارد کنید"})

    sid = os.urandom(16).hex()
    session["sid"] = sid
    session["phone"] = phone

    async def _send():
        client = TelegramClient(StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH,
                                device_model="Desktop",
                                system_version="Windows 10",
                                app_version="4.16.4")
        await client.connect()
        result = await client.send_code_request(phone)
        _clients[sid] = {"client": client, "phone_code_hash": result.phone_code_hash}

    try:
        run_async(sid, _send())
        return jsonify({"ok": True})
    except FloodWaitError as e:
        return jsonify({"ok": False, "error": f"تلگرام قفل است. {e.seconds} ثانیه صبر کنید."})
    except PhoneNumberInvalidError:
        return jsonify({"ok": False, "error": "شماره تلفن نامعتبر است. از فرمت +98... استفاده کنید"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"خطا: {str(e)}"})


@app.route(f"{BASE}/verify-code", methods=["POST"])
@app.route("/verify-code", methods=["POST"])
def verify_code():
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

    data = request.json
    code = data.get("code", "").strip()
    sid = session.get("sid")
    phone = session.get("phone")

    if not sid or sid not in _clients:
        return jsonify({"ok": False, "error": "جلسه منقضی شده. دوباره شروع کنید"})

    client_data = _clients[sid]
    client = client_data["client"]
    phone_code_hash = client_data["phone_code_hash"]

    async def _verify():
        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            return {"status": "ok", "session": client.session.save()}
        except SessionPasswordNeededError:
            return {"status": "2fa"}
        except PhoneCodeInvalidError:
            return {"status": "error", "msg": "کد اشتباه است"}
        except PhoneCodeExpiredError:
            return {"status": "error", "msg": "کد منقضی شده. دوباره ارسال کنید"}

    try:
        result = run_async(sid, _verify())
        if result["status"] == "ok":
            _cleanup(sid)
            return jsonify({"ok": True, "session": result["session"]})
        elif result["status"] == "2fa":
            return jsonify({"ok": True, "need_2fa": True})
        else:
            return jsonify({"ok": False, "error": result["msg"]})
    except Exception as e:
        return jsonify({"ok": False, "error": f"خطا: {str(e)}"})


@app.route(f"{BASE}/verify-2fa", methods=["POST"])
@app.route("/verify-2fa", methods=["POST"])
def verify_2fa():
    data = request.json
    password = data.get("password", "").strip()
    sid = session.get("sid")

    if not sid or sid not in _clients:
        return jsonify({"ok": False, "error": "جلسه منقضی شده. دوباره شروع کنید"})

    client = _clients[sid]["client"]

    async def _2fa():
        await client.sign_in(password=password)
        return client.session.save()

    try:
        session_string = run_async(sid, _2fa())
        _cleanup(sid)
        return jsonify({"ok": True, "session": session_string})
    except Exception as e:
        return jsonify({"ok": False, "error": f"رمز اشتباه است: {str(e)}"})


def _cleanup(sid):
    if sid in _clients:
        client = _clients[sid]["client"]
        async def _disc():
            try:
                await client.disconnect()
            except Exception:
                pass
        try:
            run_async(sid, _disc())
        except Exception:
            pass
        del _clients[sid]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
