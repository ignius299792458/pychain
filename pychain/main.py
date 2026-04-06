"""
main.py — PyChain REST API (FastAPI)

Endpoints:
    POST   /wallet/new              Generate a new wallet (keypair + address)
    POST   /transactions/new        Submit a signed transaction to the mempool
    POST   /mine                    Mine all pending transactions into a new block
    GET    /chain                   Return the full blockchain
    GET    /chain/valid             Validate the full chain
    GET    /mempool                 Inspect pending (unconfirmed) transactions
    POST   /nodes/register          Register peer node(s)
    GET    /nodes/resolve           Run Nakamoto consensus (adopt longest valid chain)

Run:
    uvicorn main:app --reload --port 5000
    uvicorn main:app --reload --port 5001  (second node)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import json

from blockchain import Blockchain
from wallet import generate_wallet, sign_transaction, public_key_to_address
from node_network import NodeNetwork


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PyChain",
    description="A minimal blockchain with ECDSA wallets, PoW, Merkle trees, and peer consensus.",
    version="1.0.0",
)

# Global singletons — in a real system these would be persisted to disk
# (RocksDB, LevelDB, or PostgreSQL) and loaded on startup.
blockchain = Blockchain()
network = NodeNetwork()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TransactionIn(BaseModel):
    sender: str = Field(..., description="Sender wallet address")
    recipient: str = Field(..., description="Recipient wallet address")
    amount: float = Field(..., gt=0, description="Amount to transfer")
    public_key: str = Field(..., description="Sender's PEM public key")
    signature: str = Field(..., description="Base64 ECDSA signature")


class MineRequest(BaseModel):
    miner_address: str = Field(..., description="Address to receive the mining reward")


class NodeListIn(BaseModel):
    nodes: list[str] = Field(..., description="List of peer node URLs")


# ---------------------------------------------------------------------------
# Wallet endpoints
# ---------------------------------------------------------------------------

@app.post("/wallet/new", tags=["Wallet"])
def new_wallet():
    """
    Generate a brand new ECDSA wallet.

    Returns the private key (keep this secret!), public key, and address.
    The private key is only shown once — PyChain does not store it.

    In a production system you'd use a HD wallet (BIP-32) to derive
    multiple addresses from a single seed phrase. Here we keep it simple.
    """
    wallet = generate_wallet()
    return {
        "message": "New wallet created. Store your private key securely — it is not saved.",
        "wallet": wallet,
    }


@app.post("/wallet/sign", tags=["Wallet"])
def sign_tx(body: dict):
    """
    Convenience endpoint: sign a transaction payload with a private key.

    Body: { "private_key_pem": "...", "sender": "...", "recipient": "...", "amount": 5.0 }

    In production, signing ALWAYS happens client-side (never send your private
    key over the network). This endpoint exists for local testing only.
    """
    required = {"private_key_pem", "sender", "recipient", "amount"}
    if not required.issubset(body.keys()):
        raise HTTPException(400, detail=f"Missing fields: {required - body.keys()}")

    payload = {
        "sender": body["sender"],
        "recipient": body["recipient"],
        "amount": body["amount"],
    }
    signature = sign_transaction(body["private_key_pem"], payload)
    return {"signature": signature, "payload": payload}


# ---------------------------------------------------------------------------
# Transaction endpoints
# ---------------------------------------------------------------------------

@app.post("/transactions/new", tags=["Transactions"])
def new_transaction(tx: TransactionIn):
    """
    Submit a signed transaction to the mempool.

    The node verifies the ECDSA signature before accepting.
    Invalid signatures are rejected with 400.

    Transactions sit in the mempool until a miner calls POST /mine.
    """
    try:
        block_index = blockchain.add_transaction(tx.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"Transaction accepted. Will be included in block {block_index}.",
        "transaction": tx.model_dump(exclude={"public_key"}),
    }


@app.get("/mempool", tags=["Transactions"])
def get_mempool():
    """
    Inspect pending (unconfirmed) transactions.
    Useful for checking your tx was accepted before mining.
    """
    return {
        "pending_count": len(blockchain.pending_transactions),
        "transactions": blockchain.pending_transactions,
    }


# ---------------------------------------------------------------------------
# Mining endpoint
# ---------------------------------------------------------------------------

@app.post("/mine", tags=["Mining"])
def mine(req: MineRequest):
    """
    Mine all pending transactions into a new block.

    Steps:
      1. Add a coinbase reward tx (NETWORK → miner_address)
      2. Bundle all pending txs into a new Block
      3. Run Proof of Work (find nonce s.t. hash starts with DIFFICULTY zeros)
      4. Append to chain, flush mempool

    Returns the freshly mined block.

    Mining difficulty is currently fixed at 4 (hash starts with "0000").
    On a modern laptop this takes ~0.1–2 seconds depending on luck.
    """
    if not blockchain.pending_transactions:
        raise HTTPException(
            status_code=400,
            detail="No pending transactions to mine. Submit transactions first.",
        )

    try:
        new_block = blockchain.mine_pending_transactions(req.miner_address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": "Block mined successfully!",
        "block": new_block.to_dict(),
        "miner_reward": Blockchain.MINING_REWARD,
    }


# ---------------------------------------------------------------------------
# Chain endpoints
# ---------------------------------------------------------------------------

@app.get("/chain", tags=["Chain"])
def get_chain():
    """
    Return the full blockchain.

    In Bitcoin this is called the "block explorer" view.
    We expose the full chain including all transaction data.
    In a real implementation you'd paginate this and support
    querying by block height or hash.
    """
    return blockchain.to_dict()


@app.get("/chain/valid", tags=["Chain"])
def validate_chain():
    """
    Run full chain validation:
      - Hash integrity
      - PoW difficulty
      - Chain linkage (previous_hash)
      - Merkle root integrity
      - All transaction signatures

    Returns { valid: bool, reason: str }.
    Use this after receiving a chain from a peer (or to spot tampering).
    """
    valid, reason = blockchain.is_valid_chain()
    return {
        "valid": valid,
        "reason": reason,
        "chain_length": blockchain.height,
    }


@app.get("/chain/block/{index}", tags=["Chain"])
def get_block(index: int):
    """Fetch a single block by index."""
    if index < 0 or index >= len(blockchain.chain):
        raise HTTPException(404, detail=f"Block {index} not found. Chain height: {blockchain.height}")
    return blockchain.chain[index].to_dict()


# ---------------------------------------------------------------------------
# Peer / consensus endpoints
# ---------------------------------------------------------------------------

@app.post("/nodes/register", tags=["Network"])
def register_nodes(node_list: NodeListIn):
    """
    Register one or more peer nodes.

    Example body: { "nodes": ["http://localhost:5001", "http://localhost:5002"] }

    Peers are used by GET /nodes/resolve to run Nakamoto consensus.
    """
    if not node_list.nodes:
        raise HTTPException(400, detail="Provide at least one node URL.")

    registered = network.register_nodes(node_list.nodes)
    return {
        "message": f"Registered {len(registered)} new node(s).",
        "registered": registered,
        "total_peers": list(network.peers),
    }


@app.get("/nodes", tags=["Network"])
def list_nodes():
    """List all registered peer nodes."""
    return {"peers": list(network.peers), "count": len(network.peers)}


@app.get("/nodes/resolve", tags=["Network"])
async def resolve_consensus():
    """
    Run Nakamoto consensus across all registered peers.

    Fetches /chain from every peer, validates each chain, and replaces
    the local chain if a longer valid chain is found.

    This is the "longest chain wins" rule from Satoshi's whitepaper.
    """
    if not network.peers:
        return {
            "replaced": False,
            "message": "No peers registered. Use POST /nodes/register first.",
            "chain_length": blockchain.height,
        }

    replaced, message = await network.resolve_conflicts(blockchain)
    return {
        "replaced": replaced,
        "message": message,
        "chain_length": blockchain.height,
    }


# ---------------------------------------------------------------------------
# Health / info
# ---------------------------------------------------------------------------

@app.get("/", tags=["Info"])
def root():
    return {
        "name": "PyChain",
        "chain_height": blockchain.height,
        "pending_transactions": len(blockchain.pending_transactions),
        "peers": len(network.peers),
        "difficulty": Blockchain.DIFFICULTY,
        "mining_reward": Blockchain.MINING_REWARD,
        "docs": "/docs",
    }