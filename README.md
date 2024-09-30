# cognit-frontend

The COGNIT Frontend  is a software component that acts as the single point of contact for any Application Device Runtime that requests access to the COGNIT Framework to  offload computation through the FaaS paradigm.

## Install

The Application needs to reach the OpenNebula [XMLRPC endpoint](https://docs.opennebula.io/6.8/installation_and_configuration/opennebula_services/oned.html#xml-rpc-server-configuration) and the [ai orchestrator API](https://github.com/SovereignEdgeEU-COGNIT/ai-orchestrator). Configure options at [/etc/cognit-frontend.conf](/share/etc/cognit-frontend.conf).

```yaml
host: 0.0.0.0
port: 1338
one_xmlrpc: https://opennebula_frontend/RPC2
ai_orchestrator_endpoint: http://ai_orchestrator:4567
log_level: debug
```

The application was developed with **python 3.11**. Check the [dependencies](./requirements.txt). It is recommended to install it with a virtual environment.

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
(venv) bash-5.2$ ./src/main.py
INFO:     Started server process [9222]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:1338 (Press CTRL+C to quit)
INFO:     127.0.0.1:61581 - "POST /v1/authenticate HTTP/1.1" 201 Created
INFO:     127.0.0.1:61584 - "POST /v1/app_requirements HTTP/1.1" 200 OK
INFO:     127.0.0.1:61587 - "GET /v1/app_requirements/12 HTTP/1.1" 200 OK
INFO:     127.0.0.1:61590 - "PUT /v1/app_requirements/12 HTTP/1.1" 200 OK
INFO:     127.0.0.1:61594 - "GET /v1/app_requirements/12 HTTP/1.1" 200 OK

INFO:     127.0.0.1:50273 - "GET /docs HTTP/1.1" 200 OK
INFO:     127.0.0.1:50273 - "GET /openapi.json HTTP/1.1" 200 OK
```

Unload the virtual env after stopping the applicatoin

```bash
deactivate
```

## Use

The API documentation is available where the api is running, by default at `http://localhost:1338/docs`.

The App client must issue an [authentication request](http://localhost:1338/docs#/default/authenticate_v1_authenticate_post) with the **user** and **password** credentials of an existing user in the OpenNebula [user pool](https://docs.opennebula.io/6.10/management_and_operations/users_groups_management/manage_users.html#manage-users-shell). This will return an authentication token that should be sent in the subsequent requests in the HTTP header.

This token will expire after 1 day. The client will then need to re-request the token with another authentication request. Every time the application is restarted, newer tokens will need to be re-issued as well. The keys used to generate and verify the token are regenerated when the Application starts.

## Tests

[Configure](./tests/conf.json) and run by issuing `./tests/device_client_requests.py`.

Example requests

```log
Requesting token for oneadmin
Response Code: 201
Response Body: EssBCmEKCG9uZWFkbWluCghwYXNzd29yZAoKb3Blbm5lYnVsYRgDIgkKBwgKEgMYgAgiCgoICIEIEgMYgggyJgokCgIIGxIGCAUSAggFGhYKBAoCCAUKCAoGIOjC8rYGCgQaAggAEiQIABIgneDc8YxOVlK4hXmBOmkxFGXVSig0obOfEnZBlH3i_0gaQHEWqNHbpQfaNueeSlpPKIGZTo3GhUNQI7qf9Zvc0XOLy7YWALuyc_BEXzf7wGGaSvtQ_yMbTVmqiRtFsgyYEgciIgog0-XKTSEUc32CxFO2CaaLBxoveKg89k2mX975EycY1k8=
Uploading application requirements {'REQUIREMENT': 'cpu = amd', 'SCHEDULING_POLICY': 'fast'}
Response Code: 200
Response Body: 33
Reading application requirements 33
Response Code: 200
Response Body: {'REQUIREMENT': 'cpu = amd', 'SCHEDULING_POLICY': 'fast'}
Updating application requirements {'REQUIREMENT': 'cpu = intel', 'SCHEDULING_POLICY': 'slow'}
Response Code: 200
Response Body: None
Reading application requirements 33
Response Code: 200
Response Body: {'REQUIREMENT': 'cpu = intel', 'SCHEDULING_POLICY': 'slow'}
Deleting application requirements 33
Response Code: 204
Reading application requirements 33
Response Code: 404
Response Body: {'detail': '[one.document.info] Error getting document [33].'}
Uploading function {'LANG': 'PY', 'FC': 'ZGVmIHNheV9oZWxsbygpOgogICAgcHJpbnQoJ2hlbGxvJykK', 'FC_HASH': 'bacaa2c80e4f7f381117ff8503bd8752'}
Response Code: 200
Response Body: 32
```

Cognit Frontend logs

```log
INFO:     127.0.0.1:51354 - "POST /v1/authenticate HTTP/1.1" 201 Created
INFO:     127.0.0.1:51357 - "POST /v1/app_requirements HTTP/1.1" 200 OK
INFO:     127.0.0.1:51360 - "GET /v1/app_requirements/33 HTTP/1.1" 200 OK
INFO:     127.0.0.1:51363 - "PUT /v1/app_requirements/33 HTTP/1.1" 200 OK
INFO:     127.0.0.1:51367 - "GET /v1/app_requirements/33 HTTP/1.1" 200 OK
INFO:     127.0.0.1:51370 - "DELETE /v1/app_requirements/33 HTTP/1.1" 204 No Content
INFO:     127.0.0.1:51374 - "GET /v1/app_requirements/33 HTTP/1.1" 404 Not Found
INFO:     127.0.0.1:51377 - "POST /v1/daas/upload HTTP/1.1" 200 OK
```
