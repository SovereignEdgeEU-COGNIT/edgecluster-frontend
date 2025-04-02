#!/usr/bin/env python
import pika
from pika.adapters.blocking_connection import BlockingChannel
from urllib.parse import urlparse
import ssl
import json
import logging
import uuid
from fastapi import HTTPException, status
import pydantic_core

from cognit_models import ResultMessage
import opennebula

EXCHANGES = {  # list of exchanges to create when connecting to the broker
    'direct': ['results']
}


class BrokerClient:
    def __init__(self, endpoint: str, logger: logging.Logger):
        self.endpoint = endpoint
        self.logger = logger
        self.connection = None

        self.connect()

    def connect(self) -> pika.BlockingConnection:
        # restart connection on demand
        if self.connection is None or self.connection.is_closed:
            endpoint = urlparse(self.endpoint)

            connection_parameters = pika.ConnectionParameters(
                host=endpoint.hostname, port=endpoint.port)

            if endpoint.scheme == 'ssl':
                # trust ssl certificates
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                connection_parameters.ssl_options = pika.SSLOptions(
                    context=ssl_context)

            self.connection = pika.BlockingConnection(connection_parameters)

            self.logger.info(
                f"Connection established to broker {self.endpoint}")

            channel = self.connection.channel()
            self.logger.info("Ensuring required exchanges exist")

            for type in EXCHANGES:
                exchanges = EXCHANGES[type]

                for exchange in exchanges:
                    channel.exchange_declare(
                        exchange=exchange, exchange_type=type)
                    self.logger.debug(
                        f"Declared {type} exchange \"{exchange}\"")

            channel.close

        return self.connection

    def send_message(self, message: dict, routing_key: str, queue: str = '', exchange: str = '') -> BlockingChannel:
        self.connect()
        channel = self.connection.channel()

        # default exchange uses queues based on routing keys
        if exchange == '':
            queue = routing_key

        channel.queue_declare(queue=queue)

        self.logger.info(f"Sending message to queue {queue}")
        self.logger.debug(message)

        channel.basic_publish(
            exchange=exchange, routing_key=routing_key, body=json.dumps(message))

        self.logger.info("Message queued")
        channel.close()

    def receive_message(self, routing_key: str, queue: str) -> str:
        self.connect()
        channel = self.connection.channel()

        result: dict = None

        def callback(channel: BlockingChannel, method, properties, body):
            nonlocal result
            result = json.loads(body)

            self.logger.info(f'Received message {routing_key}')
            self.logger.debug(result)

            channel.stop_consuming()

        channel.basic_consume(
            queue=queue, on_message_callback=callback, auto_ack=True)

        self.logger.info(f'Waiting for messages related to {routing_key}')
        channel.start_consuming()

        return result


class Executioner():

    def __init__(self, broker_client: BrokerClient, one_client: opennebula.OpenNebulaClient):
        self.one = one_client
        self.broker = broker_client

    def request_execution(self, request: dict, flavour: str, mode: str) -> str:
        """Queue an execution request to be processed by an SR instance

        Args:
            request (dict): Execution request payload as expected by the SR API
            flavour (str): Flavour Queue the SR is responsible for processing requests from
            mode (str): Execution mode of the function, sync or async

        Returns:
            str: Request ID of the requested execution
        """
        # Tag offload request with an ID in order to wait for results
        request_id = str(uuid.uuid4())
        execution_request = {"request_id": request_id,
                             "mode": mode,
                             "payload": request}

        self.broker.logger.info("Requesting execution")
        self.broker.logger.debug(execution_request)

        # Create temporary results queue to
        # avoid race condition with exchange dropping result messages before result queue exists
        channel = self.broker.connection.channel()
        temp_queue = channel.queue_declare(
            queue=f"results_{request_id}", exclusive=True, auto_delete=True).method.queue
        channel.queue_bind(exchange='results',
                           queue=temp_queue, routing_key=request_id)
        channel.close

        self.broker.send_message(
            message=execution_request, routing_key=flavour)

        return request_id

    def await_execution(self, request_id: str) -> str:
        result = self.broker.receive_message(
            routing_key=request_id, queue=f"results_{request_id}")

        self.broker.logger.info("Execution result received")
        self.broker.logger.debug(result)

        return result

    def execute_function(self, function_id: int, app_req_id: int, parameters: list[str], mode: str) -> dict:
        function = self.one.get_function(function_id)
        requirement = self.one.get_app_requirement(app_req_id)

        execution_request = prepare_execution_request(
            function, parameters, app_req_id)

        # Publish execution request to an exchange. Use flavour as routing key.
        execution_id = self.request_execution(
            execution_request, requirement["FLAVOUR"], mode=mode)

        result = self.await_execution(execution_id)

        try:
            ResultMessage(**result)
        except pydantic_core._pydantic_core.ValidationError as e:
            self.broker.logger.error(e)
            error = "Unexpected message from Serverless Runtime"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error)

        if result["code"] != 200:
            raise HTTPException(
                status_code=result["code"], detail=result["message"])

        return result["message"]


def prepare_execution_request(function_document: dict, params: list[str], app_req_id: int) -> dict:

    # function document keys are UPPERCASE in OpenNebula DB, but lowercase on SR model
    request = {k.lower(): v for k, v in function_document.items()}

    request["params"] = params
    request["app_req_id"] = app_req_id

    return request
