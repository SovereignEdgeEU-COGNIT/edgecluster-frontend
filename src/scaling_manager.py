#!/usr/bin/env python

import time
import subprocess
import json
import logging
from fastapi import HTTPException, status
import opennebula


def _get_queue_pending_messages(logger: logging.Logger) -> int:
    """Get total pending function execution messages across all flavour queues.

    Queries RabbitMQ via rabbitmqadmin, excludes non-execution queues
    (scaler_metrics_queue, results_* temporary queues).

    Returns:
        int: Total pending messages in flavour execution queues
    """
    try:
        result = subprocess.run(
            ['rabbitmqadmin', 'list', 'queues', 'name', 'messages', '--format=raw_json'],
            capture_output=True, text=True, check=True, timeout=10
        )
        queues = json.loads(result.stdout)
        total = 0
        for q in queues:
            name = q.get('name', '')
            if name == 'scaler_metrics_queue' or name.startswith('results_'):
                continue
            pending = q.get('messages', 0)
            if pending > 0:
                logger.info(f"Queue '{name}' has {pending} pending function executions")
            total += pending
        return total
    except Exception as e:
        logger.error(f"Error querying RabbitMQ queues: {e}")
        return 0


def _wait_for_queue_drain(logger: logging.Logger, timeout: int = 300, poll_interval: int = 5) -> None:
    """Block until all flavour execution queues are drained.

    Args:
        logger: Logger instance
        timeout: Maximum seconds to wait for drain before raising an error
        poll_interval: Seconds between queue checks
    """
    start_time = time.time()

    while True:
        pending = _get_queue_pending_messages(logger)
        if pending == 0:
            logger.info("All execution queues are empty")
            return

        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Queue drain timed out after {timeout}s. {pending} messages still pending."
            )

        logger.info(f"{pending} messages still pending, waiting {poll_interval}s for drain... ({int(elapsed)}s/{timeout}s)")
        time.sleep(poll_interval)


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
    timeout = 70 * abs(target_cardinality - current_cardinality)
    
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


def scale_down(one_client: opennebula.OpenNebulaClient, current_cardinality: int, target_cardinality: int, logger: logging.Logger) -> dict:
    """Scale down the service to target cardinality via OneGate after queue drain.

    Waits until all flavour execution queues in RabbitMQ are empty (no pending
    function executions), then delegates to scale_up which handles the OneGate
    cardinality change and polling.

    Args:
        one_client: OpenNebula client instance
        current_cardinality: Current number of VMs for FAAS role
        target_cardinality: Desired number of VMs for FAAS role
        logger: Logger instance

    Returns:
        dict: Final service state information
    """
    logger.info(f"Starting scale down from {current_cardinality} to {target_cardinality}")
    logger.info("Waiting for RabbitMQ queues to drain before scaling down...")
    _wait_for_queue_drain(logger)
    logger.info("All execution queues drained, proceeding with scale down via OneGate")
    return scale_up(one_client, current_cardinality, target_cardinality, logger)

