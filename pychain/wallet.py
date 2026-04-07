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
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

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


def verify_transaction(
    public_key_pem: str, transaction: dict, signature_b64: str
) -> bool:
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


def encrypt_private_key(private_key: str, password: str) -> str:
    """
    Encrypts a PEM private key string using a password.

    Password is hashed with SHA-256 to produce a 32-byte key,
    then base64url-encoded to satisfy Fernet's key format requirement.

    Returns a base64-encoded encrypted string safe to store in DB or file.
    """
    enc_key = hashlib.sha256(password.encode()).digest()
    f = Fernet(base64.urlsafe_b64encode(enc_key))

    # PEM is a str — encode to bytes before encrypting
    encrypted = f.encrypt(private_key.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_private_key(encrypted_private_key: str, password: str) -> str:
    """
    Decrypts an encrypted private key blob back to PEM string.

    Raises cryptography.fernet.InvalidToken if password is wrong —
    caller should catch this and handle as 'wrong password'.

    Never store the return value — use it to sign, then discard from memory.
    """
    enc_key = hashlib.sha256(password.encode()).digest()
    f = Fernet(base64.urlsafe_b64encode(enc_key))

    # encrypted_private_key is str — encode back to bytes for Fernet
    decrypted = f.decrypt(encrypted_private_key.encode("utf-8"))
    return decrypted.decode("utf-8")  # returns PEM string


def encrypt_and_save_wallet(wallet: dict, password: str):
    """
    Encrypts the private key and saves the full wallet to a JSON file.

    Private key is encrypted before writing — public key and address
    are safe to store as plaintext.

    Structure saved:
        {
            "address": "...",
            "public_key_pem": "...",
            "private_key_encrypted": "..."   ← never raw
        }
    """
    filepath = os.getenv("WALLET_FILE_PATH")
    encrypted_private_key = encrypt_private_key(wallet["private_key_pem"], password)

    with open(filepath, "r") as f:
        existing_wallets = json.load(f)

    wallet_to_save = [
        *existing_wallets,
        {
            "address": wallet["address"],
            "public_key_pem": wallet["public_key_pem"],
            "private_key_encrypted": encrypted_private_key,  # encrypted blob only
            "password": password,
        },
    ]

    with open(filepath, "w") as f:
        json.dump(wallet_to_save, f, indent=2)


def load_and_decrypt_wallet(password: str) -> dict:
    """
    Loads wallet from file and decrypts the private key into memory.

    Pair this with encrypt_and_save_wallet — completes the round trip.
    Raises Fernet.InvalidToken if password is wrong.
    """
    filepath = os.getenv("WALLET_FILE_PATH")
    with open(filepath, "r") as f:
        wallet_data = json.load(f)

    if wallet_data["password"] != password:
        raise Exception("Password mismatched")

    private_key_pem = decrypt_private_key(
        wallet_data["private_key_encrypted"], password
    )

    return {
        "address": wallet_data["address"],
        "public_key_pem": wallet_data["public_key_pem"],
        "private_key_pem": private_key_pem,  # back in memory, use and discard
    }
