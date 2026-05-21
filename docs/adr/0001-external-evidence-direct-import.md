# External evidence imports directly as unverified graph artifacts

Phase 2 Operator web search imports external evidence directly into the graph as Operator Artifact nodes, rather than waiting for human pre-approval. This preserves autonomous graph growth while keeping Human Source immutable; imported evidence must carry provenance, `trust_level: "unverified"`, visible monitor events, and lower initial edge weight so later review and graph dynamics can treat it differently from curated source material.
