"""Minimal HTTP client for the fd-wire entity-layer surface (real endpoints).

Endpoint/field shapes verified against fd-wire on-disk sources (2026-11-03,
read-only recon; sibling repo is truth, never edited from here):

- ``GET  /api/v1/entities/graph``   (``api/fd_wire_api/entities/routes.py``,
  ``get_graph``; console identity via ``require_console_customer_id``)
  → ``{"nodes": [GraphNodeOut], "edges": [GraphEdgeOut]}`` where each node is
  ``{id:int, name:str, description:str|None, pk_columns:[str],
  display_column:str|None, column_notes:{str:str}|None,
  dataset:{id:str, key:str|None, name:str|None, row_count:int|None,
  storage_tier:str|None}}`` and each edge is ``{id:int, from_entity_id,
  from_column, to_entity_id, to_column, kind, label, junction_dataset_id,
  junction_source_column, junction_target_column}``. Empty graph = 200 with
  empty lists (never 404).
- ``GET  /api/v1/entities``        → ``{"entities":[EntityOut,...]}``
- ``PUT  /api/v1/entities/{id}``   → full-replacement update, request body =
  ``EntityCreateIn`` ``{name, dataset_id, pk_columns, description,
  display_column, column_notes}``; errors 404 (foreign/not-found), 409
  (uniqueness), 422 (validation), all with ``detail`` strings.
- relationships have POST/DELETE only — **no update surface**.

Auth (``api/fd_wire_api/console/auth.py``): ``Authorization: Bearer <Logto ID
token>`` — a Logto-issued ID token (ES384/RS256/ES256, verified server-side
against JWKS/iss/aud/exp). There is NO machine-token shortcut on these routes:
no/invalid bearer → 401; server missing FD_WIRE_LOGTO_ISSUER/CLIENT_ID → 503
with the exact missing keys. The token is obtained by the console login flow
(Logto SPA; scopes openid profile email roles offline_access) — this client
does NOT run the OIDC dance; you hand it a token.

Configuration (env):

- ``WIRE_API_BASE``  base URL of the wire API. Production front door is
  ``https://wire.finddatatech.cloud`` (Caddy on cheap-1 reverse-proxies
  ``/api/`` → API NodePort 31883 over the tailscale mesh). A mesh-internal
  caller can also point directly at a node's ``http://<ip>:31883``.
- ``WIRE_ID_TOKEN``  the console bearer token (Logto ID token string).

No token/base configured → the client still constructs, but every request
raises ``WireAuthError`` with an actionable message (fail honestly, never
fabricate a response). ``requests`` is imported lazily so ``import
wire_connector.client`` succeeds in a stdlib-only environment (selfcheck).

Dependency direction: this connector (internal) calls the PUBLIC bench kernel
and the fd-wire API over HTTP. fd-wire and law-bench never depend on this
package — the internal→public edge is the only allowed direction.
"""

from __future__ import annotations

import os
from typing import Any, Optional


class WireClientError(RuntimeError):
    """Base: transport/protocol failure, reported honestly with status/body."""


class WireAuthError(WireClientError):
    """Missing/invalid credentials or server-side auth misconfig (401/503)."""


DEFAULT_BASE_ENV = "WIRE_API_BASE"
DEFAULT_TOKEN_ENV = "WIRE_ID_TOKEN"


def _import_requests():
    try:
        import requests  # noqa: PLC0415 - lazy: keeps stdlib import path alive
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise WireClientError(
            "the 'requests' package is required for live calls "
            "(offline import of wire_connector.client still works)"
        ) from exc
    return requests


class WireClient:
    """Small synchronous client over the wire entity surface (requests-based)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        id_token: Optional[str] = None,
        *,
        timeout: float = 20.0,
        base_env: str = DEFAULT_BASE_ENV,
        token_env: str = DEFAULT_TOKEN_ENV,
    ) -> None:
        self.base_url = (base_url or os.environ.get(base_env) or "").rstrip("/")
        self.id_token = id_token or os.environ.get(token_env) or ""
        self.timeout = timeout
        self.base_env = base_env
        self.token_env = token_env

    # -- plumbing ----------------------------------------------------------

    def _require(self) -> None:
        if not self.base_url:
            raise WireClientError(
                f"no wire API base configured: set {self.base_env} (e.g. "
                "https://wire.finddatatech.cloud) or pass base_url=..."
            )
        if not self.id_token:
            raise WireAuthError(
                f"no bearer id token configured: set {self.token_env} with a "
                "console Logto ID token (login flow: https://wire."
                "finddatatech.cloud/console — wire auth is console-identity "
                "only, no machine token exists on entity routes)"
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.id_token}", "Accept": "application/json"}

    def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        self._require()
        requests = _import_requests()
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method, url, headers=self._headers(), json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise WireClientError(f"{method} {url}: {exc}") from exc
        if resp.status_code == 401:
            raise WireAuthError(
                f"{method} {url} → 401: bearer token rejected (expired, wrong "
                f"audience, or not a wire-console identity): {self._snippet(resp)}"
            )
        if resp.status_code == 503:
            raise WireAuthError(
                f"{method} {url} → 503: wire server lacks its Logto config "
                f"(fail-closed): {self._snippet(resp)}"
            )
        if resp.status_code >= 400:
            raise WireClientError(
                f"{method} {url} → HTTP {resp.status_code}: {self._snippet(resp)}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    @staticmethod
    def _snippet(resp) -> str:
        """Short, desensitized response excerpt (wire details may contain
        names of other parties' rows — keep it bounded)."""
        text = (resp.text or "").strip().replace("\n", " ")
        return text[:240]

    # -- read surface --------------------------------------------------------

    def get_graph(self) -> dict:
        """``GET /api/v1/entities/graph`` → {"nodes": [...], "edges": [...]}."""
        return self._request("GET", "/api/v1/entities/graph")

    def list_entities(self) -> dict:
        """``GET /api/v1/entities`` → {"entities": [...]} (server-side list)."""
        return self._request("GET", "/api/v1/entities")

    # -- write surface (what actually exists upstream — see README gaps) ------

    def update_entity(
        self,
        entity_id: int,
        *,
        name: str,
        dataset_id: str,
        pk_columns: list[str],
        description: Optional[str] = None,
        display_column: Optional[str] = None,
        column_notes: Optional[dict[str, str]] = None,
    ) -> dict:
        """``PUT /api/v1/entities/{id}`` — full replacement of EntityCreateIn.

        Upstream revalidates the whole row (409 uniqueness / 422 validation,
        zero half-writes). NOTE: there is no PATCH and no tier/sensitivity
        field on this surface — see wire-connector/README.md 'contract gaps'.
        """
        body = {
            "name": name,
            "dataset_id": dataset_id,
            "pk_columns": list(pk_columns),
            "description": description,
            "display_column": display_column,
            "column_notes": column_notes,
        }
        return self._request("PUT", f"/api/v1/entities/{entity_id}", json_body=body)


__all__ = ["WireClient", "WireClientError", "WireAuthError"]
