from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_memory_service
from app.api.schemas.memory import (
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdateRequest,
    SupersedeMemoryRequest,
)
from app.db.models.memory import MemoryRecord
from app.services.exceptions import (
    InvalidLifecycleTransitionError,
    InvalidMemoryDataError,
    MemoryConflictError,
    MemoryNotFoundError,
)
from app.services.memory_service import MemoryCreateData, MemoryService

router = APIRouter(prefix="/api/v1", tags=["memories"])


def memory_to_response(record: MemoryRecord) -> MemoryResponse:
    return MemoryResponse(
        id=record.id,
        memory_type=record.memory_type,
        status=record.status,
        title=record.title,
        content=record.content,
        source_type=record.source_type,
        asset_id=record.asset_id,
        facility_id=record.facility_id,
        component_id=record.component_id,
        incident_id=record.incident_id,
        source_id=record.source_id,
        observed_at=record.observed_at,
        confidence=record.confidence,
        importance=record.importance,
        is_synthetic=record.is_synthetic,
        tenant_id=record.tenant_id,
        team_id=record.team_id,
        access_roles=record.access_roles or [],
        metadata=record.memory_metadata,
        supersedes_memory_id=record.supersedes_memory_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("/memories", status_code=status.HTTP_201_CREATED, response_model=MemoryResponse)
def create_memory(
    request: MemoryCreateRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    try:
        service_data = MemoryCreateData(
            memory_type=request.memory_type,
            title=request.title,
            content=request.content,
            source_type=request.source_type,
            asset_id=request.asset_id,
            facility_id=request.facility_id,
            component_id=request.component_id,
            incident_id=request.incident_id,
            source_id=request.source_id,
            observed_at=request.observed_at,
            confidence=request.confidence,
            importance=request.importance,
            is_synthetic=request.is_synthetic,
            tenant_id=request.tenant_id,
            team_id=request.team_id,
            access_roles=request.access_roles,
            memory_metadata=request.metadata,
        )
        record = service.create_memory(data=service_data)
        return memory_to_response(record)
    except (InvalidMemoryDataError, MemoryConflictError, InvalidLifecycleTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
def get_memory(
    memory_id: UUID,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    try:
        record = service.get_memory(memory_id)
        return memory_to_response(record)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/memories", response_model=MemoryListResponse)
def list_memories(
    memory_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    facility_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryListResponse:
    records = service.list_memories(
        memory_type=memory_type,
        status=status,
        asset_id=asset_id,
        facility_id=facility_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return MemoryListResponse(
        items=[memory_to_response(record) for record in records],
        total=len(records),
        limit=limit,
        offset=offset,
    )


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
def update_memory(
    memory_id: UUID,
    request: MemoryUpdateRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    patch: dict[str, Any] = {}
    for field_name, value in request.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        internal_field_name = "memory_metadata" if field_name == "metadata" else field_name
        patch[internal_field_name] = value

    try:
        record = service.update_memory(memory_id, patch=patch)
        return memory_to_response(record)
    except (InvalidMemoryDataError, InvalidLifecycleTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/memories/{memory_id}/archive", response_model=MemoryResponse)
def archive_memory(
    memory_id: UUID,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    try:
        record = service.archive_memory(memory_id)
        return memory_to_response(record)
    except (InvalidLifecycleTransitionError, MemoryConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/memories/{memory_id}/dispute", response_model=MemoryResponse)
def dispute_memory(
    memory_id: UUID,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    try:
        record = service.dispute_memory(memory_id)
        return memory_to_response(record)
    except (InvalidLifecycleTransitionError, MemoryConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/memories/{memory_id}/supersede", response_model=dict[str, MemoryResponse])
def supersede_memory(
    memory_id: UUID,
    request: SupersedeMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
) -> dict[str, MemoryResponse]:
    try:
        replacement_data = MemoryCreateData(
            memory_type=request.replacement.memory_type,
            title=request.replacement.title,
            content=request.replacement.content,
            source_type=request.replacement.source_type,
            asset_id=request.replacement.asset_id,
            facility_id=request.replacement.facility_id,
            component_id=request.replacement.component_id,
            incident_id=request.replacement.incident_id,
            source_id=request.replacement.source_id,
            observed_at=request.replacement.observed_at,
            confidence=request.replacement.confidence,
            importance=request.replacement.importance,
            is_synthetic=request.replacement.is_synthetic,
            tenant_id=request.replacement.tenant_id,
            team_id=request.replacement.team_id,
            access_roles=request.replacement.access_roles,
            memory_metadata=request.replacement.metadata,
        )
        old_record, new_record = service.supersede_memory(memory_id, replacement_data)
        return {
            "old_memory": memory_to_response(old_record),
            "replacement": memory_to_response(new_record),
        }
    except (InvalidMemoryDataError, InvalidLifecycleTransitionError, MemoryConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
