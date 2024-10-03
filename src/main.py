#!/usr/bin/env python

from fastapi import FastAPI, status, HTTPException, Header
from fastapi.responses import RedirectResponse
from typing import Annotated, Any, List
import uvicorn

import cognit_conf as conf
import biscuit_token as auth
import serverless_runtime as sr
from cognit_models import Execution, ExecutionMode

auth.KEY_PATH = f'{conf.COGNIT_FRONTEND}/v1/public_key'
auth.load_key()

sr.ONE_XMLRPC = conf.ONE_XMLRPC
sr.create_client()

app = FastAPI(title='Edge Cluster Frontend', version='0.1.0')

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")

@app.post("v1/functions/{id}/execute", status_code=status.HTTP_200_OK)
async def execute_function(
    parameters: list[str],
    app_req_id: int, # not using at the moment
    mode: ExecutionMode,
    token: Annotated[str | None, Header()] = None
) -> int:

    authorize(token)

    sr.function_push(id=id, parameters=parameters, mode=mode)

@app.post("/v1/execute", status_code=status.HTTP_200_OK)

# What to do with these metrics
@app.post("/v1/device_metrics", status_code=status.HTTP_200_OK)
async def upload_client_metrics(
    metrics: dict,
    token: Annotated[str | None, Header()] = None
) -> int:

    authorize(token)

def authorize(token) -> list:
    if token == None:
        message = 'Missing token in header'
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    try:
        facts = auth.authorize_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host=conf.HOST, port=conf.PORT,
                reload=False, log_level=conf.LOG_LEVEL)
