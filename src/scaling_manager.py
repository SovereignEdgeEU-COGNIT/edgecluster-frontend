#!/usr/bin/env python

import time
import logging
from fastapi import HTTPException, status
import opennebula

def scale_up(one_client: opennebula.OpenNebulaClient, target_cardinality: int, logger: logging.Logger) -> dict:
    """Scale up the service to target cardinality with polling until complete
    
    Args:
        one_client: OpenNebula client instance
        target_cardinality: Desired number of VMs for FAAS role
        logger: Logger instance
        
    Returns:
        dict: Final service state information
    """
    poll_interval = 1  # seconds
    timeout = 60  # 60 seconds - wait for service to become RUNNING and scaling to complete
    
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
        
        logger.debug(f"Cardinality: {current_cardinality}/{target_cardinality}")
        
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
        
        logger.info(f"State: {current_state}, Cardinality: {current_cardinality}/{target_cardinality}, waiting {poll_interval}s...")
        time.sleep(poll_interval)


def scale_down(one_client: opennebula.OpenNebulaClient, target_cardinality: int, logger: logging.Logger) -> dict:
    """Scale down the service to target cardinality (placeholder for future implementation)
    
    Args:
        one_client: OpenNebula client instance
        target_cardinality: Desired number of VMs for FAAS role
        logger: Logger instance
        
    Returns:
        dict: Final service state information
    """
    logger.warning("Scale down not yet implemented")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Scale down functionality not yet implemented. VM selection logic pending."
    )

