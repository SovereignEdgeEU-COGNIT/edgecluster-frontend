#!/usr/bin/env python3.11

import requests
from requests.auth import HTTPBasicAuth
import json
import os
import sys

import serverless_runtime as sr

SR_ENDPOINT = "http://localhost:8000"

EXAMPLE_FUNCTION = {
    "fc": "gAWVHAIAAAAAAACMF2Nsb3VkcGlja2xlLmNsb3VkcGlja2xllIwOX21ha2VfZnVuY3Rpb26Uk5QoaACMDV9idWlsdGluX3R5cGWUk5SMCENvZGVUeXBllIWUUpQoSwNLAEsASwNLAktDQwx8AHwBFAB8AhQAUwCUToWUKYwBYZSMAWKUjAFjlIeUjGIvaG9tZS9hYnJvc2EvcmVwb3MvZ2l0aHViLWRldmljZS1ydW50aW1lLXB5L2NvZ25pdC90ZXN0L2ludGVncmF0aW9uL3Rlc3RfaW50ZWdyYXRpb25fU1JfY29udGV4dC5weZSMCmR1bW15X2Z1bmOUS5pDAgwBlCkpdJRSlH2UTk5OdJRSlIwcY2xvdWRwaWNrbGUuY2xvdWRwaWNrbGVfZmFzdJSMEl9mdW5jdGlvbl9zZXRzdGF0ZZSTlGgVfZR9lCiMCF9fbmFtZV9flGgPjAxfX3F1YWxuYW1lX1+UaA+MD19fYW5ub3RhdGlvbnNfX5R9lIwOX19rd2RlZmF1bHRzX1+UTowMX19kZWZhdWx0c19flE6MCl9fbW9kdWxlX1+UjCdpbnRlZ3JhdGlvbi50ZXN0X2ludGVncmF0aW9uX1NSX2NvbnRleHSUjAdfX2RvY19flE6MC19fY2xvc3VyZV9flE6MF19jbG91ZHBpY2tsZV9zdWJtb2R1bGVzlF2UjAtfX2dsb2JhbHNfX5R9lHWGlIZSMC4:",
    "fc_hash": "83f8679345fd4b5d215f2b8fcd7c7d51b154084494e92b7ca0a8a5ccf64aafe8",
    "lang": "PY",
    "params": ["gAVLAi4:", "gAVLAy4:", "gAVLBC4:"]
}

MODES = ["sync", "async"]

result = sr.execute_function(function=EXAMPLE_FUNCTION, mode=MODES[0], endpoint=SR_ENDPOINT)

print(result.json())
