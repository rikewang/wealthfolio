"""Local-only Wealthfolio API helper; never prints passwords or cookies."""
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


class Wealthfolio:
    def __init__(self):
        self.client = httpx.Client(base_url="http://127.0.0.1:8088/api/v1/", trust_env=False, timeout=90)
        password = (ROOT / ".secrets/local-login-password.txt").read_text().strip()
        self.request("POST", "auth/login", {"password": password})

    def request(self, method, path, body=None, **kwargs):
        response = self.client.request(method, path, json=body, **kwargs)
        if response.is_error:
            # Login response and request body must never be included in error logs.
            detail = response.text[:500] if path != "auth/login" else "authentication failed"
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {detail}")
        return response.json() if response.content else None

    def state(self):
        return self.request("POST", "profiles/get_profile_state", {})

    def select(self, profile_id):
        session = self.request("POST", "profiles/unlock_profile", {"profileId": profile_id})
        self.client.headers["x-wf-profile-scope"] = session["scopeId"]

    def close(self):
        self.client.close()
