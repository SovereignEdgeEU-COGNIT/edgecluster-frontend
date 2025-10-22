import pyone
from fastapi import HTTPException, status
import logging
import os
import sys
import requests
from requests.auth import HTTPBasicAuth
import json

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
        document = _validate_xmlrpc_call(
            lambda: self.one.document.info(document_id))

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

    def get_service_info_onegate(self) -> dict:
        """Get oneflow service information using onegate (no auth needed)
        
        Returns:
            dict: Service information with state, cardinality, roles, etc.
        """
        import subprocess
        
        self.logger.info("Getting service info from onegate")
        
        try:
            result = subprocess.run(
                ['onegate', 'service', 'show', '--json', '--extended'],
                capture_output=True,
                text=True,
                check=True
            )
            service_data = json.loads(result.stdout)
            service = service_data['SERVICE']
            return service
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get service info from onegate: {e.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not get service information from onegate")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to parse onegate output: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not parse service information from onegate")

    def set_service_cardinality_onegate(self, role: str, cardinality: int) -> None:
        """Set the cardinality of a role using onegate (no auth needed)
        
        Args:
            role (str): The role name (e.g., "FAAS")
            cardinality (int): Target cardinality for the role
        """
        import subprocess
        
        self.logger.info(f"Setting role {role} cardinality to {cardinality} via onegate")
        
        try:
            result = subprocess.run(
                ['onegate', 'service', 'scale', '--role', role, '--cardinality', str(cardinality)],
                capture_output=True,
                text=True,
                check=True
            )
            
            self.logger.info(f"Successfully scaled {role} to {cardinality}")
            self.logger.debug(result.stdout)
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to scale service: {e.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not scale role {role}: {e.stderr}")

    def get_service_info(self, service_id: int) -> dict:
        """Get oneflow service information including state and cardinality
        
        Args:
            service_id (int): The oneflow service ID
            
        Returns:
            dict: Service information with state, cardinality, roles, etc.
        """
        uri = f"{self.oneflow_session['endpoint']}/service/{service_id}"
        
        self.logger.info(f"Getting oneflow service {service_id} information")
        response = requests.get(uri, auth=HTTPBasicAuth(
            self.oneflow_session['user'], self.oneflow_session['pass']))
        
        if response.status_code != 200:
            error_msg = response.text if response.text else f"HTTP {response.status_code}"
            self.logger.error(f"Failed to get service info: {error_msg}")
            raise HTTPException(
                status_code=response.status_code, 
                detail=f"Could not read service {service_id}: {error_msg}")
        
        service = response.json()["DOCUMENT"]["TEMPLATE"]["BODY"]
        self.logger.debug(service)
        
        return service

    def set_service_cardinality(self, service_id: int, cardinality: int) -> dict:
        """Set the cardinality of the FAAS role in a oneflow service
        
        Args:
            service_id (int): The oneflow service ID
            cardinality (int): Target cardinality for the FAAS role
            
        Returns:
            dict: Response from oneflow API
        """
        uri = f"{self.oneflow_session['endpoint']}/service/{service_id}/role/FAAS"
        
        payload = {
            "cardinality": cardinality,
            "force": False
        }
        
        self.logger.info(f"Setting service {service_id} FAAS role cardinality to {cardinality}")
        self.logger.debug(payload)
        
        response = requests.put(
            uri, 
            json=payload,
            auth=HTTPBasicAuth(
                self.oneflow_session['user'], 
                self.oneflow_session['pass']))
        
        if response.status_code != 200:
            error_msg = response.text if response.text else f"HTTP {response.status_code}"
            self.logger.error(f"Failed to set cardinality: {error_msg}")
            raise HTTPException(
                status_code=response.status_code, 
                detail=f"Could not set cardinality for service {service_id}: {error_msg}")
        
        result = response.json()
        self.logger.debug(result)
        
        return result


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
