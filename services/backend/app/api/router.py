"""Versioned API router."""

from fastapi import APIRouter

from app.api.v1.admin_users import router as admin_users_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bank_config import router as bank_config_router
from app.api.v1.bank_exports import router as bank_exports_router
from app.api.v1.bank_result_bundles import router as bank_result_bundles_router
from app.api.v1.beneficiaries import router as beneficiaries_router
from app.api.v1.center_profile import router as center_profile_router
from app.api.v1.evidence_links import router as evidence_links_router
from app.api.v1.files import router as files_router
from app.api.v1.gold_sale_orders import router as gold_sale_orders_router
from app.api.v1.health import router as health_router
from app.api.v1.manual_review_tasks import router as manual_review_tasks_router
from app.api.v1.matching_candidates import router as matching_candidates_router
from app.api.v1.matching_candidates import (
    segment_scoped_router as matching_candidates_segment_router,
)
from app.api.v1.metadata import router as metadata_router
from app.api.v1.operations import router as operations_router
from app.api.v1.payment_attempts import router as payment_attempts_router
from app.api.v1.payment_batches import router as payment_batches_router
from app.api.v1.payment_publications import router as payment_publications_router
from app.api.v1.payment_requests import router as payment_requests_router
from app.api.v1.receipt_segments import router as receipt_segments_router
from app.api.v1.roles import router as roles_router
from app.api.v1.trader_publications import router as trader_publications_router
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
api_v1_router.include_router(payment_batches_router)
# M7 slice 4. Its own prefix rather than a branch of the batch surface, because
# `15_Agent_Implementation_Plan.md:978` makes mark-sent act on an exact export: a batch may have
# had several versions and several exports, and exactly one of them was uploaded to a bank.
api_v1_router.include_router(bank_exports_router)
# M8 slice 1. The other direction from everything above: `bank_exports` is what the centre sends a
# bank, and this is what the bank sends back.
api_v1_router.include_router(bank_result_bundles_router)
# M8 slice 2. No prefix of its own: document 05 puts creation under the bundle and the read under
# `/receipt-segments`, so the router declares both paths rather than pretending they share a root.
api_v1_router.include_router(receipt_segments_router)
# M8 slice 3. The queue M7's G-10 said did not exist, and the first surface in this project that is
# about *work* rather than about money.
api_v1_router.include_router(manual_review_tasks_router)
# M9 slice 1. Two routers for one concept, because document 05 puts the proposal under the segment
# (`:1798`) and both decisions under the candidate (`:1806`, `:1816`). Rewriting either path onto a
# shared prefix would put a route at an address no approved document defines.
api_v1_router.include_router(matching_candidates_router)
api_v1_router.include_router(matching_candidates_segment_router)
# M9 slice 2. The authoritative half: a candidate suggests, an evidence link decides. Its own
# prefix, because document 05 gives it one (`:1824`) rather than nesting it under either side of
# the relationship it records.
api_v1_router.include_router(evidence_links_router)
# M9 slices 3 and 4. The first routes in this project that record money as having moved, and the
# first that change a request's status from what its attempts did rather than from what a person
# said about the request.
api_v1_router.include_router(payment_attempts_router)
# M9 slice 5. Both routes hang off the request rather than off a `/publications` prefix, because
# document 05 puts them there (`:1874`, `:1879`) — and because a publication has no address of its
# own until one of these two creates it.
api_v1_router.include_router(payment_publications_router)
# M9 slice 6. Its own module rather than more routes in `trader_self_service.py`: that file is
# about a trader's own *business*, and this is about a result somebody else produced. They share
# the `/me/trader` prefix because document 05 puts them both there, and `test_trader_surface_
# isolation.py` finds both by reading the routes rather than from a list either could fall off.
api_v1_router.include_router(trader_publications_router)
# M10 slice 1. The other direction of the business: a trader buying gold rather than paying a
# beneficiary. Four of §21.1s eight routes; the rest belong to slices that have states to guard.
api_v1_router.include_router(gold_sale_orders_router)
