"""Generation-prompt management tools.

Wrap the local-only prompt CRUD in :mod:`src.eval.prompt_crud`. Prompts are
always locally authored and freely editable (no harbor analog, no read-only
guard). ``NotFoundError`` / ``ConflictError`` / ``ValidationError`` surface as
tool errors.
"""

from __future__ import annotations

import anyio

from ..annotations import annotations_for
from ..server import mcp


@mcp.tool(tags={"prompts"}, annotations=annotations_for("prompt_list"))
async def prompt_list(domain: str | None = None) -> list[dict]:
    """List generation prompts (without the content body).

    Parameters:
        domain: restrict to prompts this domain owns. Omitted lists every
            prompt — which is the historical behaviour and what callers that
            predate the domain dimension rely on.

    Domain ownership lives in ``prompts.domain_id`` (added by change
    ``domain-first-mcp``): NULL means "unowned", which is what every pre-existing
    row is. Filtering here rather than in the kernel keeps the web pages —
    which do not pass a domain — byte-identical.

    Returns ``[{id, name, contract_type, purpose, source, prompt_type,
    description, created_at}]``.
    """
    from src.eval.prompt_crud import list_prompts as _list

    rows = await anyio.to_thread.run_sync(_list)
    if domain is None:
        return rows
    owned = await anyio.to_thread.run_sync(_prompt_ids_for_domain, domain)
    return [r for r in rows if r.get("id") in owned]


def _prompt_ids_for_domain(domain: str) -> set[int]:
    """Ids of prompts owned by ``domain`` (via ``prompts.domain_id``).

    Raises for an unknown domain — an empty set would read as "this domain has
    no prompts", which is a different claim from "there is no such domain".
    """
    from src.bench import workspaces
    from src.eval.db import connect

    conn = connect()
    try:
        row = workspaces.get_domain(conn, domain_key=domain)
        if row is None:
            raise ValueError(f"unknown domain {domain!r}")
        got = conn.execute(
            "SELECT id FROM prompts WHERE domain_id = %s", (row["id"],)
        ).fetchall()
        return {(r["id"] if isinstance(r, dict) else r[0]) for r in got}
    finally:
        conn.close()


@mcp.tool(tags={"prompts"}, annotations=annotations_for("prompt_get"))
async def prompt_get(name: str) -> dict:
    """Fetch a prompt's full record (including ``content``), by name.

    Parameters:
        name: prompt name.

    Returns ``{id, name, contract_type, purpose, content, source, prompt_type,
    description, created_at}``. An unknown name raises a tool error.
    """
    from src.eval.prompt_crud import get_prompt as _get

    return await anyio.to_thread.run_sync(_get, name)


@mcp.tool(tags={"prompts"}, annotations=annotations_for("prompt_create"))
async def prompt_create(
    name: str,
    contract_type: str,
    purpose: str,
    content: str,
    description: str | None = None,
    prompt_type: str | None = None,
) -> dict:
    """Create a local prompt (``source = 'local'``).

    Parameters:
        name: unique prompt name.
        contract_type: contract class key this prompt drafts for.
        purpose: short purpose label.
        content: the drafting instruction text.
        description: optional human description.
        prompt_type: optional type tag (e.g. ``"baseline"``).

    Returns the new prompt record. A duplicate name or blank field raises a
    tool error.
    """
    from src.eval.prompt_crud import create_prompt as _create

    def _go() -> dict:
        return _create(
            name, contract_type, purpose, content,
            description=description, prompt_type=prompt_type,
        )

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"prompts"}, annotations=annotations_for("prompt_update"))
async def prompt_update(
    prompt_id: int,
    name: str,
    contract_type: str,
    purpose: str,
    content: str,
    description: str | None = None,
    prompt_type: str | None = None,
) -> dict:
    """Update a prompt's full record.

    Parameters:
        prompt_id: id of the prompt to update.
        name, contract_type, purpose, content: new values (all required).
        description: new optional description.
        prompt_type: new optional type tag.

    Returns the updated prompt record. An unknown id or a duplicate name raises
    a tool error.
    """
    from src.eval.prompt_crud import update_prompt as _update

    def _go() -> dict:
        return _update(
            prompt_id, name, contract_type, purpose, content,
            description=description, prompt_type=prompt_type,
        )

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"prompts"}, annotations=annotations_for("prompt_delete"))
async def prompt_delete(prompt_id: int) -> dict:
    """Delete a prompt (no child table, nothing cascades).

    Parameters:
        prompt_id: id of the prompt to delete.

    Returns ``{deleted: True, prompt_id}``. An unknown id raises a tool error.
    """
    from src.eval.prompt_crud import delete_prompt as _delete

    await anyio.to_thread.run_sync(_delete, prompt_id)
    return {"deleted": True, "prompt_id": prompt_id}
