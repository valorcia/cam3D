"""Local HTTPS for the phone camera.

Mobile browsers only expose the camera (``getUserMedia``) in a *secure
context*. A plain ``http://192.168.x.y`` address is not one, so cam3D creates:

* a **local certificate authority**, generated on this computer, which the
  user chooses to install on the phone (iOS: profile + "full trust"; Android:
  "CA certificate"). It carries X.509 **name constraints**: it can only vouch
  for private network addresses and ``localhost`` / ``*.local``, so even if
  its key leaked it could not impersonate any Internet site;
* a **server certificate** for this computer's current LAN addresses, signed by
  that CA, valid 397 days, re-issued automatically when the addresses change.

Nothing here bypasses browser security: the user explicitly installs and
trusts the CA. Without it, the app still works over HTTP (gallery import and
the phone's native camera through ``<input capture>``).
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PRIVATE_NETS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16", "127.0.0.0/8",
                "fc00::/7", "fe80::/10", "::1/128"]
SERVER_DAYS = 397
CA_DAYS = 3650


@dataclass
class TlsPaths:
    dir: Path

    @property
    def ca_key(self) -> Path: return self.dir / "ca.key"
    @property
    def ca_crt(self) -> Path: return self.dir / "ca.crt"
    @property
    def key(self) -> Path: return self.dir / "server.key"
    @property
    def crt(self) -> Path: return self.dir / "server.crt"
    @property
    def meta(self) -> Path: return self.dir / "server.json"


def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows: ACLs of the user profile apply
        pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _networks_for(addresses: list[str]) -> list[ipaddress._BaseNetwork]:
    nets = [ipaddress.ip_network(n) for n in PRIVATE_NETS]
    for a in addresses:  # e.g. a LAN using a non-RFC1918 range: allow its /24 explicitly
        ip = ipaddress.ip_address(a)
        if not any(ip in n for n in nets):
            nets.append(ipaddress.ip_network(f"{a}/{24 if ip.version == 4 else 64}", strict=False))
    return nets


def ensure_ca(paths: TlsPaths, addresses: list[str]) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    paths.dir.mkdir(parents=True, exist_ok=True)
    if paths.ca_key.exists() and paths.ca_crt.exists():
        key = serialization.load_pem_private_key(paths.ca_key.read_bytes(), None)
        cert = x509.load_pem_x509_certificate(paths.ca_crt.read_bytes())
        if cert.not_valid_after_utc > _now() + dt.timedelta(days=30):
            return key, cert  # type: ignore[return-value]
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"cam3D local CA ({socket.gethostname()[:30]})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "cam3D (local)")])
    nets = _networks_for(addresses)
    permitted = [x509.IPAddress(n) for n in nets] + [x509.DNSName("localhost"), x509.DNSName(".local")]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(minutes=5))
        .not_valid_after(_now() + dt.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                     key_encipherment=False, data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_private(paths.ca_key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    paths.ca_crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths.meta.unlink(missing_ok=True)  # force a new server certificate
    return key, cert


def ensure_server_cert(paths: TlsPaths, addresses: list[str], hostname: str | None = None) -> dict:
    """(Re)issue the server certificate if missing, expiring, or the LAN addresses changed."""
    ca_key, ca_cert = ensure_ca(paths, addresses)
    hostname = (hostname or socket.gethostname()).split(".")[0].lower()
    wanted = sorted(set(addresses) | {"127.0.0.1"})
    names = sorted({"localhost", f"{hostname}.local"})
    if paths.meta.exists() and paths.crt.exists() and paths.key.exists():
        meta = json.loads(paths.meta.read_text(encoding="utf-8"))
        cert = x509.load_pem_x509_certificate(paths.crt.read_bytes())
        constraints = ca_cert.extensions.get_extension_for_class(x509.NameConstraints).value
        allowed = [g.value for g in constraints.permitted_subtrees if isinstance(g, x509.IPAddress)]
        in_ca = all(any(ipaddress.ip_address(a) in n for n in allowed) for a in wanted)
        if meta.get("ips") == wanted and cert.not_valid_after_utc > _now() + dt.timedelta(days=30) and in_ca:
            return meta
        if not in_ca:  # new network outside the CA's constraints: a new CA is needed
            paths.ca_key.unlink(missing_ok=True)
            paths.ca_crt.unlink(missing_ok=True)
            ca_key, ca_cert = ensure_ca(paths, addresses)
    key = ec.generate_private_key(ec.SECP256R1())
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(a)) for a in wanted]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"cam3D {hostname}")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(minutes=5))
        .not_valid_after(_now() + dt.timedelta(days=SERVER_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_private(paths.key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
    paths.crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    meta = {"ips": wanted, "dns": names, "not_after": cert.not_valid_after_utc.isoformat(),
            "ca_fingerprint_sha256": ca_cert.fingerprint(hashes.SHA256()).hex(":").upper()}
    paths.meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def ca_info(paths: TlsPaths) -> dict | None:
    if not paths.ca_crt.exists():
        return None
    cert = x509.load_pem_x509_certificate(paths.ca_crt.read_bytes())
    return {"subject": cert.subject.rfc4514_string(), "not_after": cert.not_valid_after_utc.isoformat(),
            "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(":").upper()}
