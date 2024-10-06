# Edge Cluster Frontend

The Edge Cluster Frontend is the entrypoint for offloading functions from the Device Client in each Edge Cluster. It acts as a load balancer, to handle the redirection to the correct Serverless Runtime running within the particular Edge Cluster where it is located.

## Install

The Application needs to reach the OpenNebula [XMLRPC endpoint](https://docs.opennebula.io/6.8/installation_and_configuration/opennebula_services/oned.html#xml-rpc-server-configuration) and the [oneflow endpoint](https://docs.opennebula.io/6.10/installation_and_configuration/opennebula_services/oneflow.html). Configure options at [/etc/cognit-edge_cluster_frontend.conf](/share/etc/cognit-edge_cluster_frontend.conf).

```yaml
host: 0.0.0.0
port: 1339
oneflow: "http://opennebula_frontend:2474"
one_xmlrpc: https://opennebula_frontend/RPC2
cognit_frontend: 'http://localhost:1338'
log_level: debug
```

The application was developed with **python 3.10**. Check the [dependencies](./requirements.txt). It is recommended to install it with a virtual environment.

Install virtualenv

```bash
pip install virtualenv
```

Create virtualenv

```bash
cd /path/to/cognit-frontend-repo
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the application

```bash
./src/main.py
```

It should result in uvicorn starting the web server and logging requests

```log
venv)  ◰³ venv  ~/P/C/edgecluster-frontend   v1 *  ./src/main.py                                                                                                         8s
INFO:     Started server process [22228]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:1339 (Press CTRL+C to quit)
INFO:     127.0.0.1:55300 - "GET / HTTP/1.1" 307 Temporary Redirect
INFO:     127.0.0.1:55300 - "GET /docs HTTP/1.1" 200 OK
INFO:     127.0.0.1:55300 - "GET /openapi.json HTTP/1.1" 200 OK
INFO:     127.0.0.1:55314 - "GET / HTTP/1.1" 307 Temporary Redirect
INFO:     127.0.0.1:55314 - "GET /docs HTTP/1.1" 200 OK
INFO:     127.0.0.1:55314 - "GET / HTTP/1.1" 307 Temporary Redirect
INFO:     127.0.0.1:55314 - "GET /docs HTTP/1.1" 200 OK
INFO:     127.0.0.1:55318 - "GET / HTTP/1.1" 307 Temporary Redirect
INFO:     127.0.0.1:55318 - "GET /docs HTTP/1.1" 200 OK
```

Unload the virtual env after stopping the application

```bash
deactivate
```

## Use

The API documentation is available where the api is running, by default at `http://localhost:1338/docs`.

The App client must previously get an auth token issued by the [cognit frontend](https://github.com/SovereignEdgeEU-COGNIT/cognit-frontend?tab=readme-ov-file#use) and send it on the requests header.
