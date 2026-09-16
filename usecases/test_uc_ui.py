"""UC11: a person can log in to the clinician UI."""

import requests

from conftest import BASE_URL, OE_PASS, OE_USER


def test_uc11_clinician_login():
    s = requests.Session()
    s.verify = False
    assert s.get(f"{BASE_URL}/interface/login/login.php", params={"site": "default"}, timeout=30).ok

    resp = s.post(
        f"{BASE_URL}/interface/main/main_screen.php",
        params={"auth": "login", "site": "default"},
        data={
            "new_login_session_management": "1",
            "languageChoice": "1",
            "authUser": OE_USER,
            "clearPass": OE_PASS,
        },
        timeout=60,
    )
    assert resp.ok
    assert "interface/main/tabs/main.php" in resp.url, f"login did not reach main screen: {resp.url}"
