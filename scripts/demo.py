"""
demo.py — Full end-to-end PyChain walkthrough.

Run the server first:
    uvicorn main:app --port 5000

Then in another terminal:
    python demo.py

This script demonstrates the full lifecycle:
  1. Generate wallets for Alice and Bob
  2. Alice signs a transaction to Bob
  3. Submit to mempool
  4. Mine the block
  5. Validate the chain
  6. Tamper with a block and see validation fail
"""

import httpx
import json

BASE = "http://localhost:5000"


def separator(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


def pretty(data: dict):
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# 1. Generate wallets
# ---------------------------------------------------------------------------

separator("Step 1: Generate wallets for Alice and Bob")

alice = httpx.post(f"{BASE}/wallet/new").json()["wallet"]
bob   = httpx.post(f"{BASE}/wallet/new").json()["wallet"]
miner = httpx.post(f"{BASE}/wallet/new").json()["wallet"]

print(f"Alice's address : {alice['address']}")
print(f"Bob's address   : {bob['address']}")
print(f"Miner's address : {miner['address']}")


# ---------------------------------------------------------------------------
# 2. Alice signs a transaction to Bob
# ---------------------------------------------------------------------------

separator("Step 2: Alice signs a transaction → 25 coins to Bob")

sign_resp = httpx.post(f"{BASE}/wallet/sign", json={
    "private_key_pem": alice["private_key_pem"],
    "sender": alice["address"],
    "recipient": bob["address"],
    "amount": 25.0,
}).json()

print("Signature (base64):", sign_resp["signature"][:40] + "…")


# ---------------------------------------------------------------------------
# 3. Submit transaction to mempool
# ---------------------------------------------------------------------------

separator("Step 3: Submit transaction to mempool")

tx_resp = httpx.post(f"{BASE}/transactions/new", json={
    "sender": alice["address"],
    "recipient": bob["address"],
    "amount": 25.0,
    "public_key": alice["public_key_pem"],
    "signature": sign_resp["signature"],
}).json()

pretty(tx_resp)

# Check mempool
mempool = httpx.get(f"{BASE}/mempool").json()
print(f"\nMempool: {mempool['pending_count']} pending transaction(s)")


# ---------------------------------------------------------------------------
# 4. Submit a second transaction (Bob → Alice, smaller amount)
# ---------------------------------------------------------------------------

separator("Step 4: Bob sends 5 coins back to Alice")

sign_resp2 = httpx.post(f"{BASE}/wallet/sign", json={
    "private_key_pem": bob["private_key_pem"],
    "sender": bob["address"],
    "recipient": alice["address"],
    "amount": 5.0,
}).json()

httpx.post(f"{BASE}/transactions/new", json={
    "sender": bob["address"],
    "recipient": alice["address"],
    "amount": 5.0,
    "public_key": bob["public_key_pem"],
    "signature": sign_resp2["signature"],
})

print("Bob → Alice 5 coins added to mempool.")
print(f"Mempool now has {httpx.get(f'{BASE}/mempool').json()['pending_count']} transactions.")


# ---------------------------------------------------------------------------
# 5. Mine the block
# ---------------------------------------------------------------------------

separator("Step 5: Mining (PoW — finding nonce with 4 leading zeros)…")

mine_resp = httpx.post(
    f"{BASE}/mine",
    json={"miner_address": miner["address"]},
    timeout=60.0,  # mining can take a few seconds
).json()

block = mine_resp["block"]
print(f"Block #{block['index']} mined!")
print(f"  Hash     : {block['hash']}")
print(f"  Nonce    : {block['nonce']}")
print(f"  Merkle   : {block['merkle_root']}")
print(f"  Txs      : {len(block['transactions'])} (including coinbase reward)")
print(f"  Miner reward: {mine_resp['miner_reward']} coins → {miner['address']}")


# ---------------------------------------------------------------------------
# 6. Check chain
# ---------------------------------------------------------------------------

separator("Step 6: Inspect the chain")

chain = httpx.get(f"{BASE}/chain").json()
print(f"Chain height: {chain['length']} blocks")
for b in chain["chain"]:
    print(f"  Block {b['index']}: {b['hash'][:20]}… ({len(b['transactions'])} txs)")


# ---------------------------------------------------------------------------
# 7. Validate chain
# ---------------------------------------------------------------------------

separator("Step 7: Full chain validation")

validation = httpx.get(f"{BASE}/chain/valid").json()
pretty(validation)


# ---------------------------------------------------------------------------
# 8. Demonstrate tamper detection
# ---------------------------------------------------------------------------

separator("Step 8: Tamper with a transaction and re-validate (expect FAILURE)")

# This is a DIRECT Python manipulation — simulating what would happen
# if someone tried to alter a committed transaction on disk.
from main import blockchain as live_chain   # import the running instance

if len(live_chain.chain) > 1:
    tampered_block = live_chain.chain[1]
    original_amount = tampered_block.transactions[1]["amount"]
    tampered_block.transactions[1]["amount"] = 9999.0   # try to double-spend!
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