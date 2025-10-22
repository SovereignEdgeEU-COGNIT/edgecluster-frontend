#!/usr/bin/env python

import time
import logging
from fastapi import HTTPException, status
import opennebula

def scale_up(one_client: opennebula.OpenNebulaClient, current_cardinality: int, target_cardinality: int, logger: logging.Logger) -> dict:
    """Scale up the service to target cardinality with polling until complete
    
    Args:
        one_client: OpenNebula client instance
        target_cardinality: Desired number of VMs for FAAS role
        logger: Logger instance
        
    Returns:
        dict: Final service state information
    """
    poll_interval = 2  # seconds
    # The timeout depends on the target cardinality, because we need to wait for all VMs to be ready
    timeout = 70 * (target_cardinality - current_cardinality)
    
    logger.info(f"Starting scale up to cardinality {target_cardinality}")
    
    # Step 1: Wait for service to be in RUNNING
    logger.info("Waiting for service to be ready for scaling...")
    start_time = time.time()
    
    while True:
        service_info = one_client.get_service_info_onegate()
        current_state = int(service_info.get('state', -1))        
        logger.debug(f"Current service state: {current_state}")
        
        # Service is ready for scaling if it's RUNNING
        if current_state == 2:
            logger.info(f"Service is in RUNNING state, ready for scaling")
            break
        
        # Check if we've exceeded the timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Service did not reach RUNNING state within {timeout}s. Current state: {current_state}"
            )
        
        if current_state == 2:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Service is not in FAILED_SCALING state."
            )
        
        time.sleep(poll_interval)
    
    # Step 2: Trigger the scaling operation
    logger.info(f"Triggering scale to cardinality {target_cardinality}")
    one_client.set_service_cardinality_onegate('FaaS', target_cardinality)
    
    # Step 3: Poll until scaling completes and target cardinality is reached
    logger.info("Polling until scaling operation completes...")
    start_time = time.time()
    
    while True:
        service_info = one_client.get_service_info_onegate()
        current_state = int(service_info.get('state', -1))
        
        # Find current FAAS role cardinality
        current_cardinality = 0
        for role in service_info.get('roles', []):
            if role.get('name') == 'FaaS':
                current_cardinality = role.get('cardinality')
                break
                
        # Success: RUNNING state and target cardinality reached
        if (current_state == 2 or current_state == 10) and current_cardinality == target_cardinality:
            logger.info(f"Scaling complete! Cardinality: {current_cardinality}")
            return service_info
        
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Scaling operation timed out after {timeout}s. Current: {current_cardinality}, Target: {target_cardinality}"
            )
        
        # Failed states
        if current_state == 9:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scaling failed. Service is not in RUNNING state. Current state: {current_state}"
            )
        
        logger.info(f"State: {current_state}, Polling every {poll_interval}s, Timeout: {timeout}s")
        time.sleep(poll_interval)


def scale_down(one_client: opennebula.OpenNebulaClient, target_cardinality: int, logger: logging.Logger) -> dict:
    """Scale down the service to target cardinality with idle-first strategy
    
    Args:
        one_client: OpenNebula client instance
        target_cardinality: Desired number of VMs for FAAS role
        logger: Logger instance
        
    Returns:
        dict: Final service state information
    """
    import requests
    
    poll_interval = 5  # seconds
    operation_timeout = 600  # 10 minutes
    
    logger.info(f"Starting scale down to cardinality {target_cardinality}")
    
    # Get current service state
    service_info = one_client.get_service_info_onegate()
    
    # Extract FaaS VMs
    faas_vms = []
    for role in service_info.get('roles', []):
        if role.get('name') == 'FaaS':
            faas_vms = role.get('nodes', [])
            break
    
    if not faas_vms:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No FaaS VMs found in service"
        )
    
    current_cardinality = len(faas_vms)
    vms_to_remove = current_cardinality - target_cardinality
    
    logger.info(f"Need to remove {vms_to_remove} VMs")
    
    # Phase 1: Classify VMs into busy and idle
    busy_vms = []
    idle_vms = []
    
    for vm_node in faas_vms:
        vm_id = vm_node.get('deploy_id')
        vm_ip = _get_vm_ip(vm_node, logger)
        logger.debug(f"vm_id: {vm_id}, vm_ip: {vm_ip}")

        if not vm_ip:
            logger.warning(f"Could not get IP for VM {vm_id}, terminating without graceful shutdown")
            _terminate_vm(vm_id, logger)
            continue
        
        is_busy = _is_vm_busy(vm_ip, logger)
        
        if is_busy:
            busy_vms.append({'id': vm_id, 'ip': vm_ip})
            logger.info(f"VM {vm_id} is BUSY")
        else:
            idle_vms.append({'id': vm_id, 'ip': vm_ip})
            logger.info(f"VM {vm_id} is IDLE")
    
    # Phase 1.5: Async terminate idle VMs (up to vms_to_remove)
    terminated_idle_count = 0
    if idle_vms and vms_to_remove > 0:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        # Select idle VMs to terminate (up to the number we need to remove)
        idle_to_terminate = idle_vms[:vms_to_remove]
        logger.info(f"Terminating {len(idle_to_terminate)} idle VMs in parallel...")
        
        def stop_and_terminate_vm(vm):
            """Stop consumer, verify idle, then terminate VM"""
            try:
                # Send stop-consuming request (non-blocking)
                _stop_vm_consumer(vm['ip'], logger)
                
                # Poll briefly to ensure VM is actually idle
                
                while True:
                    if not _is_vm_busy(vm['ip'], logger):
                        # Confirmed idle, terminate now
                        _terminate_vm(vm['id'], logger)
                        logger.info(f"Successfully terminated idle VM {vm['id']}")
                        return True
                
                logger.warning(f"Idle VM {vm['id']} still busy after {max_wait}s, terminating anyway")
                _terminate_vm(vm['id'], logger)
                return True
                
            except Exception as e:
                logger.error(f"Error terminating idle VM {vm['id']}: {e}")
                return False
        
        # Async stop+terminate each VM as soon as its stop-consuming finishes
        with ThreadPoolExecutor(max_workers=len(idle_to_terminate)) as executor:
            futures = {
                executor.submit(stop_and_terminate_vm, vm): vm 
                for vm in idle_to_terminate
            }
            for future in as_completed(futures):
                vm = futures[future]
                try:
                    if future.result():
                        terminated_idle_count += 1
                except Exception as e:
                    logger.error(f"Unexpected error for VM {vm['id']}: {e}")
        
        logger.info(f"Successfully terminated {terminated_idle_count} idle VMs")
    
    vms_to_remove -= terminated_idle_count
    terminated_count = terminated_idle_count  # Track total terminated VMs

    # Phase 2: If more removals needed, unbind busy VMs and wait for them to finish
    if vms_to_remove > 0:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        logger.info(f"Need to remove {vms_to_remove} more VMs from busy ones")
        
        vms_to_unbind = busy_vms[:vms_to_remove]
        logger.info(f"Stopping consumers and waiting for {len(vms_to_unbind)} busy VMs to finish in parallel...")
        
        def stop_wait_and_terminate_busy_vm(vm):
            """Stop consumer, wait for execution to finish, then terminate VM"""
            try:
                # Step 1: Stop consumer
                _stop_vm_consumer(vm['ip'], logger)
                logger.info(f"VM {vm['id']} consumer stopped, waiting for execution to finish...")
                
                # Step 2: Poll until VM becomes idle
                start_time = time.time()
                while (time.time() - start_time) < operation_timeout:
                    is_busy = _is_vm_busy(vm['ip'], logger)
                    
                    if not is_busy:
                        # Step 3: Terminate immediately when idle
                        logger.info(f"VM {vm['id']} finished execution, terminating now")
                        _terminate_vm(vm['id'], logger)
                        return True
                    
                    time.sleep(poll_interval)
                
                # Timeout: force terminate
                logger.warning(f"VM {vm['id']} did not finish within timeout, force terminating")
                _terminate_vm(vm['id'], logger)
                return True
                
            except Exception as e:
                logger.error(f"Error processing busy VM {vm['id']}: {e}")
                return False
        
        # Process each busy VM independently in parallel
        with ThreadPoolExecutor(max_workers=len(vms_to_unbind)) as executor:
            futures = {
                executor.submit(stop_wait_and_terminate_busy_vm, vm): vm 
                for vm in vms_to_unbind
            }
            for future in as_completed(futures):
                vm = futures[future]
                try:
                    if future.result():
                        terminated_count += 1
                except Exception as e:
                    logger.error(f"Unexpected error for busy VM {vm['id']}: {e}")
    
    # Verify final state
    logger.info(f"Scale down complete! Terminated {terminated_count} VMs, target cardinality: {target_cardinality}")
    service_info = one_client.get_service_info_onegate()
    
    return service_info


def _get_vm_ip(vm_node: dict, logger: logging.Logger) -> str:
    """Extract VM IP address from node info
    
    Args:
        vm_node: VM node dictionary from oneflow
        logger: Logger instance
        
    Returns:
        str: VM IP address or None if not found
    """
    try:
        vm_info = vm_node.get('vm_info', {})
        template = vm_info.get('VM', {}).get('TEMPLATE', {})
        nic = template.get('NIC', {})
        
        # Try IPv4 first
        if isinstance(nic, list):
            ip = nic[0].get('IP')
        else:
            ip = nic.get('IP')
        
        if ip:
            return ip
        
        # Try IPv6
        if isinstance(nic, list):
            ip6 = nic[0].get('IP6')
        else:
            ip6 = nic.get('IP6')
        return ip6
        
    except Exception as e:
        logger.error(f"Error extracting VM IP: {e}")
        return None


def _is_vm_busy(vm_ip: str, logger: logging.Logger) -> bool:
    """Check if VM is currently executing a function via Prometheus metrics
    
    Args:
        vm_ip: VM IP address
        logger: Logger instance
        
    Returns:
        bool: True if VM is busy (executing), False if idle
    """
    import requests
    
    try:
        response = requests.get(f"http://{vm_ip}:9100/metrics", timeout=5)
        metrics_text = response.text
        
        # Look for vm_is_executing metric
        for line in metrics_text.split('\n'):
            if line.startswith('vm_is_executing'):
                # Parse: vm_is_executing{vm="810"} 1
                # or:    vm_is_executing 1
                parts = line.split()
                if len(parts) >= 2:
                    value = float(parts[-1])
                    logger.debug(f"prometheus: vm_is_executing for {vm_ip}: {value}")
                    return value > 0
        
        # Metric not found, assume idle
        logger.warning(f"vm_is_executing metric not found for {vm_ip}, assuming idle")
        return False
        
    except Exception as e:
        logger.error(f"Error checking VM {vm_ip} status: {e}")
        # On error, assume idle to avoid blocking scale-down
        return False


def _stop_vm_consumer(vm_ip: str, logger: logging.Logger) -> None:
    """Stop RabbitMQ consumer on a VM (non-blocking, just triggers the stop)
    
    Args:
        vm_ip: VM IP address
        logger: Logger instance
    """
    import requests
    
    try:
        # To trigger the stop
        response = requests.post(
            f"http://{vm_ip}:8000/control/stop-consuming",
            timeout=3 
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully sent stop-consuming request to VM {vm_ip}")
        else:
            logger.warning(f"Stop-consuming returned {response.status_code} for VM {vm_ip}")
            
    except requests.exceptions.Timeout:
        # Timeout is OK - the endpoint received our request but is waiting for function to finish
        logger.info(f"Stop-consuming request sent to VM {vm_ip} (endpoint still processing)")
    except Exception as e:
        logger.warning(f"Error stopping consumer on VM {vm_ip}: {e} (will poll vm_is_executing)")


def _terminate_vm(vm_id: int, logger: logging.Logger) -> None:
    """Terminate a VM using onegate
    
    Args:
        vm_id: VM ID to terminate
        logger: Logger instance
    """
    import subprocess
    
    try:
        logger.info(f"Terminating VM {vm_id} with hard shutdown")
        
        result = subprocess.run(
            ['onegate', 'vm', 'terminate', str(vm_id), '--hard'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30  # 30 second timeout for terminate command
        )
        
        logger.info(f"Successfully terminated VM {vm_id}")
        logger.debug(result.stdout)
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout terminating VM {vm_id}: command took longer than 30s")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Timeout terminating VM {vm_id}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to terminate VM {vm_id}: {e.stderr}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not terminate VM {vm_id}: {e.stderr}")

