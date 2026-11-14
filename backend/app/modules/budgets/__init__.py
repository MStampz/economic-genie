"""Spending overview and budgets (increment 2)."""

from fastapi import APIRouter

from app.modules.budgets import models  # noqa: F401  (registers the tables)
from app.modules.budgets.overview import router as overview_router
from app.modules.budgets.routes import router as budget_router

router = APIRouter()
router.include_router(budget_router)
router.include_router(overview_router)
