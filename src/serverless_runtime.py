from cognit_models import Execution, ExecutionMode
import pyone
from fastapi import HTTPException, status
import os

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

def function_push(execution: Execution, mode: ExecutionMode):
    pass

# TODO: Map flavours to numbers or update SR to label FLAVOURS_STR as well. Use these as filter instead
def get_runtimes(flavour: str) -> list[int]:
    # sqlite cannot issue full text search
    # Get every RUNNING VM whose name starts with FAAS_. FAAS comes from the role name on oneflow
    vms = one.vmpool.info(-4, -1, -1, 3, "NAME=FAAS_").VM # one 6.10+ uses VM.NAME

    runtime_endpoints = []

    for vm in vms:
        template = dict(vm.TEMPLATE)
        ip = template['NIC'][0]['IP']

        runtime_endpoints.append(f"http://{ip}:8000")



# TODO: Load balance mode. Explain which modes are required/considered
# Ideally the SR App should have a way to communicate how many functions is it executing.
# Otherwise we are limited to metric parsing, which might be inaccurate (metrics are scrapped per interval)
# and time consuming (querying each SR VM metric can take time)
# For example: GET /v1/faas -> [] of faas_task_uuid. Smaller [] is runtime candidate to run the current function
def get_runtime(runtimes: list[str]) -> str:
    pass

# class ExecSyncParams(BaseModel):
#     lang: str = Field(
#         default="",
#         description="Language of the offloaded function",
#     )
#     fc: str = Field(
#         default="",
#         description="Function to be offloaded",
#     )
#     fc_hash: str = Field(
#         default="",
#         description="Hash of the function to be offloaded",
#     )
#     params: list[str] = Field(
#         default="",
#         description="List containing the serialized parameters by each device runtime transfered to the offloaded function",
#     )

# TODO: Example is wrong at https://github.com/SovereignEdgeEU-COGNIT/serverless-runtime/blob/c33dcc89dd250ed34022e8c5251638d27f8cdba3/docs/README.md#L32-L56
_EXAMPLE_FUNCTION = {
    "lang": "PY",
    "fc": "gAWVKwIAAAAAAACMF2Nsb3VkcGlja2xlLmNsb3VkcGlja2xllIwOX21ha2VfZnVuY3Rpb26Uk5QoaACMDV9idWlsdGluX3R5cGWUk5SMCENvZGVUeXBllIWUUpQoSwJLAEsASwJLAktDQwh8AHwBFwBTAJROhZQpjAFhlIwBYpSGlIx2L21udC9jL1VzZXJzL2dwZXJhbHRhL09uZURyaXZlIC0gSUtFUkxBTiBTLkNPT1AvUFJPWUVDVE9TL0VVUk9QRU9TL0NPR05JVC9EZXNhcnJvbGxvIFdQMy9QcnVlYmFzL3Rlc3Rfc2VyaWFsaXphdGlvbi5weZSMCm15ZnVuY3Rpb26USxJDAggBlCkpdJRSlH2UKIwLX19wYWNrYWdlX1+UTowIX19uYW1lX1+UjAhfX21haW5fX5SMCF9fZmlsZV9flGgNdU5OTnSUUpSMHGNsb3VkcGlja2xlLmNsb3VkcGlja2xlX2Zhc3SUjBJfZnVuY3Rpb25fc2V0c3RhdGWUk5RoGH2UfZQoaBRoDowMX19xdWFsbmFtZV9flGgOjA9fX2Fubm90YXRpb25zX1+UfZSMDl9fa3dkZWZhdWx0c19flE6MDF9fZGVmYXVsdHNfX5ROjApfX21vZHVsZV9flGgVjAdfX2RvY19flE6MC19fY2xvc3VyZV9flE6MF19jbG91ZHBpY2tsZV9zdWJtb2R1bGVzlF2UjAtfX2dsb2JhbHNfX5R9lHWGlIZSMC4=",
    "fc_hash": "", # TODO: Missing in example
    "params":["gAVLAi4=","gAVLAy4="]
}


def execute_function(function: dict, mode: ExecutionMode):
    pass

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
