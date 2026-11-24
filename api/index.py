import requests
import random
from flask import Flask, jsonify, request
import json
import os
import base64
import hashlib
import secrets
from datetime import datetime, timedelta

class GameInfo:
    def __init__(self):
        self.ApiKey: str = "OC|1385138534689986|c1d6ef3b12409bdeaafafb47013ca8fd"


    def get_auth_headers(self):
        return {"content-type": "application/json", "X-SecretKey": self.SecretKey}


settings = GameInfo()
app = Flask(__name__)

Valid_Package = "com.company.product"

pending_nonces = {}

def AttestationAuthentication(AttestationToken):
    url = (
        "https://graph.oculus.com/platform_integrity/verify"
        f"?token={AttestationToken}&access_token={settings.ApiKey}"
    )

    resp = requests.get(url)
    return resp.json()

@app.route("/api/authenticate/attestation/mothershipAuth", methods=["POST"])
def MotherShipAuth():
    rjson = request.get_json()
    user_id = rjson.get("UserId")
    attestation_token = rjson.get("AttestationToken")
    expected_nonce = pending_nonces.get(user_id)

    if not attestation_token or attestation_token.strip() == "":
        return jsonify({
            "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership authentication attestation token is null or empty.",
            "BanExpirationTime": "Unkown"
        }), 403

    data = AttestationAuthentication(attestation_token)

    if "data" not in data or len(data["data"]) == 0:
        return jsonify({
            "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership authentication responded with a value less then 1, the attestation authentication must return a value greater then 0 and not less then 0, example: 1, 2, 3, 4. But the response is less then 1. eg: the Validation responded with null or empty data.",
            "BanExpirationTime": "Unkown"
        }), 403

    response_data = data["data"][0]

    if response_data.get("message") == "invalid signature":
        return jsonify({
            "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with a invalid attestation token authentication signature, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to you token having an invalid signature.",
            "BanExpirationTime": "Unkown"
        }), 403

    if response_data.get("message") == "token expired":
        return jsonify({
            "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with your attestation token authentication being expired, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to your token being expired.",
            "BanExpirationTime": "Unkown"
        }), 403

    if response_data.get("message") != "success":
        return jsonify({
            "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with your attestation token authentication being a invalid token, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to your token being invalid and not a valid attestation authentication request.",
            "BanExpirationTime": "Unkown"
        }), 403

    claims = response_data.get("claims")
    decoded_bytes = base64.urlsafe_b64decode(claims + "==")
    claims_json = json.loads(decoded_bytes)

    request_details = claims_json.get("request_details", {})
    app_state = claims_json.get("app_state", {})
    device_state = claims_json.get("device_state", {})
    device_ban = claims_json.get("device_ban", {})
    security_state = claims_json.get("device_state", {})

    unique_id = device_state.get("unique_id") if device_state else None
    device_integrity_state = device_state.get("device_integrity_state") if device_state else None
    StoreRecognized = app_state.get("app_integrity_state") if app_state else None
    securityUpdate = security_state.get("security_update_pending_days") if security_state else None
    packageId = app_state.get("package_id") if app_state else None
    Sha256Sig = app_state.get("package_cert_sha256_digest") if app_state else None
    device_ban_status = device_ban.get("is_banned") if device_ban else False

    if unique_id is None or device_integrity_state is None or StoreRecognized is None or packageId is None or Sha256Sig is None:
            return jsonify({
                "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with no data. the data must be greater then 0, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to the authentication response return is null or empty or less then 1.",
                "BanExpirationTime": "Unkown"
            }), 403

    if packageId != Valid_Package:
            return jsonify({
                "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with your package id being a unkown package cert, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to the authentication response returning a unkown package cert.",
                "BanExpirationTime": "Unkown"
            }), 403

    if device_integrity_state != "Advanced":
            return jsonify({
                "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with your device integrity state being untrusted, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to the authentication response returning your device integrity state being untrusted.",
                "BanExpirationTime": "Unkown"
            }), 403

    if StoreRecognized != "StoreRecognized":
            return jsonify({
                "BanMessage": "OCULUS INTEGRITY AUTHENTICATION FAILED. REASON: The mothership attestation authentication responded with your download source being a invalid download director source, please check you are on the latest version of the game. The attestation authentication has refused your authentication request due to the authentication response returning your download source being unrecongnised.",
                "BanExpirationTime": "Unkown"
            }), 403

    return jsonify({
            "Success!": "OCULUS INTEGRITY AUTHENTICATION PASSED. REASON: The mothership attestation authentication responded with your authentication validation being valid"
            })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7080)
