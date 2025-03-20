#!/usr/bin/env python

from fastapi import FastAPI, status, HTTPException, Header, Path, Query
from fastapi.responses import RedirectResponse
from typing import Annotated
import uvicorn
import logging

import cognit_conf as conf
import biscuit_token as auth
from cognit_models import ExecutionMode
import cognit_broker
import opennebula

logger = logging.getLogger("uvicorn")
if conf.LOG_LEVEL == 'debug':  # uvicorn run log parameter is ignored
    logger.setLevel(logging.DEBUG)

# biscuit auth
auth.KEY_PATH = f'{conf.COGNIT_FRONTEND}/v1/public_key'
auth.load_key()

# cognit admin auth
one_auth = opennebula.get_one_auth()
one_client = opennebula.OpenNebulaClient(
    oned=conf.ONE_XMLRPC, oneflow=conf.ONEFLOW, username=one_auth[0], password=one_auth[1], logger=logger)

executioner = cognit_broker.Executioner(endpoint=conf.BROKER, logger=logger, one=one_client)

app = FastAPI(title='Edge Cluster Frontend', version='0.1.0')

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")

@app.post("/v1/functions/{id}/execute", status_code=status.HTTP_200_OK)
async def execute_function(
    id: Annotated[int, Path(title="Document ID of the Function")],
    parameters: list[str],
    app_req_id: Annotated[int, Query(title="Document ID of the App Requirement")],
    mode: Annotated[ExecutionMode, Query(title="Execution Mode")], # Not needed with broker
    token: Annotated[str | None, Header()] = None
) -> dict:

    authorize(token)

    return executioner.execute_function(function_id=id, app_req_id=app_req_id, parameters=parameters)


# What to do with these metrics
@app.post("/v1/device_metrics", status_code=status.HTTP_200_OK)
async def upload_client_metrics(
    metrics: dict,
    token: Annotated[str | None, Header()] = None
):

    authorize(token)


def authorize(token) -> list:
    if token is None:
        message = 'Missing token in header'
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    try:
        auth.authorize_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host=conf.HOST, port=conf.PORT,
                reload=False, log_level=conf.LOG_LEVEL)
