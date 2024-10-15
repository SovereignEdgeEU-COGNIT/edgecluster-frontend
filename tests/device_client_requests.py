#!/usr/bin/env python

import requests
from requests.auth import HTTPBasicAuth
import json
import os

# A working Cognit Frontend is required to
# get the auth token and to have function and app_req previously uploaded

conf_path = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'conf.json')
with open(conf_path, 'r') as file:
    CONF = json.load(file)


def authenticate(user: str, password: str):
    print(f"Requesting token for {user}")

    uri = f'{CONF["cognit_frontend"]}/v1/authenticate'

    response = requests.post(uri, auth=HTTPBasicAuth(user, password))
    token = response.json()

    inspect_response(response)

    return token


def inspect_response(response: requests.Response):
    print(f"Response Code: {response.status_code}")
    if response.status_code != 204:
        print(f"Response Body: {response.json()}")


def execute(token: str, function_id: int, app_req_id: int, mode: str, parameters = list[str]):
    print(f"Executing function {function_id} with requirements {app_req_id} on mode {mode} with parameters {parameters}")

    headers = {"token": token}
    uri = f'{CONF["api_endpoint"]}/v1/functions/{function_id}/execute'
    qparams = {
        'app_req_id': app_req_id,
        'mode': mode
    }

    response = requests.post(uri, params=qparams, headers=headers, data=json.dumps(parameters))

    inspect_response(response)

# Get biscuit token

credentials = CONF['credentials'].split(':')
token = authenticate(credentials[0], credentials[1])

# Execute sync function

sync = CONF['execution']["sync"]

function_id = sync['function_id']
app_req_id = sync['app_req_id']
mode = sync['execution_mode']
params = sync['params']

execute(token=token, function_id=function_id, app_req_id=app_req_id, mode=mode, parameters=params)
