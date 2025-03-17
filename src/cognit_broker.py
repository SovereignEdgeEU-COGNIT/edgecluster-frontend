#!/usr/bin/env python
import pika
from urllib.parse import urlparse
import ssl
import json
import logging
import uuid
from fastapi import HTTPException

import opennebula

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

        return self.connection

    def send_message(self, message: dict, routing_key: str, queue: str = '', exchange: str = ''):
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

    def receive_message(self, routing_key: str, exchange: str) -> str:
        self.connect()
        channel = self.connection.channel()

        channel.exchange_declare(exchange=exchange, exchange_type='direct')
        queue = channel.queue_declare(
            queue='', exclusive=True).method.queue  # TODO: exclusive ?
        channel.queue_bind(exchange=exchange, queue=queue,
                           routing_key=routing_key)

        result: dict = None

        def callback(channel, method, properties, body):
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


class Executioner(BrokerClient):

    def __init__(self, endpoint: str, logger: logging.Logger, one: opennebula.OpenNebulaClient):
        self.one = one
        super().__init__(endpoint, logger)

    def request_execution(self, request: dict, flavour: str) -> str:
        # Tag offload request with an ID in order to wait for results
        request_id = str(uuid.uuid4())
        execution_request = {"request_id": request_id,
                             "payload": request}

        self.logger.info("Requesting execution")
        self.logger.debug(execution_request)

        self.send_message(message=execution_request, routing_key=flavour)

        return request_id

    def await_execution(self, request_id: str) -> str:
        result = self.receive_message(request_id, 'results')

        self.logger.info("Execution result received")
        self.logger.debug(result)

        return result

    def execute_function(self, function_id: int, app_req_id: int, parameters: list[str]) -> dict:
        function = self.one.get_function(function_id)
        requirement = self.one.get_app_requirement(app_req_id)

        execution_request = prepare_execution_request(
            function, parameters, app_req_id)

        # Publish execution request to an exchange. Use flavour as routing key.
        execution_id = self.request_execution(
            execution_request, requirement["FLAVOUR"])
        # Subscribe to the execution results queue. Wait for execution result.
        result = self.await_execution(execution_id)

        if result["code"] != 200:
            raise HTTPException(status_code=result["code"], detail=result["message"])

        return result["message"]


def prepare_execution_request(function_document: dict, params: list[str], app_req_id: int) -> dict:

    # function document keys are UPPERCASE in OpenNebula DB, but lowercase on SR model
    request = {k.lower(): v for k, v in function_document.items()}

    request["params"] = params
    request["app_req_id"] = app_req_id

    return request
