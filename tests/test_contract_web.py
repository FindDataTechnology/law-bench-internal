"""HTML tests for the contract-template web routes (``/contracts``,
``/contracts/{type}``, ``/contracts/{type}/download/{format}``) and the nav link.

The contracts routes are file-backed (they read ``src/contracts`` + the bundled
``output/law_info`` markdown), so these tests use a lightweight DB-free
``TestClient`` - no PostgreSQL fixture is required.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app

SOFFICE_AVAILABLE = shutil.which("soffice") is not None


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_contracts_list(client: TestClient):
    r = client.get("/contracts")
    assert r.status_code == 200
    assert "买卖合同" in r.text
    assert "/contracts/sale" in r.text


def test_contract_detail(client: TestClient):
    r = client.get("/contracts/sale")
    assert r.status_code == 200
    # template body rendered (markdown -> heading)
    assert "<h2>" in r.text or "第一条" in r.text
    # a slot-instruction label is shown
    assert "甲方名称" in r.text
    # a 法律法规 name from the sale answers is shown
    assert "民法典" in r.text
    # download links present
    assert "/contracts/sale/download/docx" in r.text
    assert "/contracts/sale/download/pdf" in r.text
    # generation-principle section is shown
    assert "生成原理" in r.text


def test_contract_detail_unknown_type_404(client: TestClient):
    r = client.get("/contracts/does_not_exist")
    assert r.status_code == 404
    assert "does_not_exist" in r.text


def test_contract_download_docx(client: TestClient):
    r = client.get("/contracts/sale/download/docx")
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers.get("content-type", "")


def test_contract_download_unsupported_format_400(client: TestClient):
    r = client.get("/contracts/sale/download/rtf")
    assert r.status_code == 400


def test_contract_download_unknown_type_404(client: TestClient):
    r = client.get("/contracts/does_not_exist/download/pdf")
    assert r.status_code == 404


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_contract_download_pdf(client: TestClient):
    r = client.get("/contracts/sale/download/pdf")
    assert r.status_code == 200
    assert "application/pdf" in r.headers.get("content-type", "")


def test_contracts_nav_link_present(client: TestClient):
    r = client.get("/contracts")
    assert '/contracts"' in r.text or "合同模板" in r.text
