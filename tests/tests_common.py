import logging
import os
import sys
import yaml

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "src"))


import opennebula  # noqa: E402

def create_logger(name: str, level=logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Log to  console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    return logger

logger = create_logger('tests_logger')

conf_path = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'conf.yaml')
with open(conf_path, 'r') as file:
    CONF = yaml.safe_load(file)

# cognit admin auth
one_auth = opennebula.get_one_auth()
one_client = opennebula.OpenNebulaClient(
    oned=CONF["oned"], oneflow=CONF["oneflow"], username=one_auth[0], password=one_auth[1], logger=logger)

