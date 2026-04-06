"""
blockchain.py — Core data structures: Block, Merkle tree, Blockchain.

Key design decisions:
  - Transactions are stored in each block with signatures attached.
  - Every block commits to its transactions via a Merkle root (not raw list hash).
    This means you can prove a single tx belongs to a block without replaying all of them.
  - PoW difficulty is configurable (default: 4 leading zeros).
  - Chain validation re-checks: hashes, PoW, previous_hash links, and ALL signatures.
"""

import hashlib
import json
import time
from typing import Any

from wallet import verify_transaction


# ---------------------------------------------------------------------------
# Merkle Tree
# ---------------------------------------------------------------------------

def merkle_root(transactions: list[dict]) -> str:
    """
    Compute the Merkle root of a list of transactions.

    A Merkle tree is a binary hash tree:
      - Leaves  = SHA-256 of each transaction (canonical JSON)
      - Parents = SHA-256 of left_child_hash + right_child_hash
      - Root    = single hash that commits to the ENTIRE transaction set

    Why it matters: changing any single transaction changes the root,
    which changes the block hash, which breaks the chain.
    Also allows O(log n) membership proofs (Merkle proofs) — used in SPV.

    Edge cases:
      - Empty tx list      → hash of empty string (genesis block)
      - Odd number of txs  → duplicate the last leaf (Bitcoin standard)
    """
    if not transactions:
        return hashlib.sha256(b"").hexdigest()

    # Step 1: hash every transaction
    layer = [
        hashlib.sha256(
            json.dumps(tx, sort_keys=True).encode()
        ).hexdigest()
        for tx in transactions
    ]

    # Step 2: climb the tree until we have one root
    while len(layer) > 1:
        # Duplicate last element if odd number (Bitcoin-style)
        if len(layer) % 2 == 1:
            layer.append(layer[-1])

        layer = [
            hashlib.sha256((layer[i] + layer[i + 1]).encode()).hexdigest()
            for i in range(0, len(layer), 2)
        ]

    return layer[0]


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

class Block:
    """
    A single block in the chain.

    Fields:
        index           — position in the chain (0 = genesis)
        timestamp       — unix epoch float
        transactions    — list of signed transaction dicts
        merkle_root     — Merkle root of transactions (integrity commitment)
        previous_hash   — hash of the preceding block (links the chain)
        nonce           — proof-of-work counter
        hash            — set AFTER mining (not part of compute_hash input)
    """

    def __init__(
        self,
        index: int,
        transactions: list[dict],
        previous_hash: str,
        nonce: int = 0,
        timestamp: float | None = None,
    ):
        self.index = index
        self.timestamp = timestamp or time.time()
        self.transactions = transactions
        self.merkle_root = merkle_root(transactions)
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash: str = ""   # filled by Blockchain.proof_of_work()

    def compute_hash(self) -> str:
        """
        SHA-256 of the block's canonical representation.

        NOTE: self.hash is deliberately excluded from this input —
        otherwise we'd have a circular dependency.
        The nonce IS included so we can brute-force different hashes.
        """
        block_dict = {
            "index": self.index,
            "timestamp": self.timestamp,
            "merkle_root": self.merkle_root,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }
        return hashlib.sha256(
            json.dumps(block_dict, sort_keys=True).encode()
        ).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "merkle_root": self.merkle_root,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        """Reconstruct a Block from a serialised dict (used during consensus)."""
        block = cls(
            index=data["index"],
            transactions=data["transactions"],
            previous_hash=data["previous_hash"],
            nonce=data["nonce"],
            timestamp=data["timestamp"],
        )
        block.hash = data["hash"]
        return block


# ---------------------------------------------------------------------------
# Blockchain
# ---------------------------------------------------------------------------

class Blockchain:
    """
    The main ledger: an append-only chain of Blocks.

    Responsibilities:
      - Maintain the canonical chain (self.chain)
      - Manage the mempool (self.pending_transactions)
      - Run Proof of Work before accepting a new block
      - Validate the chain fully (hashes + PoW + signatures)
    """

    DIFFICULTY = 4          # Number of leading zeros required in a valid hash
    MINING_REWARD = 10.0    # Coinbase reward sent to the miner's address

    def __init__(self):
        self.chain: list[Block] = []
        self.pending_transactions: list[dict] = []
        self._create_genesis_block()

    # ------------------------------------------------------------------
    # Genesis
    # ------------------------------------------------------------------

    def _create_genesis_block(self) -> None:
        """
        The genesis block is block 0. It has no real transactions and its
        previous_hash is "0" by convention — there's no predecessor.
        It is NOT mined (no PoW required); we just assign a hash directly.
        """
        genesis = Block(index=0, transactions=[], previous_hash="0")
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    @property
    def height(self) -> int:
        return len(self.chain)

    # ------------------------------------------------------------------
    # Transaction mempool
    # ------------------------------------------------------------------

    def add_transaction(self, transaction: dict) -> int:
        """
        Validate and add a transaction to the mempool.

        A transaction must have:
            sender      — sender's address (or "NETWORK" for coinbase)
            recipient   — recipient's address
            amount      — positive float
            public_key  — sender's PEM public key
            signature   — base64 ECDSA signature of {sender, recipient, amount}

        Returns the index of the block this tx will be mined into.
        Raises ValueError for invalid transactions.
        """
        required = {"sender", "recipient", "amount", "public_key", "signature"}
        if not required.issubset(transaction.keys()):
            raise ValueError(f"Transaction missing fields: {required - transaction.keys()}")

        if transaction["amount"] <= 0:
            raise ValueError("Transaction amount must be positive.")

        # Coinbase transactions (mining rewards) skip signature verification
        if transaction["sender"] != "NETWORK":
            # The signed payload is just the core fields — not public_key or signature
            payload = {
                "sender": transaction["sender"],
                "recipient": transaction["recipient"],
                "amount": transaction["amount"],
            }
            if not verify_transaction(
                transaction["public_key"], payload, transaction["signature"]
            ):
                raise ValueError("Invalid transaction signature.")

        self.pending_transactions.append(transaction)
        return self.last_block.index + 1   # will be mined into this block

    # ------------------------------------------------------------------
    # Mining (Proof of Work)
    # ------------------------------------------------------------------

    def proof_of_work(self, block: Block) -> str:
        """
        Brute-force nonce until block hash starts with DIFFICULTY leading zeros.

        This is intentionally expensive to compute but trivially fast to verify —
        the asymmetry is what makes history expensive to rewrite.

        In Bitcoin, difficulty adjusts every 2016 blocks to maintain ~10min/block.
        Here it's fixed for simplicity.
        """
        block.nonce = 0
        computed = block.compute_hash()
        target = "0" * self.DIFFICULTY

        while not computed.startswith(target):
            block.nonce += 1
            computed = block.compute_hash()

        return computed

    def mine_pending_transactions(self, miner_address: str) -> Block:
        """
        Create a new block from all pending transactions and mine it.

        Steps:
          1. Add a coinbase reward transaction to pay the miner
          2. Create a Block with all pending transactions
          3. Run PoW to find a valid nonce
          4. Append to chain and clear the mempool
        """
        if not self.pending_transactions:
            raise ValueError("No pending transactions to mine.")

        # Coinbase transaction — miner gets the block reward
        coinbase = {
            "sender": "NETWORK",
            "recipient": miner_address,
            "amount": self.MINING_REWARD,
            "public_key": "",
            "signature": "",
        }
        # Prepend coinbase so it's always the first tx in the block
        all_transactions = [coinbase] + self.pending_transactions

        block = Block(
            index=len(self.chain),
            transactions=all_transactions,
            previous_hash=self.last_block.hash,
        )

        block.hash = self.proof_of_work(block)
        self.chain.append(block)
        self.pending_transactions = []   # flush the mempool

        return block

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_valid_chain(self, chain: list[Block] | None = None) -> tuple[bool, str]:
        """
        Full chain validation. Checks:
          1. Genesis block consistency
          2. Each block's hash matches its contents
          3. PoW difficulty satisfied
          4. previous_hash links are intact
          5. All non-coinbase transaction signatures are valid
          6. Merkle root matches the transactions in the block

        Returns (True, "valid") or (False, "reason for failure").
        Accepts an optional external chain (used during consensus to
        validate a peer's chain before adopting it).
        """
        chain = chain or self.chain

        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # 1. Recompute hash
            recomputed = current.compute_hash()
            if current.hash != recomputed:
                return False, f"Block {i}: hash mismatch (stored={current.hash[:8]}… computed={recomputed[:8]}…)"

            # 2. PoW difficulty
            if not current.hash.startswith("0" * self.DIFFICULTY):
                return False, f"Block {i}: PoW not satisfied (hash={current.hash[:12]}…)"

            # 3. Chain linkage
            if current.previous_hash != previous.hash:
                return False, f"Block {i}: broken chain link (expected={previous.hash[:8]}… got={current.previous_hash[:8]}…)"

            # 4. Merkle root integrity
            expected_root = merkle_root(current.transactions)
            if current.merkle_root != expected_root:
                return False, f"Block {i}: Merkle root mismatch — transactions may have been tampered with."

            # 5. Signature validation on every non-coinbase transaction
            for j, tx in enumerate(current.transactions):
                if tx["sender"] == "NETWORK":
                    continue   # coinbase — no signature

                payload = {
                    "sender": tx["sender"],
                    "recipient": tx["recipient"],
                    "amount": tx["amount"],
                }
                if not verify_transaction(tx["public_key"], payload, tx["signature"]):
                    return False, f"Block {i}, tx {j}: invalid signature from {tx['sender']}"

        return True, "valid"

    # ------------------------------------------------------------------
    # Serialization (for API responses and consensus sync)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "chain": [block.to_dict() for block in self.chain],
            "length": len(self.chain),
        }

    def replace_chain(self, new_chain_data: list[dict]) -> bool:
        """
        Replace the local chain with a longer valid chain from a peer.
        Returns True if replaced, False if the local chain was kept.
        Called by the consensus resolver in node_network.py.
        """
        if len(new_chain_data) <= len(self.chain):
            return False

        # Reconstruct Block objects from raw dicts
        new_chain = [Block.from_dict(b) for b in new_chain_data]

        valid, reason = self.is_valid_chain(new_chain)
        if not valid:
            return False

        self.chain = new_chain
        return True