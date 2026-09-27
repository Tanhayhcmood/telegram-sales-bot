from fastapi import APIRouter
from app.api.deps import APIKeyDep
from app.services.monitoring.dashboard import get_dashboard_data
from app.services.monitoring.health import full_health_check
from app.services.monitoring.metrics_collector import collect_system_metrics, get_daily_stats

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/health")
async def health_check():
    return await full_health_check()


@router.get("/system")
async def system_metrics(_: APIKeyDep):
    return await collect_system_metrics()


@router.get("/dashboard")
async def dashboard(_: APIKeyDep):
    return await get_dashboard_data()


@router.get("/daily")
async def daily_stats(_: APIKeyDep):
    return await get_daily_stats()
