from fastapi import HTTPException, status
import requests
import json
import logging

from cognit_models import ExecutionMode
import opennebula

ERROR_OFFLOAD = "Failed to offload function"

SR_PORT = 8000
CLUSTER_ID = None
LB_MODE = "cpu"

logger: logging.Logger = None
one: opennebula.OpenNebulaClient = None


def execute_function(function_id: int, app_req_id: int, parameters: list[str], mode: ExecutionMode):
    function = one.get_function(function_id)
    requirement = one.get_app_requirement(app_req_id)

    flavour = requirement["FLAVOUR"]
    services = get_runtime_services(flavour)

    # Get ideal VM based on LB logic
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

    flavour_services = []

    for service in one.get_services():

        if service["NAME"] == flavour and service["TEMPLATE"]["BODY"]["roles"][0]["name"] == "FAAS" and service["TEMPLATE"]["BODY"]["roles"][0]["cardinality"] > 0:
            flavour_services.append(service)

    if len(flavour_services) == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Could not find Serverless Runtime instances for flavour {flavour}")

    logger.debug(flavour_services)

    return flavour_services


def get_sr_vm_ids(services: list[dict]) -> list[int]:
    vm_ids_sr = []

    # Get every FAAS VM. FAAS is role 0 on flavour service templates
    for service in services:
        vms = service["TEMPLATE"]["BODY"]["roles"][0]["nodes"]

        for vm in vms:
            vm_ids_sr.append(vm["deploy_id"])

    # Get every RUNNING VM on a cluster
    vmpool_ec = one.cluster_vms(CLUSTER_ID)
    vm_ids_ec = []

    for vm in vmpool_ec:
        vm_ids_ec.append(vm.ID)

    vm_ids = list(set(vm_ids_sr) & set(vm_ids_ec))

    logger.info(f"Reading SR VMs for flavour on cluster {CLUSTER_ID}")
    logger.debug(vm_ids)

    return vm_ids


def get_sr_vms_by_cpu(sr_vm_ids: list[int]) -> list:
    # can be optimized by getting VMs only for the cognit/serverless group
    # this group would only own SR VMs
    # currently it reads every VM in the pool

    cpu_load = {}

    # get cpu load metrics of each vm in sr_vm_ids
    for vm_monitoring in one.vmpool_monitoring():
        cpu = vm_monitoring.CPU

        if cpu is None:
            continue

        vm_id = vm_monitoring.ID

        if vm_id in sr_vm_ids:
            cpu_load[vm_id] = cpu

    # sort by cpu usage
    logger.debug(cpu_load)
    cpu_load_sorted = sorted(cpu_load.keys(), key=cpu_load.get)

    logger.debug(cpu_load_sorted)
    return cpu_load_sorted


def get_runtime_endpoint(vm_ids: list[int]):

    # TODO: define LB logic when module is loaded. Generate the function.
    if LB_MODE == "cpu":
        vm_ids = get_sr_vms_by_cpu(vm_ids)
    else:
        logger.warning(
            f"Unknown load balance mode '{LB_MODE}'. Using CPU Load Balance mode.")

    for vm_id in vm_ids:
        template = one.vm_info(vm_id)

        logger.debug(template)

        if 'NIC' not in template:
            logger.error(f"Serverless Runtime VM {vm_id} does not have NIC")
            continue

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
            continue

        return runtime_endpoint

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERROR_OFFLOAD)


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
# Direct SR function execution offloading is deprecated. Queue the execution request instead
def offload_function(endpoint: str, offload_request: dict, mode: ExecutionMode):
    """Offload the function execution to the Serverless Runtime instance

    Args:
        endpoint (str): Where the Serverless Runtime Instance is runninr
        offload_request (dict): Function to be executed with required execution context
        mode (ExecutionMode): sync or async execution

    Returns:
        _type_: Response from the SR App
    """

    # Ideally SR API should handle execution mode as query parameter as well instead of two separate URI
    if mode == "sync":
        url = f"{endpoint}/v1/faas/execute-sync"
    elif mode == "async":
        url = f"{endpoint}/v1/faas/execute-async"

    logger.info(f"Sending function offload to {url}")
    logger.debug(offload_request)

    try:
        response = requests.post(url=url, data=json.dumps(offload_request))
    except Exception as e:
        logger.error(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=ERROR_OFFLOAD)

    if response.status_code != 200:
        logger.error(response.json())
        raise HTTPException(
            status_code=response.status_code, detail=ERROR_OFFLOAD)

    return response.json()
