"""Contract generation API routes."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..deps import get_db, get_settings
from ..schemas import (
    ContractBatchRequest,
    ContractBatchResponse,
    ContractContentRequest,
    ContractContentResponse,
    ContractTypeCatalogItem,
    ContractTypeCatalogResponse,
    ScenarioInfo,
    TypeMetadataResponse,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# Contract Content Generation
# ============================================================================

@router.post("/content", response_model=ContractContentResponse)
async def generate_contract_content(
    request: ContractContentRequest,
    db: Any = Depends(get_db),
):
    """Generate contract content from tags.

    This endpoint wraps the MCP contract_content tool, providing HTTP access
    to the tag-driven contract generation system.
    """
    from ...tools.content import contract_content

    try:
        result = await contract_content(
            contract_type=request.contract_type,
            tags=request.tags,
            format=request.format,
            include_current_tags=request.include_current_tags,
            trace_id=request.trace_id,
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
                "trace_id": request.trace_id,
            },
        )


# ============================================================================
# Batch Contract Generation
# ============================================================================

@router.post("/batch", response_model=ContractBatchResponse)
async def generate_contract_batch(
    request: ContractBatchRequest,
    db: Any = Depends(get_db),
):
    """Generate multiple contracts in parallel.

    This endpoint wraps the MCP contract_generate_batch tool, allowing
    batch generation across multiple tag combinations.
    """
    from ...tools.batch import contract_generate_batch

    try:
        result = await contract_generate_batch(
            contract_type=request.contract_type,
            tag_combinations=request.tag_combinations,
            enumerate_all=request.enumerate_all,
            max_concurrent=request.max_concurrent,
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )


# ============================================================================
# Contract Type Catalog
# ============================================================================

@router.get("/types", response_model=ContractTypeCatalogResponse)
async def list_contract_types(
    db: Any = Depends(get_db),
):
    """List all available contract types.

    Returns metadata about all contract types including slot counts,
    clause counts, and scenario availability.
    """
    from ...tools.catalog import contract_type_catalog

    try:
        result = await contract_type_catalog(db=db)
        return {
            "types": result,
            "total": len(result),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )


@router.get("/types/{contract_type}", response_model=TypeMetadataResponse)
async def get_contract_type_metadata(
    contract_type: str,
    db: Any = Depends(get_db),
):
    """Get detailed metadata for a specific contract type.

    Returns comprehensive information about a contract type including
    tag dimensions, scenarios, and assembly readiness.
    """
    from ...tools.catalog import type_metadata

    try:
        result = await type_metadata(contract_type=contract_type, db=db)
        return result
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"Contract type '{contract_type}' not found",
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )
