import json
import os
import urllib.parse
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.server import app
from app.tools.email_tools import (
    email_get_account,
    email_link_google_oauth,
    _refresh_google_token_if_needed,
    _trash_gmail_api_message,
    email_bulk_cleanup,
)
from app.tools.calendar_tools import _get_active_google_access_token

client = TestClient(app)


def test_google_auth_status_unconfigured():
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
        res = client.get("/api/auth/google/status")
        assert res.status_code == 200
        data = res.json()
        assert data["configured"] is False


def test_google_auth_status_configured():
    with patch.dict(
        os.environ,
        {
            "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "test-secret",
            "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/auth/google/callback",
        },
    ):
        res = client.get("/api/auth/google/status")
        assert res.status_code == 200
        data = res.json()
        assert data["configured"] is True
        assert data["client_id"] == "test-client-id.apps.googleusercontent.com"
        assert data["redirect_uri"] == "http://localhost:8000/api/auth/google/callback"


def test_google_login_missing_client_id_raises_400():
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
        res = client.get("/api/auth/google/login", follow_redirects=False)
        assert res.status_code == 400
        assert "GOOGLE_CLIENT_ID" in res.json()["detail"]


def test_google_login_generates_correct_oauth_url_and_scopes():
    client_id = "test-client-123.apps.googleusercontent.com"
    with patch.dict(
        os.environ,
        {
            "GOOGLE_CLIENT_ID": client_id,
            "GOOGLE_CLIENT_SECRET": "GOCSPX-secret",
            "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/auth/google/callback",
        },
    ):
        res = client.get("/api/auth/google/login", follow_redirects=False)
        assert res.status_code == 302
        redirect_url = res.headers["location"]
        assert redirect_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")

        parsed = urllib.parse.urlparse(redirect_url)
        params = urllib.parse.parse_qs(parsed.query)

        assert params["client_id"][0] == client_id
        assert params["redirect_uri"][0] == "http://localhost:8000/api/auth/google/callback"
        assert params["response_type"][0] == "code"
        assert params["access_type"][0] == "offline"
        assert params["prompt"][0] == "consent"

        scopes = params["scope"][0].split(" ")
        assert "openid" in scopes
        assert "email" in scopes
        assert "profile" in scopes
        assert "https://www.googleapis.com/auth/gmail.modify" in scopes
        assert "https://www.googleapis.com/auth/gmail.send" in scopes
        assert "https://www.googleapis.com/auth/calendar.events" in scopes


def test_google_callback_handles_error():
    res = client.get(
        "/api/auth/google/callback?error=access_denied", follow_redirects=False
    )
    assert res.status_code == 302
    assert "google_error=access_denied" in res.headers["location"]


def test_google_callback_successful_exchange_and_account_linking():
    fake_token_response = json.dumps({
        "access_token": "ya29.fake-live-access-token",
        "refresh_token": "1//fake-live-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }).encode("utf-8")

    fake_userinfo_response = json.dumps({
        "email": "developer.real@gmail.com",
        "name": "Developer Real",
        "verified_email": True,
    }).encode("utf-8")

    def mock_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "oauth2.googleapis.com/token" in url:
            mock_resp.read.return_value = fake_token_response
        elif "oauth2/v2/userinfo" in url:
            mock_resp.read.return_value = fake_userinfo_response
        elif "gmail/v1/users/me/messages" in url:
            mock_resp.read.return_value = json.dumps({"messages": []}).encode("utf-8")
        else:
            mock_resp.read.return_value = b"{}"
        return mock_resp

    with patch.dict(
        os.environ,
        {
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/auth/google/callback",
        },
    ):
        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            res = client.get(
                "/api/auth/google/callback?code=fake-auth-code-12345",
                follow_redirects=False,
            )
            assert res.status_code == 302
            loc = res.headers["location"]
            assert "google_auth=success" in loc
            assert "developer.real%40gmail.com" in loc or "developer.real@gmail.com" in loc

    # Check connected account state in SQLite
    acc = email_get_account()
    assert acc["connected"] is True
    assert acc["account_type"] == "google_oauth"
    assert acc["email"] == "developer.real@gmail.com"
    assert acc["is_oauth"] is True


def test_calendar_inherits_google_oauth_token():
    # Link test account
    email_link_google_oauth(
        email_address="calendar.user@gmail.com",
        access_token="ya29.calendar-test-token",
        refresh_token="1//calendar-refresh-token",
        expires_in=3600,
    )

    token = _get_active_google_access_token()
    assert token == "ya29.calendar-test-token"


def test_google_token_refresh_flow():
    email_link_google_oauth(
        email_address="refresh.user@gmail.com",
        access_token="old-expired-token",
        refresh_token="valid-refresh-token",
        expires_in=-100,  # expired in the past
    )

    fake_refresh_response = json.dumps({
        "access_token": "ya29.brand-new-refreshed-token",
        "expires_in": 3600,
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = fake_refresh_response

    with patch.dict(
        os.environ,
        {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
        },
    ):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            refreshed = _refresh_google_token_if_needed({
                "email": "refresh.user@gmail.com",
                "access_token": "old-expired-token",
                "refresh_token": "valid-refresh-token",
                "token_expiry": "2020-01-01T00:00:00",
            })
            assert refreshed == "ya29.brand-new-refreshed-token"


def test_disconnect_google_account_restores_sandbox():
    res = client.post(
        "/api/email/account",
        json={"email": "demo.executive@local.ai", "account_type": "demo"},
    )
    assert res.status_code == 200
    acc = email_get_account()
    assert acc["account_type"] == "demo"
    assert acc["email"] == "demo.executive@local.ai"


def test_gmail_api_trash_invocation():
    account = {
        "email": "test@gmail.com",
        "access_token": "valid-token",
        "refresh_token": "refresh-token",
    }

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.status = 200
    mock_resp.read.return_value = b"{}"

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        ok = _trash_gmail_api_message(account, "msg-12345")
        assert ok is True
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        assert "gmail/v1/users/me/messages/msg-12345/trash" in req.full_url
        assert req.headers["Authorization"] == "Bearer valid-token"
