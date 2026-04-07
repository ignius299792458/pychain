"""
node_network.py — Peer node registry and Nakamoto consensus.
Peers are now persisted to SQLite via db.py.
"""

from urllib.parse import urlparse

import db
import httpx


class NodeNetwork:
    def __init__(self):
        self.peers: set[str] = db.load_peers()  # restore from DB on startup

    def register_nodes(self, addresses: list[str]) -> list[str]:
        registered = []
        for address in addresses:
            parsed = urlparse(address)
            normalized = (
                f"http://{address}"
                if not parsed.scheme
                else f"{parsed.scheme}://{parsed.netloc}"
            )
            if normalized not in self.peers:
                self.peers.add(normalized)
                db.save_peer(normalized)  # persist immediately
                registered.append(normalized)
        return registered

    async def resolve_conflicts(self, local_blockchain) -> tuple[bool, str]:
        best_chain = None
        best_length = len(local_blockchain.chain)

        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in self.peers:
                try:
                    response = await client.get(f"{peer}/chain")
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    peer_length = data.get("length", 0)
                    peer_chain_data = data.get("chain", [])
                    if peer_length > best_length:
                        valid, _ = local_blockchain.is_valid_chain(
                            _deserialize_chain(peer_chain_data)
                        )
                        if valid:
                            best_length = peer_length
                            best_chain = peer_chain_data
                except (httpx.RequestError, Exception):
                    continue

        if best_chain:
            replaced = local_blockchain.replace_chain(best_chain)
            if replaced:
                return (
                    True,
                    f"Chain replaced. New height: {len(local_blockchain.chain)}",
                )

        return False, "Local chain is authoritative."


def _deserialize_chain(chain_data: list[dict]):
    from blockchain import Block

    return [Block.from_dict(b) for b in chain_data]
