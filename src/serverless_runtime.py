import pyone
from fastapi import HTTPException, status
import os
import requests
from requests.auth import HTTPBasicAuth
import json
from decimal import Decimal
import sys

from cognit_models import ExecutionMode

DOCUMENT_TYPES = {
    'APP_REQUIREMENT': 1338,
    'FUNCTION': 1339
}

ERROR_OFFLOAD = "Failed to offload function"

SR_PORT = 8000
LB_MODE = "cpu"

ONE_XMLRPC = None  # Set when importing module
ONEFLOW = None

# The user doesn't control the SR VMs. These VMs shared among every user should be under the control
# of an admin of sorts of the Function Executing group. Could also be oneadmin.
# The user only owns the app_requirements and function documents. SERVERLESS means no server controlled
HOME = os.path.expanduser("~")
ONE_AUTH = f"{HOME}/.one/one_auth"  # Serverless Runtimes owner credentials
BASIC_AUTH = {}

one = None
logger = None


def execute_function(function_id: int, app_req_id: int, parameters: list[str], mode: ExecutionMode):
    document = get_document(function_id, "FUNCTION")
    function = dict(document.TEMPLATE)

    document = get_document(app_req_id, "APP_REQUIREMENT")
    requirement = dict(document.TEMPLATE)
    flavour = requirement["FLAVOUR"]

    logger.debug(function)
    logger.debug(requirement)

    # Get ideal VM based on LB logic
    services = get_runtime_services(flavour)

    logger.debug(services)

    vm_ids = get_sr_vm_ids(services)
    endpoint = get_runtime_endpoint(vm_ids)

    return offload_function(function=function, mode=mode, app_req_id=app_req_id, endpoint=endpoint, params=parameters)


def get_runtime_services(flavour: str) -> list[dict]:
    """Returns a list of active opennebula flow services backing a certain Serverless Runtime Flavour

    Args:
        flavour (str): Serverless Runtime Flavour

    Returns:
        list[dict]: oneflow instances documents
    """
    uri = f"{ONEFLOW}/service"

    logger.info("Getting existing oneflow services")
    response = requests.get(uri, auth=HTTPBasicAuth(
        BASIC_AUTH['user'], BASIC_AUTH['password']))

    if response.status_code != 200:
        logger.error(response.json())
        raise HTTPException(
            status_code=response.status_code, detail="Could not read Serverless Runtime instances")

    services = response.json()
    logger.debug(services)

    flavour_services = []

    for service in services["DOCUMENT_POOL"]["DOCUMENT"]:

        if service["NAME"] == flavour and service["TEMPLATE"]["BODY"]["roles"][0]["name"] == "FAAS" and service["TEMPLATE"]["BODY"]["roles"][0]["cardinality"] > 0:
            flavour_services.append(service)

    if len(flavour_services) == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Could not find Serverless Runtime instances for flavour {flavour}")

    return flavour_services


def get_sr_vm_ids(services: list[dict]) -> list[int]:
    vm_ids = []

    for service in services:
        vms = service["TEMPLATE"]["BODY"]["roles"][0]["nodes"]

        for vm in vms:
            vm_ids.append(vm["deploy_id"])

    return vm_ids


def get_sr_vm_id_by_cpu(sr_vm_ids: list[int]):
    # can be optimized by getting VMs only for the cognit/serverless group
    # this group would only own SR VMs
    # currently it reads every VM in the pool

    logger.info("Reading VMs last monitoring metrics")
    monitoring_entries = validate_call(
        lambda: one.vmpool.monitoring(-2, 0).MONITORING)

    cpu_load = {}

    # get cpu load metrics of each vm in sr_vm_ids
    for vm_monitoring in monitoring_entries:
        cpu = vm_monitoring.CPU

        if cpu is None:
            continue

        vm_id = vm_monitoring.ID

        if vm_id in sr_vm_ids:
            # return first found vm with less than 10% cpu usage
            if cpu < Decimal(10.0):
                return vm_id

            cpu_load[vm_id] = cpu

    logger.debug(cpu_load)

    return min(cpu_load, key=cpu_load.get)  # return vm with lowest cpu_load

# TODO: Best effor. Try next SR VM for flavour if first candidate fails
def get_runtime_endpoint(vm_ids: list[int]):

    # TODO: define LB logic when module is loaded. Generate the function.
    if LB_MODE == "cpu":
        vm_id = get_sr_vm_id_by_cpu(vm_ids)
    else:
        logger.warning(f"Unknown load balance mode '{LB_MODE}'. Using CPU Load Balance mode.")

    logger.info(f"Getting information about VM {vm_id}")
    vm = validate_call(lambda: one.vm.info(vm_id))
    template = dict(vm.TEMPLATE)

    logger.debug(template)

    if 'NIC' not in template:
        logger.error("Serverless Runtime VM does not have NIC")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERROR_OFFLOAD)

    # ip = template['NIC'][0]['IP'] Multiple NIC turns NIC into an array
    # VMs with 1 NIC assumed
    if 'IP' in template["NIC"]:
        ip = template["NIC"]["IP"]
        runtime_endpoint = f"http://{ip}:{SR_PORT}"
    elif 'IP6' in template["NIC"]:
        ip = template["NIC"]["IP6"]
        runtime_endpoint = f"http://[{ip}]:{SR_PORT}"
    else:
        logger.error(f"Serverless Runtime VM '{vm_id}' does not have IP")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERROR_OFFLOAD)

    return runtime_endpoint



# EXAMPLE_FUNCTION = {
#     "fc": "gAWVHAIAAAAAAACMF2Nsb3VkcGlja2xlLmNsb3VkcGlja2xllIwOX21ha2VfZnVuY3Rpb26Uk5QoaACMDV9idWlsdGluX3R5cGWUk5SMCENvZGVUeXBllIWUUpQoSwNLAEsASwNLAktDQwx8AHwBFAB8AhQAUwCUToWUKYwBYZSMAWKUjAFjlIeUjGIvaG9tZS9hYnJvc2EvcmVwb3MvZ2l0aHViLWRldmljZS1ydW50aW1lLXB5L2NvZ25pdC90ZXN0L2ludGVncmF0aW9uL3Rlc3RfaW50ZWdyYXRpb25fU1JfY29udGV4dC5weZSMCmR1bW15X2Z1bmOUS5pDAgwBlCkpdJRSlH2UTk5OdJRSlIwcY2xvdWRwaWNrbGUuY2xvdWRwaWNrbGVfZmFzdJSMEl9mdW5jdGlvbl9zZXRzdGF0ZZSTlGgVfZR9lCiMCF9fbmFtZV9flGgPjAxfX3F1YWxuYW1lX1+UaA+MD19fYW5ub3RhdGlvbnNfX5R9lIwOX19rd2RlZmF1bHRzX1+UTowMX19kZWZhdWx0c19flE6MCl9fbW9kdWxlX1+UjCdpbnRlZ3JhdGlvbi50ZXN0X2ludGVncmF0aW9uX1NSX2NvbnRleHSUjAdfX2RvY19flE6MC19fY2xvc3VyZV9flE6MF19jbG91ZHBpY2tsZV9zdWJtb2R1bGVzlF2UjAtfX2dsb2JhbHNfX5R9lHWGlIZSMC4=",
#     "fc_hash": "83f8679345fd4b5d215f2b8fcd7c7d51b154084494e92b7ca0a8a5ccf64aafe8",
#     "lang": "PY",
#     "params": ["gAVLAi4=", "gAVLAy4=", "gAVLBC4="]
# }

# EXAMPLE_RESPONSE_SYNC = {
#   "ret_code": 0,
#   "res": "gAVLGC4=",
#   "err": null
# }
# EXAMPLE_RESPONSE_ASYNC = {
# {
#     "status": "WORKING",
#     "res": null,
#     "exec_id": {
#         "faas_task_uuid": "ac249cb6-8425-11ef-b968-c297e15a9b8f"
#     }
# }

def offload_function(endpoint: str, function: dict, app_req_id: int, mode: ExecutionMode, params: list[str]):
    """Offload the function execution to the Serverless Runtime instance

    Args:
        endpoint (str): Where the Serverless Runtime Instance is runninr
        function (dict): Function to be executed
        mode (ExecutionMode): sync or async execution
        params (list[str]): Function input parameters

    Returns:
        _type_: Response from the SR App
    """

    # Ideally SR API should handle execution mode as query parameter as well instead of two separate URI
    if mode == "sync":
        url = f"{endpoint}/v1/faas/execute-sync"
    elif mode == "async":
        url = f"{endpoint}/v1/faas/execute-async"

    # function document keys are UPPERCASE in OpenNebula DB, but lowercase on SR model
    function_lowercase = {k.lower(): v for k, v in function.items()}

    function_lowercase["params"] = params
    function_lowercase["app_req_id"] = app_req_id

    logger.info(f"Offloading function to {url}")
    logger.debug(function_lowercase)
    logger.debug(f"Function parameters: {params}")
    logger.debug(f"App Requirements: {app_req_id}")

    try:
        response = requests.post(url=url, data=json.dumps(function_lowercase))
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=ERROR_OFFLOAD)

    if response.status_code != 200:
        logger.error(response.json())
        raise HTTPException(status_code=response.status_code, detail=ERROR_OFFLOAD)

    return response.json()

# Helpers


def create_client():
    global one

    if os.path.exists(ONE_AUTH):
        with open(ONE_AUTH, 'r') as file:
            session = file.read().strip('\n')

            credentials = session.split(":")

            BASIC_AUTH["user"] = credentials[0]
            BASIC_AUTH["password"] = credentials[1]
    else:
        sys.stderr.write(f"The file {ONE_AUTH} does not exist.")
        exit(1)

    one = pyone.OneServer(ONE_XMLRPC, session=session)


def get_document(document_id: int, type_str: str):
    logger.info(f"Getting information about document {document_id}")
    document = validate_call(lambda: one.document.info(document_id))

    type = DOCUMENT_TYPES[type_str]

    if int(document.TYPE) != type:
        error = f"Resource {document_id} is not of type {type_str}"
        logger.error(error)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    return document


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
