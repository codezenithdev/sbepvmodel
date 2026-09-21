"""Read-only discovery of model results and separately stored TEA analyses."""

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from sbepv.api import state

router = APIRouter(prefix="/api/analysis-library", tags=["analysis library"])


@router.get("")
def list_analyses(
    q: str = Query(default="", max_length=200),
    workflow: Literal["all", "validation", "annual", "technoeconomic"] = "all",
    status: Literal["all", "done", "queued", "running", "error", "cancelled", "interrupted"] = "all",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    return JSONResponse(
        state.AGENT_STORE.list_analysis_library(
            query=q.strip(), workflow=workflow, status=status, offset=offset, limit=limit,
        ),
        headers={"Cache-Control": "private, no-store"},
    )
