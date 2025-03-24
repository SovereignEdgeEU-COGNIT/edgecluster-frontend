import pyone
from fastapi import HTTPException, status
import logging
import os
import sys
import requests
from requests.auth import HTTPBasicAuth


# The user doesn't control the SR VMs. These VMs shared among every user should be under the control
# of an admin of sorts of the Function Executing group. Could also be oneadmin.
# The user only owns the app_requirements and function documents. SERVERLESS means no server controlled
_home = os.path.expanduser("~")
ONE_AUTH = f"{_home}/.one/one_auth"

def get_one_auth() -> str:
    if os.path.exists(ONE_AUTH):
        with open(ONE_AUTH, 'r') as file:
            session = file.read().strip('\n')

            credentials = session.split(":")
    else:
        sys.stderr.write(f"The file {ONE_AUTH} does not exist.")
        exit(1)

    return credentials

class OpenNebulaClient(object):
    DOCUMENT_TYPES = {
        'APP_REQUIREMENT': 1338,
        'FUNCTION': 1339
    }

    def __init__(self, oned: str, oneflow: str, username: str, password: str, logger: logging.Logger):
        self.oned = oned
        self.oneflow_session = {
            'endpoint': oneflow,
            'user': username,
            'pass': password
        }

        self.one = pyone.OneServer(oned, session=f"{username}:{password}")
        self.logger = logger

    def vm_info(self, vm_id: int) -> dict:
        self.logger.info(f"Getting information about VM {vm_id}")

        vm = _validate_xmlrpc_call(lambda: self.one.vm_info(vm_id))

        return dict(vm.TEMPLATE)

    def vmpool_monitoring(self) -> list[pyone.bindings.MONITORINGType45Sub]:
        self.logger.info("Reading VMs last monitoring metrics")

        monitoring_entries = _validate_xmlrpc_call(
            lambda: self.one.vmpool.monitoring(-2, 0).MONITORING)

        return monitoring_entries

    def get_function(self, document_id: int) -> dict:
        return self.get_document(document_id=document_id, type_str='FUNCTION')

    def get_app_requirement(self, document_id: int) -> dict:
        return self.get_document(document_id=document_id, type_str='APP_REQUIREMENT')

    def get_document(self, document_id: int, type_str: str) -> dict:
        self.logger.info(f"Getting information about document {document_id}")
        document = _validate_xmlrpc_call(lambda: self.one.document.info(document_id))

        type = self.DOCUMENT_TYPES[type_str]

        if int(document.TYPE) != type:
            error = f"Resource {document_id} is not of type {type_str}"
            self.logger.error(error)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

        document = dict(document.TEMPLATE)
        self.logger.debug(document)

        return document

    def get_services(self) -> list[dict]:
        uri = f"{self.oneflow_session['endpoint']}/service"

        self.logger.info("Getting existing oneflow services")
        response = requests.get(uri, auth=HTTPBasicAuth(
            self.oneflow_session['user'], self.oneflow_session['pass']))

        if response.status_code != 200:
            self.logger.error(response.json())
            raise HTTPException(
                status_code=response.status_code, detail="Could not read Serverless Runtime instances")

        services = response.json()["DOCUMENT_POOL"]["DOCUMENT"]
        self.logger.debug(services)

        return services

    def cluster_vms(self, cluster_id: int) -> list[pyone.bindings.VMSub]:
        return self.one.vmpool.infoextended(-2, -1, -1, 3, f'CID={cluster_id}').VM


def _validate_xmlrpc_call(xmlrpc_call):
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

