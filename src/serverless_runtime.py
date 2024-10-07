from cognit_models import ExecutionMode
import pyone
from fastapi import HTTPException, status
import os
import requests
from requests.auth import HTTPBasicAuth
import json

DOCUMENT_TYPES = {
    'APP_REQUIREMENT': 1338,
    'FUNCTION': 1339
}
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


def function_push(function_id: int, app_req_id: int, parameters: list[str], mode: ExecutionMode):
    document = get_document(function_id, "FUNCTION")
    function = dict(document.TEMPLATE)

    document = get_document(app_req_id, "APP_REQUIREMENT")
    requirement = dict(document.TEMPLATE)
    flavour = requirement["FLAVOUR"]

    # Get ideal VM based on LB logic
    services = get_runtime_services(flavour)
    vm_ids = get_sr_vm_ids(services)
    endpoint = get_runtime_endpoint(vm_ids)

    return execute_function(function=function, mode=mode, endpoint=endpoint, params=parameters)


def get_runtime_services(flavour: str) -> list[dict]:
    """Returns a list of active opennebula flow services backing a certain Serverless Runtime Flavour

    Args:
        flavour (str): Serverless Runtime Flavour

    Returns:
        list[dict]: oneflow instances documents
    """
    uri = f"{ONEFLOW}/service"

    response = requests.get(uri, auth=HTTPBasicAuth(
        BASIC_AUTH['user'], BASIC_AUTH['password']))

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code, detail=response.json())

    services = response.json()

    flavour_services = []

    for service in services["DOCUMENT_POOL"]["DOCUMENT"]:
        if service["NAME"] == flavour and service["TEMPLATE"]["BODY"].roles[0].name == "FAAS" and service["TEMPLATE"]["BODY"].roles[0].cardinality > 0:
            flavour_services.append(service)

    if len(flavour_services) == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Could not find Serverless Runtime instances for flavour {flavour}")

    return flavour_services


def get_sr_vm_ids(services: list[dict]) -> list[int]:
    vm_ids = []

    for service in services:
        vms = service["TEMPLATE"]["BODY"].roles[0].nodes

        for vm in vms:
            vm_ids.append(vm["deploy_id"])

    return vm_ids


def get_sr_vm_id_by_cpu(sr_vm_ids: list[int]):
    monitoring_entries = validate_call(
        lambda: one.vmpool.monitoring(-2, 0).MONITORING)

    cpu_load = {}

    for vm_monitoring in monitoring_entries:
        cpu = vm_monitoring.CPU

        if cpu is None:
            continue

        cpu_load["id"] = vm_monitoring.ID
        cpu_load["cpu"] = cpu

    # remove non SR vm_ids from cpu_load
    for vm_id in cpu_load.keys():
        if vm_id not in sr_vm_ids:
            cpu_load.pop(vm_id)

    return min(cpu_load, key=cpu_load.get)  # return vm with lowest cpu_load


def get_runtime_endpoint(vm_ids: list[int]):

    # TODO: define LB logic when module is loaded. Generate the function.
    if LB_MODE == "cpu":
        vm_id = get_sr_vm_id_by_cpu(vm_ids)
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Unknown load balance mode '{LB_MODE}'")

    vm = validate_call(lambda: one.vm.info(vm_id))
    template = dict(vm.TEMPLATE)

    if 'NIC' not in template:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Serverless Runtime VM does not have NIC")
    if 'IP' not in template["NIC"]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Serverless Runtime VM does not have IP")

    # ip = template['NIC'][0]['IP'] Multiple NIC turns NIC into an array
    # VMs with 1 NIC assumed
    ip = template['NIC']['IP']
    runtime_endpoint = f"http://{ip}:{SR_PORT}"

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

def execute_function(endpoint: str, function: dict, mode: ExecutionMode, params: list[str]):

    # Ideally SR API should handle execution mode as query parameter as well instead of two separate URI
    if mode == "sync":
        url = f"{endpoint}/v1/faas/execute-sync"
    elif mode == "async":
        url = f"{endpoint}/v1/faas/execute-async"

    function["params"] = params

    response = requests.post(url=url, data=json.dumps(function))

    if response.status_code != 200:
        raise HTTPException(response.status_code, detail=response.json())

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
        print(f"The file {ONE_AUTH} does not exist.")
        exit(1)

    one = pyone.OneServer(ONE_XMLRPC, session=session)


def get_document(document_id: int, type_str: str):
    document = validate_call(lambda: one.document.info(document_id))

    type = DOCUMENT_TYPES[type_str]

    if int(document.TYPE) != type:
        e = f"Resource {document_id} is not of type {type_str}"
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED, detail=e)

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
