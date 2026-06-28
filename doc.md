```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                           PYCHAIN — FULL PROCESS FLOW                           ║
╚══════════════════════════════════════════════════════════════════════════════════╝

  CLIENT (curl / demo.py / Swagger UI)
       │
       │  HTTP Request
       ▼
╔═════════════════════════════════════════════════════════════════════════════╗
║  main.py  —  FastAPI REST layer                                             ║
║                                                                             ║
║   POST /wallet/new          POST /transactions/new      POST /mine          ║
║   POST /wallet/sign         GET  /mempool               GET  /chain         ║
║   POST /nodes/register      GET  /nodes/resolve         GET  /chain/valid   ║
╚══════════╤══════════════════════════╤══════════════════════════╤════════════╝
           │                          │                          │
           ▼                          ▼                          ▼
╔══════════════════╗     ╔════════════════════════╗     ╔═══════════════════╗
║   wallet.py      ║     ║    blockchain.py        ║     ║  node_network.py  ║
║                  ║     ║                         ║     ║                   ║
║ generate_wallet()║     ║  Blockchain (singleton) ║     ║ register_nodes()  ║
║                  ║     ║  ┌─────────────────┐    ║     ║                   ║
║  ECDSA secp256k1 ║     ║  │ .chain []       │    ║     ║ resolve_conflicts ║
║  private_key ─┐  ║     ║  │ .pending_txs [] │    ║     ║  async fan-out    ║
║  public_key  ─┤  ║     ║  └────────┬────────┘    ║     ║  to all peers     ║
║  address      │  ║     ║           │              ║     ║                   ║
║               │  ║     ║  add_transaction()       ║     ║  GET /chain from  ║
║ sign_tx()  ◄──┘  ║     ║  ┌──────────────────┐   ║     ║  each peer node   ║
║  SHA-256 digest  ║     ║  │ verify sig ───────────────► wallet.verify_tx() ║
║  DER signature   ║     ║  │ amount > 0       │   ║     ║                   ║
║                  ║     ║  │ push to mempool  │   ║     ║  longest valid    ║
║ verify_tx()      ║     ║  └──────────────────┘   ║     ║  chain wins       ║
║  True / False    ║     ║           │              ║     ║  (Nakamoto rule)  ║
╚══════════════════╝     ║           │ mine()       ║     ╚═══════════════════╝
                         ║           ▼              ║
                         ║  ┌─────────────────────┐ ║
                         ║  │  1. coinbase tx      │ ║
                         ║  │     NETWORK → miner  │ ║
                         ║  │                      │ ║
                         ║  │  2. merkle_root()    │ ║
                         ║  │     hash all txs     │ ║
                         ║  │     build binary     │ ║
                         ║  │     hash tree        │ ║
                         ║  │     → single root    │ ║
                         ║  │                      │ ║
                         ║  │  3. proof_of_work()  │ ║
                         ║  │     nonce = 0        │ ║
                         ║  │     loop:            │ ║
                         ║  │       hash(block)    │ ║
                         ║  │       starts "0000"? │ ║
                         ║  │       no → nonce++   │ ║
                         ║  │       yes → done     │ ║
                         ║  └──────────┬──────────┘ ║
                         ║             │             ║
                         ║             ▼             ║
                         ║  ┌─────────────────────┐  ║
                         ║  │      Block           │  ║
                         ║  │  ┌───────────────┐   │  ║
                         ║  │  │ index         │   │  ║
                         ║  │  │ timestamp     │   │  ║
                         ║  │  │ transactions[]│   │  ║
                         ║  │  │ merkle_root   │   │  ║
                         ║  │  │ previous_hash │   │  ║
                         ║  │  │ nonce         │   │  ║
                         ║  │  │ hash  ◄───────────────── SHA-256(index
                         ║  │  └───────────────┘   │  ║              + ts
                         ║  └──────────┬──────────┘  ║              + merkle_root
                         ║             │              ║              + prev_hash
                         ║             ▼              ║              + nonce)
                         ║  chain.append(block)       ║
                         ║  pending_txs = []          ║
                         ╚════════════════════════════╝


 THE CHAIN — how blocks link together
 ─────────────────────────────────────────────────────────────────────────────────

  ┌──────────────────────┐      ┌──────────────────────┐      ┌────────────────────┐
  │   Block #0 (genesis) │      │     Block #1          │      │     Block #2        │
  │                      │      │                       │      │                     │
  │  index:  0           │      │  index:  1            │      │  index: 2           │
  │  prev:   "0"         │  ┌──►│  prev:   9d56993b...  │  ┌──►│  prev: 00009361...  │
  │  merkle: e3b0c4...   │  │   │  merkle: 6909860...   │  │   │  merkle: a1b2c3...  │
  │  nonce:  0           │  │   │  nonce:  126328        │  │   │  nonce: 84201       │
  │  hash:   9d56993b... ├──┘   │  hash:   00009361... ├──┘   │  hash: 0000fa2b...  │
  └──────────────────────┘      └──────────────────────┘      └────────────────────┘
   starts with anything           starts with "0000"            starts with "0000"
   (no PoW on genesis)            ← PoW satisfied               ← PoW satisfied

  TAMPER DETECTION: change any field in Block #1
    → its hash changes
    → Block #2's prev_hash no longer matches
    → is_valid_chain() fails at Block #2
    → chain is rejected


 MERKLE TREE — inside a single block
 ─────────────────────────────────────────────────────────────────────────────────

  transactions: [tx0, tx1, tx2, tx3]

  SHA-256(tx0)    SHA-256(tx1)    SHA-256(tx2)    SHA-256(tx3)
      h0              h1              h2              h3
       └──────┬───────┘               └──────┬────────┘
          SHA-256(h0+h1)               SHA-256(h2+h3)
              h01                          h23
               └───────────────┬───────────┘
                          SHA-256(h01+h23)
                            merkle_root              ← stored in block header
                                                        one hash commits to ALL txs
  odd tx count → duplicate last leaf (Bitcoin-standard)
  tamper any tx → merkle_root changes → block hash changes → chain breaks


 NAKAMOTO CONSENSUS — across peer nodes
 ─────────────────────────────────────────────────────────────────────────────────

  node A (you)           node B (peer)          node C (peer)
  height: 3              height: 5              height: 4
  chain: A→B→C           chain: A→B→C→D→E       chain: A→B→C→D

  GET /nodes/resolve
  ├── fetch node B /chain ──────────────────────► length=5, valid ✓
  ├── fetch node C /chain ────────────────────────────────────────► length=4, valid ✓
  │
  │   best valid chain = node B (length 5 > local 3)
  │
  └── replace_chain(node_B_chain)
        is_valid_chain() ← full re-validation before adopting:
          ✓ every hash matches compute_hash()
          ✓ every hash starts with "0000"
          ✓ every prev_hash links correctly
          ✓ every merkle_root matches transactions
          ✓ every signature is valid
        → self.chain = node_B_chain   ← longest valid chain wins


 FILE RESPONSIBILITY MAP
 ─────────────────────────────────────────────────────────────────────────────────

  wallet.py         owns:  cryptographic identity
                    knows: nothing about the chain

  blockchain.py     owns:  Block, chain, PoW, Merkle, validation
                    uses:  wallet.verify_transaction()

  node_network.py   owns:  peer list, consensus resolution
                    uses:  blockchain.is_valid_chain(), blockchain.replace_chain()

  main.py           owns:  HTTP interface, request parsing, routing
                    uses:  all three modules above
                    holds: one Blockchain instance, one NodeNetwork instance

  demo.py           owns:  end-to-end test script
                    uses:  main.py via HTTP (httpx)

  .vscode/
  launch.json       owns:  7 debug configs + 2 compound launchers
                    uses:  .venv/bin/python, .env


 REQUEST LIFECYCLE — POST /transactions/new
 ─────────────────────────────────────────────────────────────────────────────────

  curl POST /transactions/new  {sender, recipient, amount, public_key, signature}
       │
       ▼
  main.py: TransactionIn (Pydantic validates types + amount > 0)
       │
       ▼
  blockchain.add_transaction(tx)
       ├── required fields present?         no  → ValueError 400
       ├── amount > 0?                      no  → ValueError 400
       ├── sender == "NETWORK"?             yes → skip sig check (coinbase)
       └── wallet.verify_transaction()
               load public_key from PEM
               canonical_bytes = json.dumps({sender,recipient,amount}, sort_keys=True)
               ECDSA.verify(signature, canonical_bytes)
               valid? yes → pending_txs.append(tx)  → return block_index
                      no  → ValueError 400 "Invalid transaction signature"


 REQUEST LIFECYCLE — POST /mine
 ─────────────────────────────────────────────────────────────────────────────────

  curl POST /mine  {miner_address}
       │
       ▼
  main.py → blockchain.mine_pending_transactions(miner_address)
       │
       ├── prepend coinbase {NETWORK → miner, amount: 10.0}
       │
       ├── Block(index, all_transactions, previous_hash=last_block.hash)
       │     └── merkle_root(transactions)  ← hash tree over all txs
       │
       ├── proof_of_work(block)
       │     nonce=0 … SHA-256(block) … "0000"? … nonce++ … repeat
       │     (avg ~65000 iterations at difficulty=4)
       │
       ├── block.hash = winning_hash
       ├── chain.append(block)
       └── pending_txs = []

       ▼
  200 { block: { index, hash, nonce, merkle_root, transactions[] } }
```
