"""Versioned API router."""

from fastapi import APIRouter

from app.api.v1.admin_users import router as admin_users_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bank_config import router as bank_config_router
from app.api.v1.beneficiaries import router as beneficiaries_router
from app.api.v1.center_profile import router as center_profile_router
from app.api.v1.files import router as files_router
from app.api.v1.health import router as health_router
from app.api.v1.metadata import router as metadata_router
from app.api.v1.operations import router as operations_router
from app.api.v1.payment_requests import router as payment_requests_router
from app.api.v1.roles import router as roles_router
from app.api.v1.trader_self_service import router as trader_self_service_router
from app.api.v1.traders import router as traders_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(metadata_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(center_profile_router)
api_v1_router.include_router(operations_router)
api_v1_router.include_router(trader_self_service_router)
api_v1_router.include_router(traders_router)
api_v1_router.include_router(admin_users_router)
api_v1_router.include_router(roles_router)
api_v1_router.include_router(files_router)
api_v1_router.include_router(bank_config_router)
api_v1_router.include_router(beneficiaries_router)
api_v1_router.include_router(payment_requests_router)
