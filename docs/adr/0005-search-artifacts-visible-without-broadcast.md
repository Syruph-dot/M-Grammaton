# Search artifacts are globally visible without default broadcast

Search reports and imported web evidence are ordinary graph nodes and are visible to all Actors through graph traversal and dashboard observation. They do not automatically create User or Operator messages; notifying another Actor requires an explicit `send_message` action, which keeps external exploration observable without turning every search into an interruption.
