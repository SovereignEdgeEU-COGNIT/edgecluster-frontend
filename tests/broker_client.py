#!/usr/bin/env python

import os
import sys
import tests_common as tests

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

import cognit_broker  # noqa: E402

logger = tests.logger
conf = tests.CONF

broker_endpoint :str = conf["broker"]
broker_client = cognit_broker.BrokerClient(
    endpoint=broker_endpoint, logger=logger)
broker_client = cognit_broker.Executioner(broker_client=broker_client, one_client=tests.one_client)

queues :dict = conf["flavours"]
offload_requests :dict = conf["offload_requests"]

for flavour in queues:
    logger.info(f"Using broker {broker_endpoint} on queue {flavour}")

    for offload_request in offload_requests.values():
        request_id = broker_client.request_execution(offload_request, flavour)
        broker_client.await_execution(request_id)
