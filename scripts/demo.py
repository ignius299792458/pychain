"""
demo.py — Full end-to-end PyChain walkthrough.

Run the server first:
    uvicorn main:app --port 5000

Then in another terminal:
    python demo.py

This script demonstrates the full lifecycle:
  1. Generate wallets for Alice, Bob, and the miner
  2. Alice signs a transaction to Bob
  3. Submit to mempool
  4. Bob sends coins back to Alice
  5. Mine the block (PoW)
  6. Inspect the chain
  7. Validate the chain
  8. Tamper with a block and see validation fail
"""

import json

import httpx

BASE = "http://localhost:5000"

# Passwords used to encrypt each wallet in the DB
ALICE_PASSWORD = "alice_secret"
BOB_PASSWORD = "bob_secret"
MINER_PASSWORD = "miner_secret"


def separator(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def pretty(data: dict):
    print(json.dumps(data, indent=2))


def post(path: str, payload: dict, timeout: float = 10.0) -> dict:
    resp = httpx.post(f"{BASE}{path}", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get(path: str) -> dict:
    resp = httpx.get(f"{BASE}{path}")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Generate wallets
# ---------------------------------------------------------------------------

separator("Step 1: Generate wallets for Alice, Bob, and miner")

alice = post("/wallet/new", {"password": ALICE_PASSWORD})["wallet"]
bob = post("/wallet/new", {"password": BOB_PASSWORD})["wallet"]
miner = post("/wallet/new", {"password": MINER_PASSWORD})["wallet"]

print(f"Alice's address : {alice['address']}")
print(f"Bob's address   : {bob['address']}")
print(f"Miner's address : {miner['address']}")


# ---------------------------------------------------------------------------
# 2. Retrieve stored wallets (decrypt from DB)
# ---------------------------------------------------------------------------

separator("Step 2: Retrieve and decrypt stored wallets")

alice_loaded = httpx.get(f"{BASE}/wallet", params={"password": ALICE_PASSWORD}).json()
print("Alice wallet from DB:", alice_loaded["wallet"]["address"])


# ---------------------------------------------------------------------------
# 3. Alice signs a transaction to Bob
# ---------------------------------------------------------------------------

separator("Step 3: Alice signs a transaction → 25 coins to Bob")

sign_resp = post(
    "/wallet/sign",
    {
        "private_key_pem": alice["private_key_pem"],
        "sender": alice["address"],
        "recipient": bob["address"],
        "amount": 25.0,
    },
)

print("Signature (base64):", sign_resp["signature"][:40] + "…")


# ---------------------------------------------------------------------------
# 4. Submit Alice → Bob transaction to mempool
# ---------------------------------------------------------------------------

separator("Step 4: Submit transaction to mempool")

tx_resp = post(
    "/transactions/new",
    {
        "sender": alice["address"],
        "recipient": bob["address"],
        "amount": 25.0,
        "public_key": alice["public_key_pem"],
        "signature": sign_resp["signature"],
    },
)

pretty(tx_resp)

mempool = get("/mempool")
print(f"\nMempool: {mempool['pending_count']} pending transaction(s)")


# ---------------------------------------------------------------------------
# 5. Bob signs and submits a transaction back to Alice
# ---------------------------------------------------------------------------

separator("Step 5: Bob sends 5 coins back to Alice")

sign_resp2 = post(
    "/wallet/sign",
    {
        "private_key_pem": bob["private_key_pem"],
        "sender": bob["address"],
        "recipient": alice["address"],
        "amount": 5.0,
    },
)

post(
    "/transactions/new",
    {
        "sender": bob["address"],
        "recipient": alice["address"],
        "amount": 5.0,
        "public_key": bob["public_key_pem"],
        "signature": sign_resp2["signature"],
    },
)

print("Bob → Alice 5 coins added to mempool.")
print(f"Mempool now has {get('/mempool')['pending_count']} transactions.")


# ---------------------------------------------------------------------------
# 6. Mine the block
# ---------------------------------------------------------------------------

separator("Step 6: Mining (PoW — finding nonce with 4 leading zeros)…")

mine_resp = post("/mine", {"miner_address": miner["address"]}, timeout=60.0)

block = mine_resp["block"]
print(f"Block #{block['index']} mined!")
print(f"  Hash        : {block['hash']}")
print(f"  Nonce       : {block['nonce']}")
print(f"  Merkle root : {block['merkle_root']}")
print(f"  Txs         : {len(block['transactions'])} (including coinbase reward)")
print(f"  Miner reward: {mine_resp['miner_reward']} coins → {miner['address']}")


# ---------------------------------------------------------------------------
# 7. Inspect the chain
# ---------------------------------------------------------------------------

separator("Step 7: Inspect the full chain")

chain = get("/chain")
print(f"Chain height: {chain['length']} blocks")
for b in chain["chain"]:
    print(f"  Block {b['index']}: {b['hash'][:20]}… ({len(b['transactions'])} txs)")


# ---------------------------------------------------------------------------
# 8. Validate chain
# ---------------------------------------------------------------------------

separator("Step 8: Full chain validation")

validation = get("/chain/valid")
pretty(validation)


# ---------------------------------------------------------------------------
# 9. Demonstrate tamper detection
# ---------------------------------------------------------------------------

separator("Step 9: Tamper with a transaction and re-validate (expect FAILURE)")

# Direct in-process manipulation — simulates an attacker altering a committed
# block in memory. In a real node this would mean modifying the DB on disk.
from main import blockchain as live_chain

from pychain.blockchain import Blockchain as _BC

if live_chain.height > 1:
    tampered_block = live_chain.chain[1]
    original_amount = tampered_block.transactions[1]["amount"]
    tampered_block.transactions[1]["amount"] = 9999.0  # double-spend attempt
    print(f"Tampered tx amount: {original_amount} → 9999.0")

    valid, reason = live_chain.is_valid_chain()
    print(f"\nChain valid after tampering? {valid}")
    print(f"Reason: {reason}")

    # Restore
    tampered_block.transactions[1]["amount"] = original_amount
    valid, reason = live_chain.is_valid_chain()
    print(f"\nChain valid after restoring? {valid}")
else:
    print("Need at least 2 blocks for tamper demo — mine one more block first.")


print("\n\nDemo complete. Visit http://localhost:5000/docs for the interactive API.")
