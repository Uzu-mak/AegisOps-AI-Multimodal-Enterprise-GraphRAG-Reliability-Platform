"""
Work-order import API.

POST /api/v1/imports/work-orders takes the CSV text in a JSON body (the
console reads the file in the browser), so no multipart handling is needed.
``dry_run`` defaults to true: the same call previews what would be created,
superseded or skipped, and the caller repeats it with ``dry_run: false``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_memory_service
from app.core.security import current_principal
from app.ingestion.work_orders import MAX_BYTES, ImportOptions, WorkOrderImportError, run_import
from app.services.exceptions import InvalidMemoryDataError, MemoryConflictError

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


class WorkOrderImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv: str = Field(..., description="Full text of the CSV export, header row first.", max_length=MAX_BYTES)
    file_name: Optional[str] = Field(default=None, max_length=255)
    dry_run: bool = True
    is_synthetic: bool = Field(default=False, description="Mark every record as sample / synthetic data.")
    day_first: bool = Field(default=False, description="Read 03/04/2026 as 3 April instead of March 4.")
    timezone: str = Field(default="UTC", description="IANA time zone for dates without an offset.")
    source_system: str = Field(default="default", min_length=1, max_length=128)
    default_facility_id: Optional[str] = None
    column_map: dict[str, str] = Field(default_factory=dict, description="Canonical field -> CSV column overrides.")


@router.post("/work-orders")
def import_work_orders(request: WorkOrderImportRequest, service=Depends(get_memory_service)) -> dict:
    options = ImportOptions(
        source_system=request.source_system,
        tenant_id=current_principal().tenant_id if current_principal() else None,
        is_synthetic=request.is_synthetic,
        day_first=request.day_first,
        timezone=request.timezone,
        default_facility_id=request.default_facility_id or None,
        column_map=request.column_map,
        file_name=request.file_name,
    )
    try:
        report = run_import(service, request.csv, options, dry_run=request.dry_run)
    except WorkOrderImportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidMemoryDataError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except MemoryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return report
