"""Pydantic schemas for HTTP API request/response validation."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Contract Content Schemas
# ============================================================================

class ContractContentRequest(BaseModel):
    """Request schema for generating contract content."""

    contract_type: str = Field(..., description="Contract type key (e.g., 'sale', 'lease')")
    tags: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Tags for contract generation (e.g., {'scenario': '农产品买卖', 'stance': 'balanced'})"
    )
    format: Literal["markdown", "docx", "pdf", "both"] = Field(
        default="markdown",
        description="Output format. 'markdown' returns text only, 'docx'/'pdf'/'both' generate files"
    )
    include_current_tags: bool = Field(
        default=False,
        description="Include current tag vocabulary in response"
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional trace ID for request tracking"
    )


class ContractContentResponse(BaseModel):
    """Response schema for contract content generation."""

    trace_id: str = Field(..., description="Unique trace ID for this request")
    contract_type: str = Field(..., description="Contract type key")
    format: str = Field(..., description="Output format used")
    body_text: str = Field(..., description="Generated contract content")
    slots: List[str] = Field(default_factory=list, description="List of slot names in the contract")
    instructions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Slot filling instructions"
    )
    law_refs: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Referenced laws and regulations"
    )
    tags_used: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tags that were actually used in generation"
    )
    docx_path: Optional[str] = Field(
        default=None,
        description="Path to generated DOCX file (if format includes docx)"
    )
    pdf_path: Optional[str] = Field(
        default=None,
        description="Path to generated PDF file (if format includes pdf)"
    )
    current_tags: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Current tag vocabulary (if include_current_tags=True)"
    )


# ============================================================================
# Contract Batch Schemas
# ============================================================================

class ContractBatchRequest(BaseModel):
    """Request schema for batch contract generation."""

    contract_type: str = Field(..., description="Contract type key")
    tag_combinations: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of tag combinations to generate. If None and enumerate_all=False, generates all valid combinations"
    )
    enumerate_all: bool = Field(
        default=False,
        description="If True, auto-generate all valid tag combinations"
    )
    max_concurrent: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent generation tasks (1-20)"
    )


class ContractBatchItem(BaseModel):
    """Single item in batch generation response."""

    success: bool = Field(..., description="Whether this generation succeeded")
    tags: Dict[str, Any] = Field(..., description="Tags used for this generation")
    contract_type: Optional[str] = Field(default=None, description="Contract type key")
    body_text: Optional[str] = Field(default=None, description="Generated contract content")
    slots: Optional[List[str]] = Field(default=None, description="List of slot names")
    instructions: Optional[List[Dict[str, Any]]] = Field(default=None, description="Slot filling instructions")
    law_refs: Optional[List[Dict[str, Any]]] = Field(default=None, description="Referenced laws")
    tags_used: Optional[Dict[str, Any]] = Field(default=None, description="Tags actually used")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Error details if success=False")


class ContractBatchResponse(BaseModel):
    """Response schema for batch contract generation."""

    trace_id: str = Field(..., description="Unique trace ID for this request")
    contract_type: str = Field(..., description="Contract type key")
    total_requested: int = Field(..., description="Total number of combinations requested")
    success_count: int = Field(..., description="Number of successful generations")
    failure_count: int = Field(..., description="Number of failed generations")
    results: List[ContractBatchItem] = Field(..., description="Results for each combination")
    combinatorial_warning: bool = Field(
        default=False,
        description="Warning if combinatorial explosion detected"
    )
    error: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Error details if tag preparation failed"
    )


# ============================================================================
# Contract Catalog Schemas
# ============================================================================

class ContractTypeCatalogItem(BaseModel):
    """Single contract type in catalog."""

    key: str = Field(..., description="Contract type key")
    zh_name: str = Field(..., description="Chinese name")
    slot_count: int = Field(..., description="Number of slots in template")
    total_base_clauses: int = Field(..., description="Number of base clauses")
    total_tagged_clauses: int = Field(..., description="Number of tagged clauses")
    total_custom_clauses: int = Field(..., description="Number of custom clauses")
    has_scenarios: bool = Field(..., description="Whether this type has scenario-specific clauses")


class ContractTypeCatalogResponse(BaseModel):
    """Response schema for contract type catalog."""

    types: List[ContractTypeCatalogItem] = Field(..., description="List of contract types")
    total: int = Field(..., description="Total number of contract types")


class ScenarioInfo(BaseModel):
    """Scenario information for a contract type."""

    name: str = Field(..., description="Scenario name")
    clause_count: int = Field(..., description="Number of clauses for this scenario")
    has_tagged_clauses: bool = Field(..., description="Whether this scenario has tagged clauses")
    example_clause_ids: List[int] = Field(
        default_factory=list,
        description="Example clause IDs for this scenario"
    )


class TypeMetadataResponse(BaseModel):
    """Response schema for contract type metadata."""

    key: str = Field(..., description="Contract type key")
    zh_name: str = Field(..., description="Chinese name")
    slot_count: int = Field(..., description="Number of slots in template")
    universal_dims: Dict[str, List[str]] = Field(..., description="Universal tag dimensions")
    type_specific_dims: Dict[str, List[str]] = Field(..., description="Type-specific tag dimensions")
    scenarios: List[ScenarioInfo] = Field(..., description="Available scenarios")
    assembly_ready: bool = Field(..., description="Whether this type is ready for assembly")


# ============================================================================
# Tag Combination Schemas
# ============================================================================

class TagCombinationInfo(BaseModel):
    """Information about a single tag combination."""

    tags: Dict[str, Any] = Field(..., description="Tag values for this combination")
    has_tagged_clauses: bool = Field(..., description="Whether tagged clauses exist")
    tagged_clause_count: int = Field(..., description="Number of tagged clauses")
    tagged_clause_ids: List[int] = Field(..., description="IDs of tagged clauses")
    has_custom_clauses: bool = Field(..., description="Whether custom clauses exist")


class TagCombinationsResponse(BaseModel):
    """Response schema for tag combination enumeration."""

    contract_type: str = Field(..., description="Contract type key")
    dimensions: List[str] = Field(..., description="Tag dimensions used")
    combinations: List[TagCombinationInfo] = Field(..., description="List of tag combinations")
    estimated_combinations: int = Field(..., description="Total number of combinations")
    combinatorial_warning: bool = Field(
        default=False,
        description="Warning if combinatorial explosion detected"
    )


# ============================================================================
# Tag Validation Schemas
# ============================================================================

class TagValidateRequest(BaseModel):
    """Request schema for tag validation."""

    tags: Dict[str, Any] = Field(..., description="Tags to validate")
    contract_type: Optional[str] = Field(
        default=None,
        description="Contract type for validation context"
    )


class TagValidateResponse(BaseModel):
    """Response schema for tag validation."""

    valid: bool = Field(..., description="Whether tags are valid")
    cleaned_tags: Dict[str, Any] = Field(..., description="Cleaned/normalized tags")
    errors: List[str] = Field(
        default_factory=list,
        description="Validation error messages"
    )


# ============================================================================
# Error Response Schema
# ============================================================================

class ErrorResponse(BaseModel):
    """Standardized error response schema."""

    error: str = Field(..., description="Error type/name")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details"
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Trace ID for debugging"
    )
