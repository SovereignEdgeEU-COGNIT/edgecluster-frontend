from biscuit_auth import Authorizer, Biscuit, PublicKey
from datetime import datetime, timezone
import requests
import sys
import re

KEY_PATH = None
public_key = None


def load_key():
    """Load public key from Cognit Frontend for token verification
    """
    global public_key

    try:
        response = requests.get(KEY_PATH)

        if response.status_code != 200:
            raise f"Error {response.status_code}\n{response.json()}"

    except Exception as e:
        detail = f"Cannot load public key for biscuit token authentication from {KEY_PATH}\n{str(e)}"
        sys.stderr.write(detail)
        exit(1)

    public_key_hex_string = response.json()

    public_key = PublicKey.from_hex(public_key_hex_string)


def authorize_token(token64: str) -> list[str]:
    attempted = False

    token = Biscuit.from_base64(token64, public_key)

    def attempt_authorization():
        authorizer = Authorizer("""
        time({now});
        allow if user($u), password($p);
        """,
                                {
                                    'now': datetime.now(tz=timezone.utc)
                                })
        authorizer.add_token(token)
        authorizer.authorize()

    try:
        attempt_authorization()
    except Exception as e:
        if attempted is True:  # maybe the key has been renewed
            raise e

        attempted = True

        load_key()
        attempt_authorization()

    token_body = token.block_source(0)

    credentials: list[str] = []

    # extract credentials from token
    for i in ['user', 'password']:
        match = re.search(rf'{i}\("(.+?)"\);', token_body)

        if match:
            credentials.append(match.group(1))

    return credentials
