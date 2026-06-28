# PyChain

PyChain is a lightweight blockchain prototype built in Python with FastAPI. It demonstrates core blockchain concepts such as wallets, signed transactions, proof of work, Merkle trees, block validation, and peer-to-peer chain synchronization in a compact, easy-to-run codebase.

## About this project

PyChain is designed as a learning-oriented implementation of a minimal blockchain system. It includes:

- ECDSA-based wallet generation and transaction signing
- Transaction validation before admission to the mempool
- Proof-of-work mining with a configurable difficulty
- Merkle root generation for each block
- SQLite-based persistence for blocks and peer nodes
- A simple REST API for interacting with the chain
- Basic Nakamoto-style consensus via peer node chain resolution

This project is intentionally simple and should be treated as a reference implementation rather than a production blockchain platform.

## Architecture

The project is organized around five main responsibilities:

- [pychain/main.py](pychain/main.py): FastAPI application and REST endpoints
- [pychain/blockchain.py](pychain/blockchain.py): Block, chain, mining, validation, and Merkle logic
- [pychain/wallet.py](pychain/wallet.py): Wallet creation, transaction signing, and signature verification
- [pychain/node_network.py](pychain/node_network.py): Peer registration and chain conflict resolution
- [pychain/db.py](pychain/db.py): SQLite storage for blocks and peers

A simple text-based view of the system looks like this:

```text
+-------------------+        +------------------------+
|   Client / API    | <----> |   FastAPI app         |
|   (curl, Swagger) |        |   pychain/main.py     |
+-------------------+        +-----------+------------+
                                         |
                                         v
                              +------------------------+
                              |   Blockchain Core      |
                              |   pychain/blockchain   |
                              | - blocks               |
                              | - mempool              |
                              | - mining / PoW         |
                              +-----------+------------+
                                          |
                  +-----------------------+-----------------------+
                  |                       |                       |
                  v                       v                       v
      +-------------------+   +--------------------+   +---------------------+
      | Wallet Layer      |   | Peer Network       |   | Persistence Layer   |
      | pychain/wallet.py |   | pychain/node_net   |   | pychain/db.py       |
      | - key generation  |   | - peer registry    |   | - SQLite blocks     |
      | - signing         |   | - chain sync       |   | - peer storage      |
      +-------------------+   +--------------------+   +---------------------+

```

### Request flow

1. A client creates or loads a wallet.
2. A signed transaction is submitted to the API.
3. The transaction is added to the mempool after signature verification.
4. A miner calls the mining endpoint to create a new block.
5. The new block is persisted and becomes part of the chain.
6. Peer nodes can register and synchronize the longest valid chain.

## How to run

### Prerequisites

- Python 3.12+
- Poetry

### 1. Install dependencies

```bash
poetry install
```

### 2. Set the wallet file path

The wallet persistence code expects a wallet file path in the environment:

```bash
export WALLET_FILE_PATH=wallet.json
```

### 3. Start the API server

```bash
poetry run uvicorn pychain.main:app --reload --port 5000
```

The API will be available at:

- http://localhost:5000/docs for Swagger UI
- http://localhost:5000/redoc for ReDoc

### 4. Example workflow

Create a wallet:

```bash
curl -X POST http://localhost:5000/wallet/new \
  -H "Content-Type: application/json" \
  -d '{"password":"secret"}'
```

Sign a transaction (example payload):

```bash
curl -X POST http://localhost:5000/wallet/sign \
  -H "Content-Type: application/json" \
  -d '{
    "private_key_pem":"<your-private-key>",
    "sender":"<sender-address>",
    "recipient":"<recipient-address>",
    "amount": 5.0
  }'
```

Submit a transaction:

```bash
curl -X POST http://localhost:5000/transactions/new \
  -H "Content-Type: application/json" \
  -d '{
    "sender":"<sender-address>",
    "recipient":"<recipient-address>",
    "amount": 5.0,
    "public_key":"<public-key>",
    "signature":"<base64-signature>"
  }'
```

Mine the pending transactions:

```bash
curl -X POST http://localhost:5000/mine \
  -H "Content-Type: application/json" \
  -d '{"miner_address":"<miner-address>"}'
```

### 5. Run tests

```bash
poetry run pytest
```

## Notes

- The chain data is stored in the SQLite database under the default location [data/pychain.db](data/pychain.db).
- Wallets are stored in [wallet.json](wallet.json) by default when the environment variable is set.
- This implementation is educational and intentionally minimal; it does not include full networking, persistent identity, or production-grade security features.
