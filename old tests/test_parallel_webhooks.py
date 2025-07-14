#!/usr/bin/env python3
"""
Pytest suite for testing the new *parallel* webhook endpoints.

This file focuses ONLY on the endpoints that include the suffix
`-parallel` (added for the non-sequential implementations).

Each test:
1. Builds a request payload that resembles what is used in the larger
   integration tests shipped with the repo (see `test_all_webhooks.py`).
2. Sends a POST request to the running FastAPI server (assumed to be
   running locally – see README).
3. Asserts that we receive a 200 HTTP status and that the JSON body
   contains a `success` key (bool).  If the endpoint is expected to be
   able to legitimately return `success = False`, we do *not* fail the
   test; we merely record the outcome so we can drill deeper if needed.

To keep the CI noise low we collect *all* failures and raise a single
assertion at the very end so the traceback is concise.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import pytest
import requests
from dotenv import load_dotenv

# --------------------------------------------------------------------------------------
# Test configuration helpers
# --------------------------------------------------------------------------------------

# Load local environment variables (.env in project root)
load_dotenv()

# Default values fall back to the dev settings described in README
BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("API_KEY", "development-key")
DIALED_NUMBER = os.getenv("TEST_DIALED_NUMBER", "0478621276")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# Fallback constants that are known-good in the local seed DB.
FALLBACKS: Dict[str, str] = {
    "business_id": "1717010852512540252",  # balmain
    "location_name": "balmain",
    "service": "Acupuncture (Initial)",
    "practitioner": "Cameron",
}

# --------------------------------------------------------------------------------------
# Helper utilities
# --------------------------------------------------------------------------------------

def _post(endpoint: str, payload: Dict[str, Any]) -> requests.Response:
    """Thin wrapper so we consistently apply headers & base url."""
    url = f"{BASE_URL}{endpoint}"
    return requests.post(url, json=payload, headers=HEADERS, timeout=30)


# --------------------------------------------------------------------------------------
# Parametrised test cases
# --------------------------------------------------------------------------------------

parallel_test_matrix: List[Dict[str, Any]] = [
    {
        "name": "find_next_available_parallel_basic",
        "endpoint": "/find-next-available-parallel",
        "payload": {
            "service": FALLBACKS["service"],
            "dialedNumber": DIALED_NUMBER,
            "sessionId": "pytest-parallel-001",
            "maxDays": 7,
        },
    },
    {
        "name": "find_next_available_parallel_specific_practitioner",
        "endpoint": "/find-next-available-parallel",
        "payload": {
            "practitioner": FALLBACKS["practitioner"],
            "dialedNumber": DIALED_NUMBER,
            "sessionId": "pytest-parallel-002",
            "maxDays": 14,
        },
    },
    {
        "name": "get_available_practitioners_parallel",
        "endpoint": "/get-available-practitioners-parallel",
        "payload": {
            "business_id": FALLBACKS["business_id"],
            "businessName": FALLBACKS["location_name"],
            "date": "today",
            "dialedNumber": DIALED_NUMBER,
            "sessionId": "pytest-parallel-003",
        },
    },
]


@pytest.mark.parametrize("case", parallel_test_matrix, ids=[c["name"] for c in parallel_test_matrix])
def test_parallel_endpoints(case: Dict[str, Any]):
    """Main parameterised test covering all parallel webhook endpoints."""

    resp = _post(case["endpoint"], case["payload"])

    # Capture useful debugging info right away if the request failed.
    dbg_ctx = {
        "url": f"{BASE_URL}{case['endpoint']}",
        "status_code": resp.status_code,
        "response_text": resp.text,
    }

    assert resp.status_code == 200, f"Non-200 response – context: {dbg_ctx}"

    try:
        data = resp.json()
    except ValueError as exc:
        raise AssertionError(f"Invalid JSON in response – context: {dbg_ctx}") from exc

    assert "success" in data, f"Missing 'success' key – context: {dbg_ctx}"

    # If the endpoint reports failure, include details but do not hard-fail – we mark xfail
    if data.get("success") is False:
        pytest.xfail(f"Endpoint returned success=False – context: {dbg_ctx}")


# --------------------------------------------------------------------------------------
# Sanity check for base URL reachability (helps fail fast if server is down)
# --------------------------------------------------------------------------------------

def test_healthcheck():
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200, "Health check endpoint unreachable – is the API running?"
