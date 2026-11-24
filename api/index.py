import os
import json
import time
import uuid
import logging
from functools import wraps
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PLAYFAB_TITLE_ID = os.environ.get("PLAYFAB_TITLE_ID", "1626EA")
PLAYFAB_SECRET_KEY = os.environ.get("PLAYFAB_SECRET_KEY", "")

FRIEND_STORE = {}
USER_MAPPING = {}
QUEST_STORE = {}

CHALLENGE_TTL = 300
used_nonces = {}

META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")

def validate_environment():
    missing = []
    if not PLAYFAB_SECRET_KEY:
        missing.append("PLAYFAB_SECRET_KEY")
    if missing:
        logger.warning(f"Missing environment variables: {', '.join(missing)}")

validate_environment()

ONLINE_IMAGE = "https://imgs.search.brave.com/mAFO5ujGrTUVwrK2p-7Go6CEKVnU3tDpmcIOrZb5-N0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMuZ2VuaXVzLmNv/bS9jYmU3ZDQwZTVm/ODE0ZmYyN2YyMzJm/ZTdlZDNiMjEyMC4z/MDB4MzAweDEucG5n"
OFFLINE_IMAGE = "https://imgs.search.brave.com/zt4SEESxldboGwcop7al8XS282qUY96Lwd0dS0UF-1E/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9wcmV2/aWV3LnJlZGQuaXQv/c29tZS1wcmV2aW91/c2x5LXVuc2Vlbi1w/aG90b2dyYXBocy1v/Zi1jYXJ0aS1oYXZl/LXN1cmZhY2VkLXYw/LXc5Ym04cW12Ymdk/ZzEuanBlZz93aWR0/aD05NjAmZm9ybWF0/PXBqcGcmYXV0bz13/ZWJwJnM9NjVmMDc1/NTBjNzZhZmE4ZDFj/YmE0ZWU1OTg0YzBk/YmFhMzc4ZjNmYg"

HTML_PAGE = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MonkeBiz25 Backend</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #000; display: flex; align-items: center; justify-content: center;
    min-height: 100vh; font-family: Arial, sans-serif;
  }}
  .container {{ text-align: center; padding: 20px; }}
  img {{ max-width: 90vw; max-height: 80vh; border-radius: 12px; box-shadow: 0 0 30px rgba(0,0,0,0.5); }}
  .status {{ margin-top: 16px; font-size: 18px; color: #888; }}
  .online {{ color: #4ade80; }}
  .offline {{ color: #f87171; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<div class="container">
  <img id="statusImage" src="{ONLINE_IMAGE}" alt="API Status">
  <p id="statusText" class="status online">API ONLINE</p>
  <p id="errorText" class="status offline hidden">API OFFLINE - CHECK BACKEND</p>
</div>
<script>
(async function() {{
  try {{
    let res = await fetch('/api/Attestation/challenge', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ OculusUserId: "healthcheck" }})
    }});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    let data = await res.json();
    if (!data.ChallengeNonce) throw new Error('Bad response');
  }} catch(e) {{
    document.getElementById('statusImage').src = '{OFFLINE_IMAGE}';
    document.getElementById('statusText').className = 'status offline hidden';
    document.getElementById('errorText').className = 'status offline';
  }}
}})();
</script>
</body>
</html>"""

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    if request.method == "OPTIONS":
        response.status_code = 200
    return response

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400

        playfab_id = data.get("PlayFabId", "").strip()
        playfab_ticket = data.get("PlayFabTicket", "").strip()

        if not playfab_id or not playfab_ticket:
            return jsonify({"error": "PlayFabId and PlayFabTicket required"}), 401

        valid, result = validate_playfab_ticket(playfab_id, playfab_ticket)
        if not valid:
            return jsonify({"error": "Invalid session ticket", "message": result}), 403

        return f(playfab_id, data, *args, **kwargs)
    return decorated

def validate_playfab_ticket(playfab_id, session_ticket):
    try:
        url = f"https://{PLAYFAB_TITLE_ID}.playfabapi.com/Server/AuthenticateSessionTicket"
        headers = {
            "X-SecretKey": PLAYFAB_SECRET_KEY,
            "Content-Type": "application/json"
        }
        body = {"SessionTicket": session_ticket}

        response = requests.post(url, json=body, headers=headers, timeout=10)

        if response.status_code != 200:
            logger.warning(f"Session ticket validation failed: {response.status_code}")
            return False, "Session validation failed"

        data = response.json().get("data", {})
        user_info = data.get("UserInfo", {})
        validated_id = user_info.get("PlayFabId", "")

        if validated_id != playfab_id:
            logger.warning(f"PlayFabId mismatch: {validated_id} != {playfab_id}")
            return False, "PlayFabId mismatch"

        return True, None
    except requests.Timeout:
        return False, "PlayFab API timeout"
    except requests.RequestException as e:
        return False, f"PlayFab request failed: {str(e)[:100]}"

@app.route("/")
def health():
    return HTML_PAGE, 200, {"Content-Type": "text/html"}

@app.route("/api/GetFriends", methods=["POST"])
@require_auth
def get_friends(playfab_id, data):
    register_user_identity(playfab_id, data)
    friends = FRIEND_STORE.get(playfab_id, [])
    return jsonify({
        "Result": friends,
        "StatusCode": 200,
        "Error": None
    })

@app.route("/api/RequestFriend", methods=["POST"])
@require_auth
def request_friend(playfab_id, data):
    my_friend_link_id = data.get("MyFriendLinkId", "").strip()
    friend_friend_link_id = data.get("FriendFriendLinkId", "").strip()

    if not my_friend_link_id or not friend_friend_link_id:
        return jsonify({"error": "MyFriendLinkId and FriendFriendLinkId required"}), 400

    if my_friend_link_id == friend_friend_link_id:
        return jsonify({"error": "Cannot friend yourself"}), 400

    register_user_identity(playfab_id, data)

    target = USER_MAPPING.get(friend_friend_link_id)
    if not target:
        return jsonify({"error": "Target player not found"}), 404

    target_playfab_id = target["playfab_id"]
    target_name = target.get("user_name", "Unknown")

    sender_name = data.get("UserName", "") or USER_MAPPING.get(my_friend_link_id, {}).get("user_name", "Unknown")

    if playfab_id not in FRIEND_STORE:
        FRIEND_STORE[playfab_id] = []
    if target_playfab_id not in FRIEND_STORE:
        FRIEND_STORE[target_playfab_id] = []

    already_friends = any(f["FriendLinkId"] == friend_friend_link_id for f in FRIEND_STORE[playfab_id])
    if already_friends:
        return jsonify({"error": "Already friends"}), 409

    FRIEND_STORE[playfab_id].append({
        "FriendLinkId": friend_friend_link_id,
        "UserName": target_name,
        "RoomId": target.get("room_id", ""),
        "Zone": target.get("zone", ""),
        "Region": target.get("region", "")
    })

    FRIEND_STORE[target_playfab_id].append({
        "FriendLinkId": my_friend_link_id,
        "UserName": sender_name,
        "RoomId": data.get("RoomId", ""),
        "Zone": data.get("Zone", ""),
        "Region": data.get("Region", "")
    })

    logger.info(f"Friend request accepted: {playfab_id} <-> {target_playfab_id}")
    return jsonify({"success": True})

@app.route("/api/RemoveFriend", methods=["POST"])
@require_auth
def remove_friend(playfab_id, data):
    my_friend_link_id = data.get("MyFriendLinkId", "").strip()
    friend_friend_link_id = data.get("FriendFriendLinkId", "").strip()

    if not my_friend_link_id or not friend_friend_link_id:
        return jsonify({"error": "MyFriendLinkId and FriendFriendLinkId required"}), 400

    target = USER_MAPPING.get(friend_friend_link_id)
    if not target:
        return jsonify({"error": "Target player not found"}), 404

    target_playfab_id = target["playfab_id"]

    if playfab_id in FRIEND_STORE:
        FRIEND_STORE[playfab_id] = [
            f for f in FRIEND_STORE[playfab_id]
            if f["FriendLinkId"] != friend_friend_link_id
        ]

    if target_playfab_id in FRIEND_STORE:
        FRIEND_STORE[target_playfab_id] = [
            f for f in FRIEND_STORE[target_playfab_id]
            if f["FriendLinkId"] != my_friend_link_id
        ]

    logger.info(f"Friend removed: {playfab_id} <-> {target_playfab_id}")
    return jsonify({"success": True})

@app.route("/api/GetQuestStatus", methods=["POST"])
@require_auth
def get_quest_status(playfab_id, data):
    quests = QUEST_STORE.get(playfab_id, {
        "dailyPoints": {},
        "weeklyPoints": {},
        "userPointsTotal": 0
    })
    return jsonify({
        "result": {
            "dailyPoints": quests.get("dailyPoints", {}),
            "weeklyPoints": quests.get("weeklyPoints", {}),
            "userPointsTotal": quests.get("userPointsTotal", 0)
        }
    })

@app.route("/api/SetQuestComplete", methods=["POST"])
@require_auth
def set_quest_complete(playfab_id, data):
    quest_id = data.get("QuestId")
    if quest_id is None:
        return jsonify({"error": "QuestId required"}), 400

    if playfab_id not in QUEST_STORE:
        QUEST_STORE[playfab_id] = {
            "dailyPoints": {},
            "weeklyPoints": {},
            "userPointsTotal": 0
        }

    quests = QUEST_STORE[playfab_id]

    is_daily = quest_id >= 1000
    points = 1

    if is_daily:
        day_key = time.strftime("%Y-%m-%d")
        quests["dailyPoints"][day_key] = quests["dailyPoints"].get(day_key, 0) + points
    else:
        week_key = time.strftime("%Y-W%V")
        quests["weeklyPoints"][week_key] = quests["weeklyPoints"].get(week_key, 0) + points

    quests["userPointsTotal"] += points

    logger.info(f"Quest {quest_id} completed for {playfab_id}, total points: {quests['userPointsTotal']}")
    return jsonify({
        "result": {
            "dailyPoints": quests.get("dailyPoints", {}),
            "weeklyPoints": quests.get("weeklyPoints", {}),
            "userPointsTotal": quests.get("userPointsTotal", 0)
        }
    })

def register_user_identity(playfab_id, data):
    friend_link_id = data.get("MyFriendLinkId", "").strip()
    user_name = data.get("UserName", "") or data.get("NickName", "")
    room_id = data.get("RoomId", "")
    zone = data.get("Zone", "")
    region = data.get("Region", "")

    if friend_link_id:
        USER_MAPPING[friend_link_id] = {
            "playfab_id": playfab_id,
            "user_name": user_name,
            "room_id": room_id,
            "zone": zone,
            "region": region
        }

def get_app_access_token():
    if not META_APP_ID or not META_APP_SECRET:
        raise ValueError("META_APP_ID and META_APP_SECRET must be set")
    return f"{META_APP_ID}|{META_APP_SECRET}"

@app.route("/api/Attestation/challenge", methods=["POST"])
def challenge():
    try:
        data = request.get_json(force=True)
        oculus_user_id = data.get("OculusUserId", "").strip()

        if not oculus_user_id:
            return jsonify({"error": "OculusUserId is required"}), 400

        challenge_nonce = str(uuid.uuid4())
        used_nonces[challenge_nonce] = {
            "oculus_user_id": oculus_user_id,
            "created_at": time.time(),
            "used": False
        }

        logger.info(f"Generated challenge for user {oculus_user_id}: {challenge_nonce[:8]}...")
        return jsonify({"ChallengeNonce": challenge_nonce})

    except Exception as e:
        logger.error(f"Challenge error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/Attestation/verify", methods=["POST"])
def verify():
    try:
        data = request.get_json(force=True)
        oculus_user_id = data.get("OculusUserId", "").strip()
        oculus_user_proof = data.get("OculusUserProof", "").strip()
        integrity_token = data.get("IntegrityToken", "").strip()
        challenge_nonce = data.get("ChallengeNonce", "").strip()

        if not all([oculus_user_id, oculus_user_proof, integrity_token, challenge_nonce]):
            return jsonify({
                "Verified": False,
                "ErrorMessage": "Missing required fields: OculusUserId, OculusUserProof, IntegrityToken, ChallengeNonce"
            }), 400

        challenge_data = used_nonces.get(challenge_nonce)
        if challenge_data is None:
            return jsonify({
                "Verified": False,
                "ErrorMessage": "Invalid or expired challenge nonce"
            }), 403

        if challenge_data.get("used"):
            return jsonify({
                "Verified": False,
                "ErrorMessage": "Challenge nonce already used - replay attack detected"
            }), 403

        if time.time() - challenge_data["created_at"] > CHALLENGE_TTL:
            used_nonces.pop(challenge_nonce, None)
            return jsonify({
                "Verified": False,
                "ErrorMessage": "Challenge nonce expired"
            }), 403

        if challenge_data["oculus_user_id"] != oculus_user_id:
            return jsonify({
                "Verified": False,
                "ErrorMessage": "Challenge nonce was issued for a different user"
            }), 403

        logger.info(f"Step 1/3: Validating Oculus user proof for {oculus_user_id}...")
        proof_valid, proof_error = validate_oculus_user_proof(oculus_user_id, oculus_user_proof)
        if not proof_valid:
            used_nonces[challenge_nonce]["used"] = True
            return jsonify({
                "Verified": False,
                "ErrorMessage": f"Oculus identity validation failed: {proof_error}"
            }), 403

        logger.info(f"Step 2/3: Verifying device integrity token...")
        integrity_valid, integrity_result = verify_integrity_token(integrity_token, challenge_nonce)
        if not integrity_valid:
            used_nonces[challenge_nonce]["used"] = True
            return jsonify({
                "Verified": False,
                "ErrorMessage": f"Device integrity verification failed: {integrity_result}"
            }), 403

        used_nonces[challenge_nonce]["used"] = True

        logger.info(f"Step 3/3: Creating PlayFab session for {oculus_user_id}...")
        playfab_session = create_playfab_session(oculus_user_id)

        if playfab_session is None:
            return jsonify({
                "Verified": False,
                "ErrorMessage": "Failed to create PlayFab session"
            }), 500

        response = {
            "Verified": True,
            "SessionTicket": playfab_session["SessionTicket"],
            "EntityToken": playfab_session.get("EntityToken", ""),
            "PlayFabId": playfab_session["PlayFabId"],
            "EntityId": playfab_session.get("EntityId", ""),
            "EntityType": playfab_session.get("EntityType", "title_player_account"),
            "KidAccessToken": "",
            "KidRefreshToken": "",
            "KidUrlBasePath": "",
            "LocationCode": ""
        }

        logger.info(f"Attestation passed for user {oculus_user_id}, PlayFabId: {response['PlayFabId']}")
        return jsonify(response)

    except Exception as e:
        logger.error(f"Verification error: {e}")
        return jsonify({
            "Verified": False,
            "ErrorMessage": "Internal server error during verification"
        }), 500

def validate_oculus_user_proof(user_id, nonce):
    try:
        access_token = get_app_access_token()
        url = "https://graph.oculus.com/user_proof/validate"

        response = requests.post(url, data={
            "access_token": access_token,
            "user_id": user_id,
            "nonce": nonce
        }, timeout=15)

        if response.status_code != 200:
            logger.error(f"Oculus proof validation HTTP {response.status_code}: {response.text[:200]}")
            return False, f"Oculus API returned HTTP {response.status_code}"

        result = response.json()

        if result.get("is_valid"):
            logger.info("Oculus user proof validated successfully")
            return True, None
        else:
            error_msg = result.get("error", {}).get("message", "Invalid user proof")
            logger.warning(f"Oculus user proof invalid: {error_msg}")
            return False, error_msg

    except requests.Timeout:
        return False, "Oculus API timeout"
    except requests.RequestException as e:
        return False, f"Oculus API request failed: {str(e)[:100]}"

def verify_integrity_token(token, expected_nonce):
    try:
        access_token = get_app_access_token()
        url = "https://graph.oculus.com/device_integrity/verify"

        response = requests.post(url, data={
            "access_token": access_token,
            "integrity_token": token
        }, timeout=15)

        if response.status_code != 200:
            logger.error(f"Integrity verification HTTP {response.status_code}: {response.text[:200]}")
            return False, f"Meta verification API returned HTTP {response.status_code}"

        result = response.json()

        if not result.get("is_valid"):
            error_msg = result.get("error", {}).get("message", "Token invalid")
            logger.warning(f"Integrity token invalid: {error_msg}")
            return False, f"Token rejected: {error_msg}"

        payload = result.get("payload", {})

        token_nonce = payload.get("nonce", "")
        if token_nonce != expected_nonce:
            logger.warning(f"Nonce mismatch: expected {expected_nonce[:8]}..., got {token_nonce[:8]}...")
            return False, "Nonce mismatch"

        package_name = payload.get("package_name", "")
        if package_name != "com.MonkeyBiz.ByLice":
            logger.warning(f"Package name mismatch: {package_name}")
            return False, f"Package name mismatch: {package_name}"

        device_integrity = payload.get("device_integrity", "")
        if device_integrity != "MEETS_DEVICE_INTEGRITY":
            logger.warning(f"Device integrity check failed: {device_integrity}")
            return False, f"Device integrity: {device_integrity}"

        app_integrity = payload.get("app_integrity", "")
        if app_integrity not in ("MEETS_APP_INTEGRITY", "PLAY_STORE"):
            logger.warning(f"App integrity check failed: {app_integrity}")
            return False, f"App integrity: {app_integrity}"

        exp = payload.get("exp", 0)
        if time.time() > exp:
            logger.warning("Token expired")
            return False, "Token expired"

        cert_digests = payload.get("package_certificate_hashes", [])
        if not cert_digests:
            logger.warning("No certificate hashes in token")
            return False, "Missing certificate hashes"

        logger.info(
            f"Integrity token verified: device={device_integrity}, "
            f"app={app_integrity}, package={package_name}, "
            f"certs={len(cert_digests)}"
        )
        return True, None

    except requests.Timeout:
        return False, "Meta verification API timeout"
    except requests.RequestException as e:
        return False, f"Meta API request failed: {str(e)[:100]}"

def create_playfab_session(oculus_id):
    try:
        custom_id = f"quest_{oculus_id}"

        url = f"https://{PLAYFAB_TITLE_ID}.playfabapi.com/Server/AuthenticateWithCustomId"
        headers = {
            "X-SecretKey": PLAYFAB_SECRET_KEY,
            "Content-Type": "application/json"
        }
        body = {
            "CustomId": custom_id,
            "CreateAccount": True
        }

        response = requests.post(url, json=body, headers=headers, timeout=15)

        if response.status_code != 200:
            logger.error(f"PlayFab auth HTTP {response.status_code}: {response.text[:300]}")
            try:
                error_data = response.json()
                if error_data.get("code") == 400 and "NotAuthenticated" in str(error_data):
                    logger.error("Invalid PlayFab secret key")
            except (ValueError, KeyError):
                pass
            return None

        result = response.json()
        data = result.get("data", {})

        if not data.get("SessionTicket") or not data.get("PlayFabId"):
            logger.error(f"PlayFab response missing session data: {json.dumps(data)[:200]}")
            return None

        return {
            "SessionTicket": data["SessionTicket"],
            "PlayFabId": data["PlayFabId"],
            "EntityToken": data.get("EntityToken", ""),
            "EntityId": data.get("Entity", {}).get("Id", ""),
            "EntityType": data.get("Entity", {}).get("Type", "title_player_account")
        }

    except requests.Timeout:
        logger.error("PlayFab API timeout")
        return None
    except requests.RequestException as e:
        logger.error(f"PlayFab API error: {e}")
        return None
    except Exception as e:
        logger.error(f"PlayFab session creation error: {e}")
        return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
