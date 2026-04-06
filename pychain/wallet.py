"""
wallet.py — ECDSA wallet using secp256k1 (same curve as Bitcoin/Ethereum).

A "wallet" is just a keypair:
  private_key  →  kept secret, used to SIGN transactions
  public_key   →  shared openly, used to VERIFY signatures and identify the sender

Why secp256k1?
  It's the standard curve for blockchain systems. Fast, battle-tested,
  and produces compact 64-byte signatures.
"""

import base64
import json

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature


# ---------------------------------------------------------------------------
# Wallet generation
# ---------------------------------------------------------------------------

def generate_wallet() -> dict:
    """
    Generate a new wallet (ECDSA keypair on secp256k1).

    Returns a dict with:
        private_key_pem  — PEM-encoded private key (keep secret)
        public_key_pem   — PEM-encoded public key  (share freely)
        address          — shortened public key used as a human-readable address
    """
    private_key = ec.generate_private_key(ec.SECP256K1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    # Address = last 20 chars of base64-encoded public key (simplified, like Ethereum)
    address = base64.b64encode(
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()[-20:]

    return {
        "private_key_pem": private_pem,
        "public_key_pem": public_pem,
        "address": address,
    }


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------

def sign_transaction(private_key_pem: str, transaction: dict) -> str:
    """
    Sign a transaction dict with the given PEM private key.

    The transaction is canonicalised (sorted keys) before signing so that
    key ordering in JSON doesn't affect the signature — same as how
    Ethereum encodes tx data before hashing.

    Returns a base64-encoded DER signature string.
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )

    # Canonical byte representation — sort_keys ensures determinism
    tx_bytes = json.dumps(transaction, sort_keys=True).encode()

    # ECDSA with SHA-256 — DER-encoded signature
    der_sig = private_key.sign(tx_bytes, ec.ECDSA(hashes.SHA256()))

    return base64.b64encode(der_sig).decode()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_transaction(public_key_pem: str, transaction: dict, signature_b64: str) -> bool:
    """
    Verify a transaction signature using the sender's public key.

    Returns True if the signature is valid, False otherwise.
    We never raise — invalid signatures are just rejected silently.

    This is called on every transaction before it's added to the mempool
    AND again when validating the full chain.
    """
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())

        tx_bytes = json.dumps(transaction, sort_keys=True).encode()
        sig_bytes = base64.b64decode(signature_b64)

        public_key.verify(sig_bytes, tx_bytes, ec.ECDSA(hashes.SHA256()))
        return True

    except (InvalidSignature, Exception):
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def public_key_to_address(public_key_pem: str) -> str:
    """Derive the wallet address from a PEM public key."""
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    return base64.b64encode(
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()[-20:]