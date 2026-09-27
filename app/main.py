import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI

_import_error: str = ""
_startup_errors: list[str] = []
_FULL_MODE = False

# ─── Attempt all module-level imports ───────────────────────────────────────────
try:
    from fastapi import Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from app.core.config import settings
    from app.core.logging import setup_logging, get_logger
    from app.core.exceptions import AppException
    from app.db.session import init_db
    from app.cache.redis_client import get_redis, close_redis
    from app.services.userbot.manager import userbot_manager
    from app.api.v1 import (
        customers,
        conversations,
        leads,
        content,
        channels,
        accounts,
        knowledge,
        metrics,
        challenges,
    )
    setup_logging()
    logger = get_logger(__name__)
    _FULL_MODE = True
except Exception as _e:
    _import_error = f"{type(_e).__name__}: {_e}"
    print(f"FATAL_IMPORT_ERROR: {_import_error}", file=sys.stderr, flush=True)
    class _FakeSettings:
        APP_NAME = "TelegramAgent"
        APP_ENV = "production"
        DEBUG = False
        DATABASE_SSL = False
        DATABASE_URL = ""
        GROQ_API_KEY = ""
        ADMIN_BOT_TOKEN = ""
        REDIS_URL = ""
        cors_origins_list = ["*"]
    settings = _FakeSettings()
    import logging as _logging
    logger = _logging.getLogger(__name__)

_userbot_task: asyncio.Task | None = None
_auto_poster_task: asyncio.Task | None = None
_rdp_pool_task: asyncio.Task | None = None
_challenge_task: asyncio.Task | None = None
_maintenance_task: asyncio.Task | None = None
_bg_init_task: asyncio.Task | None = None
_keep_alive_task: asyncio.Task | None = None

# Reduced to 5 min — Render free tier sleeps after 15 min of inactivity.
# Keeping it at 5 min gives a 3x safety margin.
KEEP_ALIVE_INTERVAL = 300


async def _keep_alive_loop() -> None:
    """
    Pings own health endpoint every 5 min so Render never spins down.
    Render free tier shuts the process after 15 min of no incoming requests.
    Without this, the userbot disconnects and the account appears offline.

    FIX: Previously exited immediately when RENDER_EXTERNAL_URL was not set,
    leaving Render free to sleep the service. Now falls back to a local
    self-ping via the PORT env var so the loop always runs.
    """
    import httpx
    await asyncio.sleep(30)  # wait for server to fully start first

    # Build candidate URLs in priority order
    ping_urls: list[str] = []
    external = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if external:
        ping_urls.append(f"{external}/api/healthz")

    port = os.environ.get("PORT", "10000")
    ping_urls.append(f"http://localhost:{port}/api/healthz")
    ping_urls.append(f"http://0.0.0.0:{port}/api/healthz")

    logger.info("keep_alive_started", urls=ping_urls, interval_sec=KEEP_ALIVE_INTERVAL)

    while True:
        for url in ping_urls:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(url)
                    logger.info("keep_alive_ping", url=url, status=r.status_code)
                break  # success — no need to try next URL
            except Exception as e:
                logger.warning("keep_alive_ping_failed", url=url, error=str(e))
        await asyncio.sleep(KEEP_ALIVE_INTERVAL)


async def _web_maintenance_loop() -> None:
    """Run essential periodic jobs when Render has no separate ARQ worker.

    The Render service currently runs the web process only. Scheduled posts
    therefore need a small in-process safety net. If REDIS_QUEUE_URL is later
    configured for the dedicated worker, this loop stays idle to avoid running
    jobs twice.
    """
    from app.cache.redis_client import cache_get
    from app.db.session import AsyncSessionLocal
    from app.services.channel.scheduler import process_scheduled_posts

    worker_configured = bool((settings.REDIS_QUEUE_URL or "").strip())
    if worker_configured:
        logger.info("web_maintenance_scheduler_idle_worker_configured")
        return

    logger.info("web_maintenance_scheduler_started", interval_sec=60)
    last_metrics_at = 0.0
    last_health_at = 0.0
    last_daily_job_slot: str | None = None

    while True:
        try:
            if not await cache_get("system:posting_paused"):
                async with AsyncSessionLocal() as session:
                    published = await process_scheduled_posts(session)
                if published:
                    logger.info("web_scheduled_posts_processed", published=published)

            now = datetime.now(timezone.utc)
            monotonic_now = time.monotonic()

            if monotonic_now - last_metrics_at >= 300:
                from app.workers.tasks.monitoring import task_collect_metrics
                await task_collect_metrics(None)
                last_metrics_at = monotonic_now

            if monotonic_now - last_health_at >= 1800:
                from app.workers.tasks.monitoring import task_system_health_check
                await task_system_health_check(None)
                last_health_at = monotonic_now

            daily_slot = f"{now.date().isoformat()}:{now.hour}"
            if now.minute == 0 and now.hour in {9, 14, 18} and daily_slot != last_daily_job_slot:
                from app.workers.tasks.followup import task_process_followups
                await task_process_followups(None)
                last_daily_job_slot = daily_slot

            learning_slot = f"learning:{now.date().isoformat()}"
            if now.hour == 3 and now.minute == 0 and last_daily_job_slot != learning_slot:
                from app.workers.tasks.learning import task_analyze_conversations
                await task_analyze_conversations(None)
                last_daily_job_slot = learning_slot
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("web_maintenance_scheduler_failed", error=str(exc))

        await asyncio.sleep(60)


async def _timed(coro, name: str, timeout: float) -> bool:
    global _startup_errors
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return True
    except asyncio.TimeoutError:
        msg = f"{name}: timed out after {timeout}s"
        _startup_errors.append(msg)
        print(f"STARTUP_TIMEOUT {msg}", file=sys.stderr, flush=True)
        return False
    except Exception as e:
        msg = f"{name}: {type(e).__name__}: {e}"
        _startup_errors.append(msg)
        print(f"STARTUP_ERROR {msg}", file=sys.stderr, flush=True)
        return False


async def _background_init() -> None:
    global _userbot_task, _auto_poster_task, _challenge_task

    await _timed(init_db(), "init_db", 15.0)

    userbot_ok = await _timed(userbot_manager.start(), "userbot", 30.0)
    if userbot_ok:
        _userbot_task = asyncio.create_task(userbot_manager.run_until_disconnected())

    try:
        from app.services.channel.publisher import set_userbot_manager as set_publisher_manager
        set_publisher_manager(userbot_manager)
    except Exception as e:
        _startup_errors.append(f"publisher: {e}")

    await _timed(_setup_admin_bot(), "admin_bot", 60.0)
    try:
        from app.services.content.desktop_image_generator import check_desktop_assets
        await check_desktop_assets()
    except Exception as e:
        _startup_errors.append(f"desktop_image_assets: {e}")

    try:
        from app.services.challenges.public_bot import setup_public_bot
        await _timed(setup_public_bot(), "public_bot", 30.0)
    except Exception as e:
        _startup_errors.append(f"public_bot: {e}")

    try:
        # Start AFTER public_bot so get_public_bot_username() already returns
        # the real username — the first challenge announcement link will be
        # correct (https://t.me/<bot>?start=challenge_<slug>).
        from app.services.challenges.service import run_challenge_scheduler
        _challenge_task = asyncio.create_task(run_challenge_scheduler())
    except Exception as e:
        _startup_errors.append(f"challenge_scheduler: {e}")

    try:
        from app.services.channel.auto_poster import run_auto_poster
        _auto_poster_task = asyncio.create_task(run_auto_poster(userbot_manager))
    except Exception as e:
        _startup_errors.append(f"auto_poster: {e}")

    try:
        from app.services.scanner.rdp_scanner import run_rdp_pool_builder
        _rdp_pool_task = asyncio.create_task(run_rdp_pool_builder())
    except Exception as e:
        _startup_errors.append(f"rdp_pool_builder: {e}")

    if _startup_errors:
        print(f"BACKGROUND_INIT_ERRORS: {_startup_errors}", file=sys.stderr, flush=True)
    else:
        print("BACKGROUND_INIT_COMPLETE: all services started", file=sys.stderr, flush=True)


async def _setup_admin_bot() -> None:
    try:
        from app.services.admin_bot.bot import setup_admin_bot
        await setup_admin_bot(userbot_manager)
    except Exception as e:
        _startup_errors.append(f"admin_bot: {e}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bg_init_task, _startup_errors, _keep_alive_task
    _startup_errors = []

    if not _FULL_MODE:
        msg = f"import_failed: {_import_error}"
        _startup_errors.append(msg)
        print(f"STARTUP_ERROR {msg}", file=sys.stderr, flush=True)
        yield
        return

    logger.info("application_starting", env=settings.APP_ENV)

    await _timed(get_redis(), "redis", 3.0)

    # Start keep-alive loop immediately so Render never sleeps
    _keep_alive_task = asyncio.create_task(_keep_alive_loop())
    _maintenance_task = asyncio.create_task(_web_maintenance_loop())

    _bg_init_task = asyncio.create_task(_background_init())

    logger.info("application_ready_serving")
    yield

    # ─── Shutdown ────────────────────────────────────────────────────────────────
    if not _FULL_MODE:
        return
    logger.info("application_shutting_down")

    for task in (_keep_alive_task, _maintenance_task, _bg_init_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    for task in (_rdp_pool_task, _auto_poster_task, _userbot_task, _challenge_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    try:
        await userbot_manager.stop()
    except Exception:
        pass
    try:
        from app.services.admin_bot.bot import shutdown_admin_bot
        await shutdown_admin_bot()
    except Exception:
        pass
    try:
        from app.services.challenges.public_bot import shutdown_public_bot
        await shutdown_public_bot()
    except Exception:
        pass
    try:
        await close_redis()
    except Exception:
        pass
    logger.info("application_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

if _FULL_MODE:
    try:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.exception_handler(AppException)
        async def app_exception_handler(request: Request, exc: AppException):
            return JSONResponse(
                status_code=400,
                content={"error": exc.code, "message": exc.message},
            )

        @app.exception_handler(Exception)
        async def generic_exception_handler(request: Request, exc: Exception):
            logger.error("unhandled_exception", error=str(exc), path=request.url.path)
            return JSONResponse(
                status_code=500,
                content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
            )

        @app.post("/tg-api/admin-bot/webhook")
        async def admin_bot_webhook(request: Request):
            try:
                update_data = await request.json()
                from app.services.admin_bot.bot import process_update
                await process_update(update_data)
            except Exception as e:
                logger.error("webhook_processing_error", error=str(e))
            return {"ok": True}

        @app.post("/tg-api/public-bot/webhook")
        async def public_bot_webhook(request: Request):
            try:
                update_data = await request.json()
                from app.services.challenges.public_bot import process_update
                await process_update(update_data)
            except Exception as e:
                logger.error("public_bot_webhook_processing_error", error=str(e))
            return {"ok": True}

        API_PREFIX = "/api/v1"
        app.include_router(customers.router, prefix=API_PREFIX)
        app.include_router(conversations.router, prefix=API_PREFIX)
        app.include_router(leads.router, prefix=API_PREFIX)
        app.include_router(content.router, prefix=API_PREFIX)
        app.include_router(channels.router, prefix=API_PREFIX)
        app.include_router(accounts.router, prefix=API_PREFIX)
        app.include_router(knowledge.router, prefix=API_PREFIX)
        app.include_router(metrics.router, prefix=API_PREFIX)
        app.include_router(challenges.router, prefix=API_PREFIX)
    except Exception as _e2:
        print(f"APP_SETUP_ERROR: {_e2}", file=sys.stderr, flush=True)
        _startup_errors.append(f"app_setup: {_e2}")


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/api/startup-status")
async def startup_status():
    bg_done = _bg_init_task.done() if _bg_init_task else None
    return {
        "status": "degraded" if (_startup_errors or _import_error) else "ok",
        "import_error": _import_error,
        "startup_errors": _startup_errors,
        "full_mode": _FULL_MODE,
        "background_init_complete": bg_done,
        "env": {
            "APP_ENV": settings.APP_ENV,
            "DATABASE_URL_set": bool(settings.DATABASE_URL),
            "GROQ_KEY_set": bool(settings.GROQ_API_KEY),
            "ADMIN_TOKEN_set": bool(settings.ADMIN_BOT_TOKEN),
            "PUBLIC_BOT_TOKEN_set": bool(settings.public_bot_token),
            "XAI_KEY_set": bool(settings.XAI_API_KEY),
            "REDIS_URL": settings.REDIS_URL,
            "RENDER_EXTERNAL_URL": os.environ.get("RENDER_EXTERNAL_URL", "not set"),
        },
    }


@app.api_route("/", methods=["GET", "HEAD"])
async def health_root():
    return {"status": "ok", "app": settings.APP_NAME}


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
