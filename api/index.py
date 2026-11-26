import os
import re
import time
import random
import string
from collections import defaultdict

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---- Environment variables (set these on your host, never in the code) ----
META_APP_ID = os.environ.get("1385138534689986", "")
META_APP_SECRET = os.environ.get("c1d6ef3b12409bdeaafafb47013ca8fd", "")
PLAYFAB_TITLE_ID = os.environ.get("178286", "")
PLAYFAB_SECRET_KEY = os.environ.get("MT5IG5XABWMS3P81BOKDWPO3KFKYMHEATFB1UHUXZ4ESD1KCBD", "")
PHOTON_REALTIME_ID = os.environ.get("3714e542-39ab-413f-9a43-4caa35b5aaa9", "")
PHOTON_VOICE_ID = os.environ.get("8f09c9df-0434-4b76-b4a7-f946e88186bd", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")  # protects /admin/check-custom-id

PF_BASE = f"https://178286.playfabapi.com"
USER_ID_RE = re.compile(r"^\d{1,20}$")

# Small in-memory rate limit. On serverless hosts this resets between instances,
# so use your host's rate limiting or Redis for anything serious.
_hits = defaultdict(list)


def rate_limited(ip):
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < 60]
    _hits[ip].append(now)
    return len(_hits[ip]) > 10


def verify_meta_nonce(user_id, nonce):
    """Ask Meta whether this nonce really belongs to this user for our app.
    Nonces are single-use and short-lived. Returns True/False."""
    r = requests.post(
        "https://graph.oculus.com/user_nonce_validate",
        params={
            "access_token": f"OC|{META_APP_ID}|{META_APP_SECRET}",
            "nonce": nonce,
            "user_id": user_id,
        },
        timeout=10,
    )
    return bool(r.json().get("is_valid"))


def playfab_server_login(server_custom_id):
    """Creates the account on first login, returns the same one every time after."""
    r = requests.post(
        f"{PF_BASE}/Server/LoginWithServerCustomId",
        headers={"X-SecretKey": PLAYFAB_SECRET_KEY},
        json={"ServerCustomId": server_custom_id, "CreateAccount": True},
        timeout=10,
    )
    return r.json()


def mark_verified(playfab_id):
    """Flag accounts made through Meta verification. CloudScript / Photon auth
    can refuse any account that lacks this flag."""
    requests.post(
        f"{PF_BASE}/Server/UpdateUserInternalData",
        headers={"X-SecretKey": PLAYFAB_SECRET_KEY},
        json={"PlayFabId": playfab_id, "Data": {"verified": "true"}},
        timeout=10,
    )


def custom_id_login_enabled():
    """Probe with a random ID and CreateAccount=False (can never create an account).
    'Account not found' means the login method itself was accepted => ENABLED.
    Test once with the setting on and off to confirm what PlayFab returns on your title."""
    rand = "probe_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    r = requests.post(
        f"{PF_BASE}/Client/LoginWithCustomID",
        json={"TitleId": PLAYFAB_TITLE_ID, "CustomId": rand, "CreateAccount": False},
        timeout=10,
    )
    j = r.json()
    return j.get("errorCode") == 1001 or j.get("error") == "AccountNotFound"


@app.route("/")
def hello():
    return "CloverTag's goody 2 shoes backend opeennn"


@app.route("/auth/login", methods=["POST"])
def auth_login():
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if rate_limited(ip):
            return jsonify(ok=False, error="rate_limited"), 429

        body = request.get_json(silent=True) or {}
        user_id = body.get("userId")
        nonce = body.get("nonce")
        if not isinstance(user_id, str) or not USER_ID_RE.match(user_id):
            return jsonify(ok=False, error="bad_user_id"), 400
        if not isinstance(nonce, str) or not (10 <= len(nonce) <= 2048):
            return jsonify(ok=False, error="bad_nonce"), 400

        if not verify_meta_nonce(user_id, nonce):
            return jsonify(ok=False, error="meta_verification_failed"), 401

        # Meta user ID is the permanent identity -> permanent PlayFab account
        pf = playfab_server_login(f"meta_{user_id}")

        if pf.get("code") != 200:
            msg = (pf.get("errorMessage") or "").lower()
            if "banned" in msg:
                details = pf.get("errorDetails") or {}
                reason, expires = "", "Indefinite"
                if details:
                    reason, vals = next(iter(details.items()))
                    expires = vals[0] if vals else "Indefinite"
                return jsonify(ok=False, banned=True, banReason=reason, banExpires=expires), 403
            app.logger.error("PlayFab error: %s", pf)
            return jsonify(ok=False, error="playfab_error"), 502

        d = pf["data"]
        mark_verified(d["PlayFabId"])
        return jsonify(
            ok=True,
            newlyCreated=bool(d.get("NewlyCreated")),
            playFabId=d["PlayFabId"],
            sessionTicket=d["SessionTicket"],
            entityToken=d["EntityToken"]["EntityToken"],
            entityId=d["EntityToken"]["Entity"]["Id"],
            entityType=d["EntityToken"]["Entity"]["Type"],
            titleId=PLAYFAB_TITLE_ID,
            photonRealtimeId=PHOTON_REALTIME_ID,
            photonVoiceId=PHOTON_VOICE_ID,
        )
    except Exception as e:
        app.logger.exception(e)
        return jsonify(ok=False, error="server_error"), 500


@app.route("/admin/check-custom-id")
def check_custom_id():
    """Ping this from a cron service (e.g. cron-job.org) every hour with
    ?key=<CRON_SECRET>. Logs a warning if client custom-ID login is still on."""
    if not CRON_SECRET or request.args.get("key") != CRON_SECRET:
        return jsonify(error="forbidden"), 403
    try:
        enabled = custom_id_login_enabled()
    except Exception as e:
        app.logger.exception(e)
        return jsonify(error="probe_failed"), 500
    if enabled:
        app.logger.error("WARNING: Client LoginWithCustomID is ENABLED. Disable it in PlayFab Game Manager.")
        # TODO: send to a Discord/Slack webhook here
    return jsonify(customIdLoginEnabled=enabled)


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 3000)))
