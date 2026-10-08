"""
SSL Certificate Generator for Local HTTPS Server.

Generates a self-signed TLS certificate and private key for serving
the local dashboard over HTTPS, which is required for camera API access
(getUserMedia) on mobile browsers on the LAN.

The cert is cached at app/ssl/ and reused across server restarts.
It covers both 'localhost' and the detected LAN IP address.
"""

import datetime
import ipaddress
import os
import socket
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent.parent / "ssl"
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"


def get_local_ip() -> str:
    """Detect the machine's LAN IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_self_signed_cert(lan_ip: str) -> tuple[str, str]:
    """
    Generate a self-signed TLS certificate covering localhost and the LAN IP.
    Returns (cert_path, key_path).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "LocalAttendanceServer"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Classroom System"),
    ])

    san_entries = [
        x509.DNSName("localhost"),
    ]
    try:
        san_entries.append(x509.IPAddress(ipaddress.IPv4Address(lan_ip)))
    except Exception:
        pass
    # Always add 127.0.0.1
    san_entries.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=825)
        )
        .add_extension(
            x509.SubjectAlternativeName(san_entries),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Write key
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    # Write cert
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return str(CERT_FILE), str(KEY_FILE)


def ensure_ssl_cert() -> tuple[str, str]:
    """
    Return existing cert/key paths, or generate new ones if missing.
    Regenerates if the LAN IP has changed since last generation.
    """
    lan_ip = get_local_ip()
    ip_marker = CERT_DIR / "lan_ip.txt"

    # Check if cert exists and IP hasn't changed
    if CERT_FILE.exists() and KEY_FILE.exists() and ip_marker.exists():
        saved_ip = ip_marker.read_text().strip()
        if saved_ip == lan_ip:
            return str(CERT_FILE), str(KEY_FILE)

    # Generate new cert
    print(f"  Generating self-signed TLS certificate for {lan_ip}...")
    cert_path, key_path = generate_self_signed_cert(lan_ip)
    ip_marker.write_text(lan_ip)
    print(f"  Certificate saved to: {CERT_DIR}")
    return cert_path, key_path


if __name__ == "__main__":
    c, k = ensure_ssl_cert()
    print(f"Cert: {c}")
    print(f"Key:  {k}")
