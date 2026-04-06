"""
node_network.py — Peer node registry and Nakamoto consensus.

Nakamoto consensus rule (from the Bitcoin whitepaper):
  "The longest valid chain wins."

When you call resolve_conflicts(), this node fetches the chain from every
registered peer, validates each one, and replaces its local chain if any
peer has a longer valid chain.

In production (Bitcoin, Ethereum) this happens continuously via the gossip
protocol. Here we expose it as an explicit HTTP endpoint so you can trigger
it manually — useful for demos and debugging.
"""

import httpx
from urllib.parse import urlparse


class NodeNetwork:
    """
    Manages the set of known peer nodes and runs consensus.

    Peers are stored as normalized base URLs, e.g.:
        "http://192.168.1.10:5001"
        "http://peer.example.com:8000"
    """

    def __init__(self):
        self.peers: set[str] = set()

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    def register_nodes(self, addresses: list[str]) -> list[str]:
        """
        Add one or more peer node URLs to the known peer set.

        Normalizes each URL to scheme://netloc — strips path, query, fragment.
        Returns the list of newly registered peers (skips duplicates).
        """
        registered = []
        for address in addresses:
            parsed = urlparse(address)
            # If no scheme, treat as host:port
            if not parsed.scheme:
                normalized = f"http://{address}"
            else:
                normalized = f"{parsed.scheme}://{parsed.netloc}"

            if normalized not in self.peers:
                self.peers.add(normalized)
                registered.append(normalized)

        return registered

    # ------------------------------------------------------------------
    # Nakamoto consensus
    # ------------------------------------------------------------------

    async def resolve_conflicts(self, local_blockchain) -> tuple[bool, str]:
        """
        Fetch chains from all peers and replace ours if a longer valid
        chain is found. Returns (replaced: bool, status_message: str).

        This is Nakamoto's longest-chain rule:
          - Contact every peer
          - Download their /chain endpoint
          - Validate the chain fully (PoW + signatures + Merkle)
          - If any peer has a longer valid chain, adopt it

        Why async?
          We need to fan out HTTP requests to N peers concurrently.
          With httpx.AsyncClient we avoid blocking the event loop.
          In a production system this would be a background task
          running on a configurable interval.
        """
        best_chain = None
        best_length = len(local_blockchain.chain)
        replaced = False

        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in self.peers:
                try:
                    response = await client.get(f"{peer}/chain")
                    if response.status_code != 200:
                        continue

                    data = response.json()
                    peer_length = data.get("length", 0)
                    peer_chain_data = data.get("chain", [])

                    # Only consider chains strictly longer than ours
                    if peer_length > best_length:
                        # Validate before adopting — never trust, always verify
                        valid, reason = local_blockchain.is_valid_chain(
                            _deserialize_chain(peer_chain_data)
                        )
                        if valid:
                            best_length = peer_length
                            best_chain = peer_chain_data

                except (httpx.RequestError, Exception):
                    # Unreachable peer — skip silently
                    continue

        if best_chain:
            replaced = local_blockchain.replace_chain(best_chain)
            if replaced:
                return True, f"Chain replaced. New height: {len(local_blockchain.chain)}"

        return False, "Local chain is authoritative. No longer valid chain found."


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deserialize_chain(chain_data: list[dict]):
    """
    Convert raw dicts from a peer /chain response into Block objects.
    Imported lazily to avoid circular imports (blockchain → node_network).
    """
    from blockchain import Block
    return [Block.from_dict(b) for b in chain_data]