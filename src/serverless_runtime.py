from cognit_models import ExecutionMode
import pyone
from fastapi import HTTPException, status
import os
import requests
import json

DOCUMENT_TYPES = {
    'APP_REQUIREMENT': 1338,
    'FUNCTION': 1339
}

# TODO: Serverless Runtime admin credentials.
# The user doesn't control the SR VMs. These VMs shared among every user should be under the control
# of an admin of sorts of the Function Executing group. Could also be oneadmin.
# The user only owns the app_requirements and function documents. SERVERLESS means no server controlled

HOME = os.path.expanduser("~")
ONE_AUTH = f"{HOME}/.one/one_auth" # Serverless Runtimes owner credentials
ONE_XMLRPC = None  # Set when importing module

one = None

def function_push(function_id: int, app_req_id: int, parameters: list[str], mode: ExecutionMode):
    # Get Function document from opennebula
    # Get App Req document from opennebula
    # Get list of compatible SR VMs
    # Get ideal VM based on LB logic
    # Execute function on that SR VM
    pass

# TODO: Update SR to label FLAVOURS_STR
def get_runtimes_vms(flavour: str) -> list[pyone.bindings.VMType93Sub]:
    # sqlite cannot issue full text search
    # Get every RUNNING VM
    flavour_vms = one.vmpool.infoextended(-4, -1, -1, 3, f"VM.USER_TEMPLATE.FLAVOURS_STR={flavour}").VM

    vms = []

    for vm in flavour_vms:
        ut = dict(vm.USER_TEMPLATE)

        if ut['ROLE_NAME'] == 'FAAS':
            vms.append(vm)

    return vms


def get_runtime_endpoints(vms: list[pyone.bindings.VMType93Sub]):
    runtime_endpoints = []

    for vm in vms:
        template = dict(vm.TEMPLATE)
        ip = template['NIC'][0]['IP']

        runtime_endpoints.append(f"http://{ip}:8000")

    return runtime_endpoints



def get_runtime(runtimes: list[str]) -> str:
    pass

# TODO: {'detail': 'Error deserializing function'}
def execute_function(function: dict, mode: ExecutionMode, endpoint: str) -> requests.Response:

    # Ideally SR API should handle execution mode as query parameter as well instead of two separate URI
    if mode == "sync":
        url = f"{endpoint}/v1/faas/execute-sync"
    elif mode == "async":
        url = f"{endpoint}/v1/faas/execute-async"

    return requests.post(url=url, data=json.dumps(function))

# Helpers

def create_client():
    global one

    if os.path.exists(ONE_AUTH):
        with open(ONE_AUTH, 'r') as file:
            session = file.read()
    else:
        print(f"The file {ONE_AUTH} does not exist.")
        exit(1)

    one = pyone.OneServer(ONE_XMLRPC, session=session)

def validate_call(xmlrpc_call):
    try:
        return xmlrpc_call()
    except pyone.OneAuthenticationException as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except pyone.OneAuthorizationException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except pyone.OneNoExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
