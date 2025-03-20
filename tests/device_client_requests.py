#!/usr/bin/env python

import requests
from requests.auth import HTTPBasicAuth
import json

import tests_common

# A working Cognit Frontend is required to
# get the auth token and to have function and app_req previously uploaded

CONF = tests_common.CONF
logger = tests_common.logger
one_auth = tests_common.one_auth

def authenticate(user: str, password: str):
    logger.info(f"Requesting token for {user}")

    uri = f'{CONF["cognit_frontend"]}/v1/authenticate'

    response = requests.post(uri, auth=HTTPBasicAuth(user, password))
    token = response.json()

    inspect_response(response)

    return token


def inspect_response(response: requests.Response):
    logger.debug(f"Response Code: {response.status_code}")
    if response.status_code != 204:
        logger.debug(f"Response Body: {response.json()}")


def execute(token: str, function_id: int, app_req_id: int, mode: str, parameters = list[str]):
    logger.info(f"Executing function {function_id} with requirements {app_req_id} on mode {mode} with parameters {parameters}")

    headers = {"token": token}
    uri = f'{CONF["edge_cluster_frontend"]}/v1/functions/{function_id}/execute'
    qparams = {
        'app_req_id': app_req_id,
        'mode': mode
    }

    response = requests.post(uri, params=qparams, headers=headers, data=json.dumps(parameters))

    inspect_response(response)

# Get biscuit token
token = authenticate(one_auth[0], one_auth[1])

# Execute sync function
sync = CONF['execution']["sync"]

function_id = sync['function_id']
app_req_id = sync['app_req_id']
mode = sync['execution_mode']
params = sync['params']

execute(token=token, function_id=function_id, app_req_id=app_req_id, mode=mode, parameters=params)
