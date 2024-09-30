import yaml
import os
import socket
import sys
from urllib.parse import urlparse

PATH = "/etc/cognit-edge_cluster_frontend.conf"
DEFAULT = {
    'host': '0.0.0.0',
    'port': 1339,
    'one_xmlrpc': 'http://localhost:2633/RPC2',
    'cognit_frontend': 'http://localhost:1338',
    'log_level': 'info'
}

FALLBACK_MSG = 'Using default configuration'


if os.path.exists(PATH):
    with open(PATH, 'r') as file:
        try:
            user_config = yaml.safe_load(file)
            if not isinstance(user_config, dict):
                user_config = {}
        except yaml.YAMLError as e:
            print(f"{e}\n{FALLBACK_MSG}")
            config = DEFAULT
else:
    print(f"{PATH} not found. {FALLBACK_MSG}.")
    config = DEFAULT

config = DEFAULT.copy()
config.update(user_config)

ONE_XMLRPC = config['one_xmlrpc']
COGNIT_FRONTEND = config['cognit_frontend']

one = urlparse(ONE_XMLRPC)

try:
    socket.create_connection((one.hostname, one.port), timeout=5)
except socket.error as e:
    print(f"Error: Unable to connect to OpenNebula at {ONE_XMLRPC}. {str(e)}")
    sys.exit(1)

HOST = config['host']
PORT = config['port']
LOG_LEVEL = config['log_level']