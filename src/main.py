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
import scaling_manager

TIMEOUT = 30

logger = logging.getLogger("uvicorn")
if conf.LOG_LEVEL == 'debug':  # uvicorn run log parameter is ignored
    logger.setLevel(logging.DEBUG)

# biscuit auth
auth.KEY_PATH = f'{conf.COGNIT_FRONTEND}/v1/public_key'
auth.load_key()

app = FastAPI(title='Edge Cluster Frontend', version='0.1.0')


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.post("/v1/functions/{id}/execute", status_code=status.HTTP_200_OK)
def execute_function(
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

    # Create a new BrokerClient per request for thread safety
    broker_client = cognit_broker.BrokerClient(endpoint=conf.BROKER, logger=logger)

    executioner = cognit_broker.Executioner(
        broker_client=broker_client, one_client=one_client)

    # Let nginx handle the timeouts. 60 seconds is the default
    result = executioner.execute_function(function_id=id,
                                          app_req_id=app_req_id,
                                          parameters=parameters,
                                          mode=mode.value)

    return result


# What to do with these metrics
@app.post("/v1/device_metrics", status_code=status.HTTP_200_OK)
def upload_client_metrics(
    metrics: dict,
    token: Annotated[str | None, Header()] = None
):

    authorize(token)


@app.post("/v1/scale", status_code=status.HTTP_200_OK)
def scale_service(
    target_cardinality: Annotated[int, Query(title="Desired cardinality for FAAS role")]
) -> dict:
    """Scale the oneflow service to the specified cardinality
    
    This endpoint scales the oneflow service this VM belongs to.
    No authentication needed - uses onegate commands with VM context token.
    
    Args:
        target_cardinality: Target number of VMs for the FAAS role
        
    Returns:
        dict: Service information after scaling operation
    """
    one_client = opennebula.OpenNebulaClient(
        oned=conf.ONE_XMLRPC, 
        oneflow=conf.ONEFLOW, 
        username="dummy",  # Not used for onegate commands
        password="dummy",  # Not used for onegate commands
        logger=logger)
    
    service_info = one_client.get_service_info_onegate()
    
    service_id = service_info['id']
    current_state = int(service_info.get('state', -1))
    
    # Find current FAAS role cardinality
    current_cardinality = 0
    for role in service_info.get('roles', []):
        if role.get('name') == 'FaaS':
            current_cardinality = role.get('cardinality', 0)
            break
    
    logger.info(f"Service ID: {service_id}, State: {current_state}")
    logger.info(f"Current cardinality: {current_cardinality}, Target: {target_cardinality}")
    
    # Determine scaling direction
    if target_cardinality > current_cardinality:
        logger.info(f"Scaling UP from {current_cardinality} to {target_cardinality}")
        final_service_info = scaling_manager.scale_up(one_client, current_cardinality, target_cardinality, logger)
    elif target_cardinality == 0:
        logger.info(f"You cannot scale down to 0 VMs. Scaling down to 1 VM")
        final_service_info = scaling_manager.scale_down(one_client, 1, logger)
    elif target_cardinality < current_cardinality:
        logger.info(f"Scaling DOWN from {current_cardinality} to {target_cardinality}")
        final_service_info = scaling_manager.scale_down(one_client, target_cardinality, logger)
    else:
        logger.info(f"Already at target cardinality {target_cardinality}, no scaling needed")
        final_service_info = service_info
    
    # Extract final state for response
    final_cardinality = 0
    for role in final_service_info.get('roles', []):
        if role.get('name') == 'FaaS':
            final_cardinality = role.get('cardinality', 0)
            break
    
    return {
        "service_id": final_service_info['id'],
        "state": int(final_service_info.get('state', -1)),
        "initial_cardinality": current_cardinality,
        "final_cardinality": final_cardinality,
        "message": "Scaling operation completed successfully"
    }


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
                reload=False, log_level=conf.LOG_LEVEL, workers=conf.WORKERS)
