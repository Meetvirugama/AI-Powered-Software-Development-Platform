import pytest
from uuid import uuid4

# List of all repository-scoped endpoints from your router
ENDPOINTS = [
    ("GET", "/repositories/{id}"),
    ("POST", "/repositories/{id}/sync"),
    ("POST", "/repositories/{id}/search"),
    ("GET", "/repositories/{id}/files"),
    ("GET", "/repositories/{id}/symbols")
]

@pytest.mark.parametrize("method, endpoint_template", ENDPOINTS)
def test_repository_isolation_matrix(client, user_a_token, user_a_repo, user_b_repo, method, endpoint_template):
    """
    Test matrix verifying 200, 403, and 404 responses for repository isolation.
    """
    headers = {"Cookie": f"auth_token={user_a_token}"}
    
    # 1. Expected 200 (or 202 for sync): User A accessing User A's repository
    url_a = endpoint_template.format(id=user_a_repo.id)
    payload = {"query": "test", "top_k": 5} if "search" in url_a else None
    res_a = client.request(method, url_a, headers=headers, json=payload)
    
    assert res_a.status_code in (200, 202) # Sync returns 202

    # 2. Must be 403: User A attempting to access User B's repository
    url_b = endpoint_template.format(id=user_b_repo.id)
    res_b = client.request(method, url_b, headers=headers, json=payload)
    
    assert res_b.status_code == 403

    # 3. Must be 404: User A attempting to access a non-existent repository
    url_missing = endpoint_template.format(id=str(uuid4()))
    res_missing = client.request(method, url_missing, headers=headers, json=payload)
    
    assert res_missing.status_code == 404
