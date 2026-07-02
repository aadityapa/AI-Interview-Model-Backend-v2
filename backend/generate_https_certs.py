"""
Create self-signed TLS certs for local HTTPS (camera/mic on LAN).
No OpenSSL binary required — uses the `cryptography` package.

SAN includes: localhost, 127.0.0.1, ::1, and your current LAN IPv4 when detectable.
"""
from __future__ import annotations

import datetime
from datetime import timezone
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _load_root_env() -> None:
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _extra_cert_ipv4s() -> list[str]:
    out: list[str] = []
    pub = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    if pub and pub.lower() != "auto":
        host = (urlparse(pub).hostname or "").strip()
        if host and host not in {"localhost", "127.0.0.1", "::1"}:
            try:
                ipaddress.IPv4Address(host)
                out.append(host)
            except ValueError:
                pass
    for part in (os.getenv("CERT_EXTRA_IPS") or "").split(","):
        ip = part.strip()
        if not ip:
            continue
        try:
            ipaddress.IPv4Address(ip)
            if ip not in out:
                out.append(ip)
        except ValueError:
            pass
    return out


def _detect_lan_ipv4() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip if ip and ip != "127.0.0.1" else None
    except OSError:
        return None


def main() -> int:
    _load_root_env()
    cert_dir = Path(__file__).resolve().parent / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    key_path = cert_dir / "key.pem"
    cert_path = cert_dir / "cert.pem"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "karnex-dev-local"),
        ]
    )

    san_list: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.IPAddress(ipaddress.IPv6Address("::1")),
    ]
    cert_ips: list[str] = []
    lip = _detect_lan_ipv4()
    if lip:
        cert_ips.append(lip)
    for ip in _extra_cert_ipv4s():
        if ip not in cert_ips:
            cert_ips.append(ip)
    for ip in cert_ips:
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
            print(f"Including LAN IP in certificate: {ip}")
        except ValueError:
            pass

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=1))
        .not_valid_after(datetime.datetime.now(timezone.utc) + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
    )

    cert = builder.sign(key, hashes.SHA256())

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Wrote {key_path}")
    print(f"Wrote {cert_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
