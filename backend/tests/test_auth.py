
def test_login_and_dashboard(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@spotwelding.example", "password": "ChangeMe123!"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    dashboard = client.get(
        "/api/v1/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert dashboard.status_code == 200
    assert "total_projects" in dashboard.json()


def test_protected_projects_require_token(client):
    response = client.get("/api/v1/projects")
    assert response.status_code in (401, 403)
