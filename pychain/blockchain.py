"""
blockchain.py — Core data structures with SQLite persistence.
"""

import hashlib
import json
import time

import db
from wallet import verify_transaction


def merkle_root(transactions: list[dict]) -> str:
    if not transactions:
        return hashlib.sha256(b"").hexdigest()
    layer = [
        hashlib.sha256(json.dumps(tx, sort_keys=True).encode()).hexdigest()
        for tx in transactions
    ]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256((layer[i] + layer[i + 1]).encode()).hexdigest()
            for i in range(0, len(layer), 2)
        ]
    return layer[0]


class Block:
    def __init__(self, index, transactions, previous_hash, nonce=0, timestamp=None):
        self.index = index
        self.timestamp = timestamp or time.time()
        self.transactions = transactions
        self.merkle_root = merkle_root(transactions)
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash: str = ""

    def compute_hash(self) -> str:
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
        block = cls(
            index=data["index"],
            transactions=data["transactions"],
            previous_hash=data["previous_hash"],
            nonce=data["nonce"],
            timestamp=data["timestamp"],
        )
        block.hash = data["hash"]
        return block


class Blockchain:
    DIFFICULTY = 4
    MINING_REWARD = 10.0

    def __init__(self):
        self.pending_transactions: list[dict] = []
        existing = db.load_chain()
        if existing:
            self.chain = [Block.from_dict(b) for b in existing]
        else:
            self.chain: list[Block] = []
            self._create_genesis_block()

    def _create_genesis_block(self) -> None:
        genesis = Block(index=0, transactions=[], previous_hash="0")
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)
        db.save_block(genesis)

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    @property
    def height(self) -> int:
        return len(self.chain)

    def add_transaction(self, transaction: dict) -> int:
        required = {"sender", "recipient", "amount", "public_key", "signature"}
        if not required.issubset(transaction.keys()):
            raise ValueError(f"Missing fields: {required - transaction.keys()}")
        if transaction["amount"] <= 0:
            raise ValueError("Amount must be positive.")
        if transaction["sender"] != "NETWORK":
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
        return self.last_block.index + 1

    def proof_of_work(self, block: Block) -> str:
        block.nonce = 0
        computed = block.compute_hash()
        target = "0" * self.DIFFICULTY
        while not computed.startswith(target):
            block.nonce += 1
            computed = block.compute_hash()
        return computed

    def mine_pending_transactions(self, miner_address: str) -> Block:
        if not self.pending_transactions:
            raise ValueError("No pending transactions.")
        coinbase = {
            "sender": "NETWORK",
            "recipient": miner_address,
            "amount": self.MINING_REWARD,
            "public_key": "",
            "signature": "",
        }
        all_transactions = [coinbase] + self.pending_transactions
        block = Block(
            index=len(self.chain),
            transactions=all_transactions,
            previous_hash=self.last_block.hash,
        )
        block.hash = self.proof_of_work(block)
        self.chain.append(block)
        db.save_block(block)
        self.pending_transactions = []
        return block

    def is_valid_chain(self, chain=None) -> tuple[bool, str]:
        chain = chain or self.chain
        for i in range(1, len(chain)):
            curr, prev = chain[i], chain[i - 1]
            if curr.hash != curr.compute_hash():
                return False, f"Block {i}: hash mismatch"
            if not curr.hash.startswith("0" * self.DIFFICULTY):
                return False, f"Block {i}: PoW not satisfied"
            if curr.previous_hash != prev.hash:
                return False, f"Block {i}: broken link"
            if curr.merkle_root != merkle_root(curr.transactions):
                return False, f"Block {i}: Merkle mismatch"
            for j, tx in enumerate(curr.transactions):
                if tx["sender"] == "NETWORK":
                    continue
                payload = {
                    "sender": tx["sender"],
                    "recipient": tx["recipient"],
                    "amount": tx["amount"],
                }
                if not verify_transaction(tx["public_key"], payload, tx["signature"]):
                    return False, f"Block {i}, tx {j}: invalid signature"
        return True, "valid"

    def to_dict(self) -> dict:
        return {"chain": [b.to_dict() for b in self.chain], "length": len(self.chain)}

    def replace_chain(self, new_chain_data: list[dict]) -> bool:
        if len(new_chain_data) <= len(self.chain):
            return False
        new_chain = [Block.from_dict(b) for b in new_chain_data]
        valid, _ = self.is_valid_chain(new_chain)
        if not valid:
            return False
        self.chain = new_chain
        for block in self.chain:
            db.save_block(block)
        return True
