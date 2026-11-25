import os
import hmac
import json
import time
import base64
import urllib.request
import urllib.error
import requests
import jwt
from flask import Flask, jsonify, request

app = Flask(__name__)

discord_webhook = "https://discord.com/api/webhooks/1575189310125248535/uN8XGNfS5ftOPL2UP0REpChCbbLBQvJmvYa5XBHCc-CScsSCr6UeIcZem6dA27zJgZQz" # webhook for da status updating if u want dis
game_config_key = "PLZFUNKINGWORK" # !! LONG STRING OF CHARS U GOTTA ALSO PUT IN UR C# THING DM DC IF NEED HELP : DOYOUTHINKOFMESTILL
title_id = "178286"
realtime = "3714e542-39ab-413f-9a43-4caa35b5aaa9"
voice = "8f09c9df-0434-4b76-b4a7-f946e88186bd"
app_id = "1385138534689986"
app_secret = "c1d6ef3b12409bdeaafafb47013ca8fd" # ok so jst to not confuse yall dis isnt pf secret key its the key in ur API page for meta. the 2nd part (longer part) of the app creds.
jwt_secret = "Ilovedilldoes927fh3h8dgyaydfaf9hh2h9h" # jst a string of letters wtv u want
expected_package_name = "com.AnotherDelux.CloverTag"
last_alerts = {}
alert_cd = 1000
last_status_sent = 0
status_interval = 600
last_messages = {}

def send_alert_(thing, reason, cooldown=True, color=None):
    if not discord_webhook or "your new" in discord_webhook.lower():
        app.logger.error("no webhook")
        return False

    now_ = time.time()
    key_ = thing.lower()

    if cooldown and now_ - last_alerts.get(key_, 0) < alert_cd:
        app.logger.info("skippy cd: %s", thing)
        return False

    if color is None:
        color = 0xFF0000 if any(
            word in reason.upper()
            for word in ("DOWN", "BROKEN", "FAILED", "UNAVAILABLE")
        ) else 0x00FF00

    embed_ = {
        "title": "WHAT'S B-B-BUGGING",
        "description": (
            f"**REPORT ON:**\n{thing}\n\n"
            f"**STATUS:**\n{reason}"
        ),
        "color": color,
        "footer": {
            "text": "unty abckedn auth thingy by orixo"
        },
        "timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
    }

    payload_ = json.dumps({
        "embeds": [embed_]
    }).encode("utf-8")

    headers_ = {
        "Content-Type": "application/json",
        "User-Agent": "Ggamey-status/1.0"
    }

    base_url_ = discord_webhook.split("?")[0]

    message_id_ = last_messages.get(key_)
    if message_id_:
        edit_req_ = urllib.request.Request(
            f"{base_url_}/messages/{message_id_}",
            data=payload_,
            headers=headers_,
            method="PATCH"
        )
        try:
            with urllib.request.urlopen(edit_req_, timeout=10) as response_:
                if 200 <= response_.status < 300:
                    last_alerts[key_] = now_
                    app.logger.info("msg dod tje thjingy")
                    return True

        except urllib.error.HTTPError as error_:
            if error_.code == 404:
                app.logger.info("old msg gone bru")
                last_messages.pop(key_, None)
            else:
                body_ = error_.read().decode("utf-8", errors="replace")
                app.logger.error(
                    "webhook edit HTTP %s: %s", error_.code, body_[:500]
                )
                return False

        except Exception:
            app.logger.exception("smh edit failed")
            return False

    post_req_ = urllib.request.Request(
        base_url_ + "?wait=true",
        data=payload_,
        headers=headers_,
        method="POST"
    )

    try:
        with urllib.request.urlopen(post_req_, timeout=10) as response_:
            body_ = response_.read().decode("utf-8", errors="replace")

            if 200 <= response_.status < 300:
                try:
                    last_messages[key_] = json.loads(body_)["id"]
                except Exception:
                    app.logger.warning("couldnt read message id")

                last_alerts[key_] = now_
                app.logger.info(
                    "webhook delivered: HTTP %s", response_.status
                )
                return True

            app.logger.error(
                "webhook returned HTTP %s: %s",
                response_.status,
                body_[:500]
            )

    except urllib.error.HTTPError as error_:
        body_ = error_.read().decode("utf-8", errors="replace")
        app.logger.error(
            "webhook HTTP %s: %s", error_.code, body_[:500]
        )

    except Exception:
        app.logger.exception("smh failed")

    return False


def authorized_():
    supplied_ = request.headers.get("X-Game-Key", "")

    return bool(game_config_key) and hmac.compare_digest(
        supplied_.encode("utf-8"), game_config_key.encode("utf-8")
    )


@app.route("/")
def home_():
    return jsonify({
        "service": "orixos pfauth unity method thingy",
        "status": "online"
    })

@app.route("/api/auth-success", methods=["POST"])
def auth_success_():
    global last_status_sent

    if not authorized_():
        return jsonify({"error": "Unauthorized"}), 401

    now_ = time.time()

    if now_ - last_status_sent < status_interval:
        return jsonify({
            "status": "cooldown",
            "alertSent": False,
            "nextStatusIn": int(status_interval - (now_ - last_status_sent))
        }), 200

    sent_ = send_alert_(
        "Game authentication status",
        "PlayFab authentication is working W aura folkkkk"
    )

    if sent_:
        last_status_sent = time.time()

    return jsonify({
        "status": "sent" if sent_ else "received",
        "alertSent": sent_
    }), 200

@app.route("/api/health", methods=["GET"])
def health_():
    return jsonify({"status": "online"}), 200


@app.route("/api/config", methods=["GET"])
def get_config_():
    if not authorized_():
        return jsonify({"error": "Unauthorized"}), 401

    if not all([title_id, realtime, voice]):
        return jsonify({"error": "Config missing"}), 500

    response_ = jsonify({
        "titleId": title_id,
        "realtime": realtime,
        "voice": voice
    })
    response_.headers["Cache-Control"] = "no-store"
    return response_


@app.route("/api/report", methods=["POST"])
def report_():
    if not authorized_():
        return jsonify({"error": "Unauthorized"}), 401

    data_ = request.get_json(silent=True) or {}
    issue_ = data_.get("issue", "")
    reason_ = data_.get("reason", "")

    allowed_ = {
        "PlayFab login failed",
        "Photon Realtime CCU limit reached",
        "Photon Realtime connection failed",
        "Photon Voice connection failed"
    }

    if issue_ not in allowed_:
        return jsonify({"error": "Unknown issue"}), 400

    if not isinstance(reason_, str):
        return jsonify({"error": "Invalid reason"}), 400

    reason_ = reason_[:500] or "No additional details provided."
    sent_ = send_alert_(issue_, reason_)

    return jsonify({
        "status": "sent" if sent_ else "received",
        "alertSent": sent_
    }), 200


@app.route("/api/monitor", methods=["GET"])
def monitor_():
    if not authorized_():
        return jsonify({"error": "Unauthorized"}), 401

    url_ = "https://status.playfab.com/api/v2/status.json"
    req_ = urllib.request.Request(
        url_,
        headers={"User-Agent": "unity thingy even doe i make apk meth"}
    )

    try:
        with urllib.request.urlopen(req_, timeout=8) as response_:
            status_ = json.loads(response_.read().decode("utf-8"))

        indicator_ = status_.get("status", {}).get(
            "indicator", "unknown"
        )
        description_ = status_.get("status", {}).get(
            "description", "Status unavailable"
        )

        if indicator_ != "none":
            send_alert_(
                "PlayFab may be experiencing an outage",
                f"Official status: {description_}\n"
                f"Status indicator: {indicator_}"
            )

        return jsonify({
            "status": description_,
            "indicator": indicator_
        }), 200

    except Exception as error_:
        send_alert_(
            "PlayFab status check failed",
            "The official status endpoint could not be reached. "
            f"Reason: {str(error_)[:300]}"
        )
        return jsonify({"error": "status check failed"}), 502


@app.route("/api/test-alert", methods=["POST"])
def test_alert_():
    if not authorized_():
        return jsonify({"error": "Unauthorized"}), 401

    sent_ = send_alert_(
        "Test alert",
        "web tets",
        cooldown=False
    )

    if sent_:
        return jsonify({"status": "sent"}), 200

    return jsonify({
        "error": "FAILEDWEFWEFUWEUFUH8WFEI9UQIO0FWO0"
    }), 502

@app.route("/auth/oculus", methods=["POST"])
def auth_oculus():
    data = request.get_json(silent=True) or {}

    user_id = data.get("userId")
    nonce = data.get("nonce")

    if not user_id or not nonce:
        return jsonify({
            "success": False,
            "message": "Missing credentials"
        }), 400

    if not app_id or not app_secret or not jwt_secret:
        return jsonify({
            "success": False,
            "message": "Server not configured"
        }), 500

    access_token = f"OC|{app_id}|{app_secret}"

    try:
        response = requests.post(
            "https://graph.oculus.com/user_nonce_validate",
            json={
                "access_token": access_token,
                "nonce": nonce,
                "user_id": user_id
            },
            timeout=10
        )
        result = response.json()
    except Exception:
        app.logger.exception("oculus nonce check failed")
        return jsonify({
            "success": False,
            "message": "Could not reach Oculus"
        }), 502

    if not result.get("is_valid", False):
        return jsonify({
            "success": False,
            "message": "Invalid Oculus proof"
        }), 401

    now_ = int(time.time())
    token = jwt.encode(
        {
            "uid": user_id,
            "iat": now_,
            "exp": now_ + 3600
        },
        jwt_secret,
        algorithm="HS256"
    )

    return jsonify({
        "success": True,
        "token": token,
        "userId": user_id
    })


@app.route("/verify-attestation", methods=["POST"])
def verify_attestation():
    data = request.get_json(silent=True) or {}

    attestation_token = data.get("attestationToken")

    if not attestation_token:
        return jsonify({
            "success": False
        }), 400

    if not app_id or not app_secret:
        return jsonify({
            "success": False,
            "message": "Server not configured"
        }), 500

    access_token = f"OC|{app_id}|{app_secret}"

    try:
        response = requests.get(
            "https://graph.oculus.com/platform_integrity/verify",
            params={"token": attestation_token, "access_token": access_token},
            timeout=10
        )
        body = response.json()
    except Exception:
        app.logger.exception("attestation check failed")
        return jsonify({
            "success": False,
            "message": "Could not reach Oculus"
        }), 502

    entries = body.get("data") if isinstance(body, dict) else None
    if not entries or not isinstance(entries, list):
        return jsonify({"success": False, "meta": body}), 403

    entry = entries[0] or {}
    if str(entry.get("message", "")).lower() != "success":
        return jsonify({"success": False, "meta": body}), 403
    try:
        claims_b64 = entry.get("claims", "")
        claims = json.loads(
            base64.urlsafe_b64decode(claims_b64 + "=" * (-len(claims_b64) % 4)).decode("utf-8")
        )
    except Exception:
        return jsonify({"success": False, "message": "Bad claims"}), 403

    app_state = claims.get("app_state", {}) or {}
    device_state = claims.get("device_state", {}) or {}
    ban_info = claims.get("device_ban") or {}

    if expected_package_name and app_state.get("package_id") != expected_package_name:
        return jsonify({"success": False, "message": "Package mismatch"}), 403

    if ban_info.get("is_banned"):
        return jsonify({"success": False, "message": "Device banned"}), 403

    if device_state.get("device_integrity_state") == "NotTrusted":
        return jsonify({"success": False, "message": "Device not trusted"}), 403

    return jsonify({
        "success": True,
        "integrityState": device_state.get("device_integrity_state"),
        "appIntegrityState": app_state.get("app_integrity_state")
    })


if __name__ == "__main__":
    app.run()
