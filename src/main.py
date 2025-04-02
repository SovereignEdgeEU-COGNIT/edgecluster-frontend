#!/usr/bin/env python

from fastapi import FastAPI, status, HTTPException, Header, Path, Query
from fastapi.responses import RedirectResponse
from typing import Annotated
import uvicorn
import logging
import signal

import cognit_conf as conf
import biscuit_token as auth
from cognit_models import ExecutionMode
import cognit_broker
import opennebula

TIMEOUT = 600 # TODO: Make it configurable

logger = logging.getLogger("uvicorn")
if conf.LOG_LEVEL == 'debug':  # uvicorn run log parameter is ignored
    logger.setLevel(logging.DEBUG)

# biscuit auth
auth.KEY_PATH = f'{conf.COGNIT_FRONTEND}/v1/public_key'
auth.load_key()

broker_client = cognit_broker.BrokerClient(endpoint=conf.BROKER, logger=logger)

app = FastAPI(title='Edge Cluster Frontend', version='0.1.0')


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.post("/v1/functions/{id}/execute", status_code=status.HTTP_200_OK)
async def execute_function(
    id: Annotated[int, Path(title="Document ID of the Function")],
    parameters: list[str],
    app_req_id: Annotated[int, Query(title="Document ID of the App Requirement")],
    mode: Annotated[ExecutionMode, Query(title="Execution Mode")],
    token: Annotated[str | None, Header()] = None
) -> dict:

    credentials = authorize(token)

    # create client for reading function related documents
    one_client = opennebula.OpenNebulaClient(
        oned=conf.ONE_XMLRPC, oneflow=conf.ONEFLOW, username=credentials[0], password=credentials[1], logger=logger)

    executioner = cognit_broker.Executioner(
        broker_client=broker_client, one_client=one_client)

    result = with_timeout(
        executioner.execute_function,
        function_id=id,
        app_req_id=app_req_id,
        parameters=parameters,
        mode=mode.value
    )

    return result


# What to do with these metrics
@app.post("/v1/device_metrics", status_code=status.HTTP_200_OK)
async def upload_client_metrics(
    metrics: dict,
    token: Annotated[str | None, Header()] = None
):

    authorize(token)


def authorize(token) -> list[str]:
    if token is None:
        message = 'Missing token in header'
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    try:
        return auth.authorize_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


def with_timeout(func: callable, *args, **kwargs):
    """Handle timeouts according to specified timer

    Args:
        func (callable): The function that might time out

    Returns:
        _type_: Whatever the function returns
    """
    # Protect vs possible execution timeouts
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(TIMEOUT)

    try:
        return func(*args, **kwargs)
    finally:
        signal.alarm(0)  # Cancel the timeout


def _timeout_handler(signum, frame):
    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail="Function execution timed out"
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host=conf.HOST, port=conf.PORT,
                reload=False, log_level=conf.LOG_LEVEL)
