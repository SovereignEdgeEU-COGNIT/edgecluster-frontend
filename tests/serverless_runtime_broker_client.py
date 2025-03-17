#!/usr/bin/env python

import json
import pika
import sys
from urllib.parse import urlparse
import ssl
import requests

import tests_common as tests

def sr_offload(offload_request: dict) -> str:
    """Serverless Runtime faas requests client. 

    Args:
        offload_request (dict): dictionary with ExecSync params as required by the Serverless Runtime API

    Returns:
        str: result dictionary containing the return code and the body of the execution
    """    
    logger.info(f"Sending function offload to {SR_ENDPOINT}")
    logger.debug(offload_request)

    url = f"{SR_ENDPOINT}/v1/faas/execute-sync"

    response = requests.post(url=url, data=json.dumps(offload_request))

    result = {
        "code": response.status_code,
        "message": response.json()
    }

    return json.dumps(result)


def subscriber_function(channel, method, properties, body):
    """Function used as callback when opening a channel for consumption. It contains the execution request handling and result delivery logic.

    Args:
        channel (_type_): _description_
        method (_type_): _description_
        properties (_type_): _description_
        body (_type_): _description_
    """
    execution_request = json.loads(body)
    request_id = execution_request["request_id"]

    logger.info(f"Received execution request {request_id}")

    # Offload execution request to the SR after the message has been received
    offload_request = execution_request["payload"]
    result = sr_offload(offload_request)

    logger.info("Results ready")
    logger.debug(result)

    # Publish results
    channel.basic_publish(
        exchange='results',
        routing_key=request_id,
        body=result
    )

    channel.basic_ack(delivery_tag=method.delivery_tag)

    logger.info(f"Processed and published request {request_id}")


def connect_to_broker(broker_endpoint: str) -> pika.BlockingConnection:
    endpoint = urlparse(broker_endpoint)

    connection_parameters = pika.ConnectionParameters(
        host=endpoint.hostname, port=endpoint.port)

    if broker_endpoint.scheme == 'ssl':
        # trust ssl certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connection_parameters.ssl_options = pika.SSLOptions(
            context=ssl_context)

    connection = pika.BlockingConnection(connection_parameters)

    logger.info(f"Established connection to rabbitmq broker at {broker_endpoint}")

    return connection


# Program Configuration
FLAVOUR = sys.argv[1]
SR_ENDPOINT = 'http://[::]:8000'
BROKER = 'http://localhost:5672'

logger = tests.logger

# Initialize connection
connection = connect_to_broker(BROKER)

# Create a channel to
channel = connection.channel()
# listen for execution requests on this queue bound to a flavour
channel.queue_declare(queue=FLAVOUR)
channel.basic_qos(prefetch_count=1)  # only process 1 request at a time
# publish execution results in this exchange
channel.exchange_declare(exchange="results", exchange_type="direct")

channel.basic_consume(queue=FLAVOUR, on_message_callback=subscriber_function)
logger.info(f"Waiting for execution requests to flavour {FLAVOUR}")
channel.start_consuming()
