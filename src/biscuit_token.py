from biscuit_auth import Authorizer, Biscuit, PublicKey
from datetime import datetime, timezone
import requests
import sys

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


def authorize_token(token64: str) -> str:
    def attempt_authorization():
        token = Biscuit.from_base64(token64, public_key)
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
        load_key()  # maybe the key has been renewed
        attempt_authorization()
