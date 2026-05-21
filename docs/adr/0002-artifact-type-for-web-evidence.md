# Web evidence uses artifact_type instead of a top-level node kind

External web evidence is represented as `kind: "artifact"` with `metadata.artifact_type: "web_page"`, rather than a new top-level `Node.kind`. This keeps `kind` focused on structural graph roles while allowing product-level artifact categories such as `note`, `reply`, `web_page`, `search_report`, and `patch_suggestion` to evolve without expanding the core node taxonomy.
