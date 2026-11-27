
import json
import os
import re
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


# DISCORD SETTINGS
APPLICATION_ID = "1575698303562293258"
GUILD_ID = "1569834289997021318"
CLAIM_CHANNEL_ID = "1575697457264857228"

# PLAYFAB SETTINGS
PLAYFAB_TITLE_ID = "13CBFD"
REWARD_ITEM_ID = "LMADW."


def env(name, default=None):
    value = os.environ.get(name, default)

    if not value or not str(value).strip():
        raise RuntimeError(
            f"Missing environment variable: {name}"
        )

    return str(value).strip()


def json_bytes(value):
    return json.dumps(value).encode("utf-8")


def api_request(method, url, payload=None, headers=None, timeout=10):
    data = None if payload is None else json_bytes(payload)

    request_headers = {
        "Content-Type": "application/json",
        "User-Agent": "StumpTagRebornClaimBot/1.0",
    }

    if headers:
        request_headers.update(headers)

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=request_headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"HTTP {exc.code}: {detail[:1000]}"
        )


# DISCORD API

def discord_api(method, path, payload=None):
    token = env("DISCORD_BOT_TOKEN")

    return api_request(
        method,
        "https://discord.com/api/v10" + path,
        payload,
        headers={
            "Authorization": f"Bot {token}",
        },
        timeout=10,
    )


# REGISTER /claimdiscord

def register_discord_command():
    command = {
        "name": "claimdiscord",
        "description": "Claim your Stump Tag Reborn reward",
        "type": 1,
    }

    return discord_api(
        "POST",
        f"/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands",
        command,
    )


# VERIFY DISCORD SIGNATURE

def verify_discord_request(headers, body):
    signature = headers.get("X-Signature-Ed25519")
    timestamp = headers.get("X-Signature-Timestamp")

    if not signature or not timestamp:
        return False

    try:
        public_key = env("DISCORD_PUBLIC_KEY")

        VerifyKey(
            bytes.fromhex(public_key)
        ).verify(
            timestamp.encode("utf-8") + body,
            bytes.fromhex(signature),
        )

        return True

    except (ValueError, BadSignatureError, RuntimeError):
        return False


# EDIT THE ORIGINAL PRIVATE RESPONSE

def edit_original_response(application_id, token, content):
    url = (
        f"https://discord.com/api/v10/webhooks/"
        f"{application_id}/{token}/messages/@original"
    )

    return api_request(
        "PATCH",
        url,
        {"content": content},
        timeout=10,
    )


# PRIVATE RESPONSE

def private_message_response(content):
    return {
        "type": 4,
        "data": {
            "content": content,
            "flags": 64,
        },
    }


# READ PLAYER ID FROM MODAL

def get_text_input_value(components, wanted_id):
    for component in components or []:

        if component.get("type") == 1:
            found = get_text_input_value(
                component.get("components", []),
                wanted_id,
            )

            if found is not None:
                return found

        if component.get("custom_id") == wanted_id:
            return component.get("value")

    return None


# GRANT PLAYFAB REWARD

def grant_playfab_item(playfab_id):
    title_id = env(
        "PLAYFAB_TITLE_ID",
        PLAYFAB_TITLE_ID
    )

    secret_key = env("PLAYFAB_SECRET_KEY")

    item_id = env(
        "REWARD_ITEM_ID",
        REWARD_ITEM_ID
    )

    url = (
        f"https://{title_id}.playfabapi.com/"
        "Server/GrantItemsToUsers"
    )

    payload = {
        "ItemGrants": [
            {
                "PlayFabId": playfab_id,
                "ItemId": item_id,
                "Annotation": "Stump Tag Reborn Discord claim",
            }
        ]
    }

    result = api_request(
        "POST",
        url,
        payload,
        headers={
            "X-SecretKey": secret_key,
        },
        timeout=15,
    )

    results = (
        result.get("data", {})
        .get("ItemGrantResults", [])
    )

    if not results:
        raise RuntimeError(
            "PlayFab returned no item grant results."
        )

    if results[0].get("Result") is not True:
        raise RuntimeError(
            f"PlayFab did not grant item {item_id}. "
            f"Result: {results[0].get('Result')}"
        )

    return result


# SEND CONFIRMATION DM

def send_claim_dm(discord_user_id):
    dm = discord_api(
        "POST",
        "/users/@me/channels",
        {
            "recipient_id": str(discord_user_id)
        },
    )

    discord_api(
        "POST",
        f"/channels/{dm['id']}/messages",
        {
            "content": (
                "Thanks for playing Stump Tag Reborn! "
                "Please restart your game"
            )
        },
    )


# PROCESS MODAL SUBMISSION

def process_modal(interaction, player_id):
    try:
        data = interaction.get("data", {})
        custom_id = data.get("custom_id", "")

        original_channel = (
            custom_id.split(":", 1)[1]
            if ":" in custom_id else ""
        )

        if original_channel != CLAIM_CHANNEL_ID:
            edit_original_response(
                interaction["application_id"],
                interaction["token"],
                "This claim can only be completed in the designated claim channel.",
            )
            return

        if not player_id or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}",
            player_id,
        ):
            edit_original_response(
                interaction["application_id"],
                interaction["token"],
                "That Player ID doesn't look valid. Run `/claimdiscord` and try again.",
            )
            return

        # GRANT REWARD
        print("CLAIM STARTED:", player_id)

        grant_playfab_item(player_id)

        print("PLAYFAB REWARD GRANTED:", player_id)

        # GET DISCORD USER ID
        user = interaction.get("member", {}).get("user", {})
        user_id = user.get("id")

        if not user_id:
            user_id = interaction.get("user", {}).get("id")

        # SEND DM
        try:
            if not user_id:
                raise RuntimeError(
                    "Could not find Discord user ID."
                )

            send_claim_dm(user_id)

            message = (
                "Reward granted! I've sent you a DM. "
                "Please restart your game."
            )

        except Exception as dm_error:
            print("DM ERROR:", repr(dm_error))

            message = (
                "Your reward was granted, but I couldn't DM you. "
                "Enable DMs from server members."
            )

        edit_original_response(
            interaction["application_id"],
            interaction["token"],
            message,
        )

        print("CLAIM FINISHED:", player_id)

    except Exception as exc:
        print("CLAIM ERROR:", repr(exc))
        print(traceback.format_exc())

        try:
            edit_original_response(
                interaction["application_id"],
                interaction["token"],
                f"Claim failed: {str(exc)[:300]}",
            )

        except Exception as edit_error:
            print(
                "DISCORD RESPONSE ERROR:",
                repr(edit_error)
            )


# VERCEL HANDLER

class handler(BaseHTTPRequestHandler):

    def _send(self, status, payload=None):
        body = (
            b""
            if payload is None
            else json_bytes(payload)
        )

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.end_headers()

        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._send(
            200,
            {
                "ok": True,
                "service": "Stump Tag Reborn claim bot",
            },
        )

    def do_POST(self):

        # REGISTER COMMAND THROUGH VERCEL
        if "register=1" in self.path:
            try:
                supplied = self.headers.get(
                    "Authorization",
                    ""
                )

                expected = (
                    "Bearer " + env("SETUP_SECRET")
                )

                if supplied != expected:
                    self._send(
                        401,
                        {"error": "Unauthorized"},
                    )
                    return

                result = register_discord_command()

                self._send(
                    200,
                    {
                        "success": True,
                        "command": result,
                    },
                )

            except Exception as exc:
                print("REGISTRATION ERROR:", repr(exc))
                print(traceback.format_exc())

                self._send(
                    500,
                    {"error": str(exc)},
                )

            return

        # READ DISCORD REQUEST
        length = int(
            self.headers.get("Content-Length", "0")
        )

        body = self.rfile.read(length)

        # VERIFY REQUEST SIGNATURE
        if not verify_discord_request(
            self.headers,
            body,
        ):
            self._send(
                401,
                {"error": "Invalid Discord request signature"},
            )
            return

        try:
            interaction = json.loads(
                body.decode("utf-8")
            )

        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(
                400,
                {"error": "Invalid JSON"},
            )
            return

        # DISCORD ENDPOINT VERIFICATION
        if interaction.get("type") == 1:
            self._send(
                200,
                {"type": 1},
            )
            return

        data = interaction.get("data", {})
        interaction_type = interaction.get("type")

        # SLASH COMMAND
        if (
            interaction_type == 2
            and data.get("name") == "claimdiscord"
        ):

            if (
                str(interaction.get("channel_id", ""))
                != CLAIM_CHANNEL_ID
            ):
                self._send(
                    200,
                    private_message_response(
                        "You can only use `/claimdiscord` in the designated claim channel."
                    ),
                )
                return

            # OPEN PRIVATE MODAL
            self._send(
                200,
                {
                    "type": 9,
                    "data": {
                        "custom_id": (
                            f"claimdiscord:{CLAIM_CHANNEL_ID}"
                        ),
                        "title": "Claim your Discord reward",
                        "components": [
                            {
                                "type": 1,
                                "components": [
                                    {
                                        "type": 4,
                                        "custom_id": "player_id",
                                        "label": "Stump Tag Reborn Player ID",
                                        "style": 1,
                                        "min_length": 1,
                                        "max_length": 64,
                                        "placeholder": "Enter your Player ID",
                                        "required": True,
                                    }
                                ],
                            }
                        ],
                    },
                },
            )
            return

        # MODAL SUBMISSION
        if (
            interaction_type == 5
            and str(
                data.get("custom_id", "")
            ).startswith("claimdiscord:")
        ):

            player_id = get_text_input_value(
                data.get("components", []),
                "player_id",
            )

            # IMPORTANT:
            # ACKNOWLEDGE DISCORD IMMEDIATELY.
            # DO NOT MAKE A SEPARATE CALLBACK REQUEST.
            self._send(
                200,
                {
                    "type": 5,
                    "data": {
                        "flags": 64
                    },
                },
            )

            # PROCESS AFTER ACKNOWLEDGEMENT
            process_modal(
                interaction,
                (player_id or "").strip(),
            )

            return

        # UNKNOWN INTERACTION
        self._send(
            200,
            private_message_response(
                "I don't recognize that command."
            ),
        )

    def log_message(self, format, *args):
        return
