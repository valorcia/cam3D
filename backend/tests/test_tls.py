"""The local CA must only be able to vouch for private addresses (name constraints)."""
import datetime as dt
import shutil
import subprocess

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from cam3d.server.tls import TlsPaths, ca_info, ensure_server_cert

openssl = pytest.mark.skipif(not shutil.which("openssl"), reason="openssl absent")


def _verify(ca, cert) -> subprocess.CompletedProcess:
    return subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(cert)], capture_output=True, text=True)


@openssl
def test_server_certificate_chain_is_valid(tmp_path):
    p = TlsPaths(tmp_path)
    meta = ensure_server_cert(p, ["192.168.1.20"])
    assert "192.168.1.20" in meta["ips"] and "127.0.0.1" in meta["ips"]
    assert _verify(p.ca_crt, p.crt).returncode == 0
    assert (p.ca_key.stat().st_mode & 0o077) == 0           # private key not readable by others
    assert ensure_server_cert(p, ["192.168.1.20"]) == meta   # reused while valid
    meta2 = ensure_server_cert(p, ["192.168.1.21"])          # new LAN address -> re-issued
    assert "192.168.1.21" in meta2["ips"] and meta2["ca_fingerprint_sha256"] == meta["ca_fingerprint_sha256"]
    assert ca_info(p)["fingerprint_sha256"] == meta["ca_fingerprint_sha256"]


@openssl
def test_ca_cannot_sign_public_sites(tmp_path):
    p = TlsPaths(tmp_path)
    ensure_server_cert(p, ["192.168.1.20"])
    ca_key = serialization.load_pem_private_key(p.ca_key.read_bytes(), None)
    ca = x509.load_pem_x509_certificate(p.ca_crt.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    for san in ([x509.DNSName("www.example.com")], [x509.IPAddress(__import__("ipaddress").ip_address("8.8.8.8"))]):
        forged = (x509.CertificateBuilder()
                  .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "forged")]))
                  .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                  .not_valid_before(now).not_valid_after(now + dt.timedelta(days=30))
                  .add_extension(x509.SubjectAlternativeName(san), critical=False)
                  .sign(ca_key, hashes.SHA256()))
        f = tmp_path / "forged.crt"
        f.write_bytes(forged.public_bytes(serialization.Encoding.PEM))
        r = _verify(p.ca_crt, f)
        assert r.returncode != 0 and "subtree violation" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
