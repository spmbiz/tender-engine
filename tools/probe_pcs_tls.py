from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOST = "api.publiccontractsscotland.gov.uk"


def run(*cmd):
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=45)
    return {"rc": p.returncode, "stdout": p.stdout[-30000:], "stderr": p.stderr[-10000:]}


def main():
    payload = {
        "schema": "PCS_TLS_CHAIN_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": HOST,
    }

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((HOST, 443), timeout=30) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST) as tls:
            der = tls.getpeercert(binary_form=True)
            payload["tls_version"] = tls.version()
            payload["leaf_sha256"] = hashlib.sha256(der).hexdigest()
            pem = ssl.DER_cert_to_PEM_cert(der)

    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
        fh.write(pem)
        leaf = fh.name
    x509 = run("openssl", "x509", "-in", leaf, "-noout", "-subject", "-issuer", "-dates", "-fingerprint", "-sha256", "-text")
    payload["leaf_openssl"] = x509
    text = x509["stdout"]
    aia = re.findall(r"CA Issuers\s*-\s*URI:([^\s]+)", text)
    payload["ca_issuers_urls"] = aia

    sclient = subprocess.run(
        ["openssl", "s_client", "-showcerts", "-connect", f"{HOST}:443", "-servername", HOST],
        input="", text=True, capture_output=True, timeout=45,
    )
    chain_text = sclient.stdout + "\n" + sclient.stderr
    certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", chain_text, re.S)
    payload["certs_sent_by_server"] = len(certs)
    payload["s_client_tail"] = chain_text[-12000:]
    payload["sent_certificates"] = []
    for i, cert in enumerate(certs):
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
            fh.write(cert + "\n")
            p = fh.name
        meta = run("openssl", "x509", "-in", p, "-noout", "-subject", "-issuer", "-fingerprint", "-sha256")
        payload["sent_certificates"].append({"index": i, **meta})

    payload["curl_verified"] = run("curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", f"https://{HOST}/v1")
    payload["curl_insecure"] = run("curl", "-k", "-sS", "-o", "/dev/null", "-w", "%{http_code}", f"https://{HOST}/v1")

    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_tls_probe.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
