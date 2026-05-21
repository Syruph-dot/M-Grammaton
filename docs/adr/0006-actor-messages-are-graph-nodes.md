# ADR 0006: Actor Messages Are Graph Nodes With Queue Views

Actor-level messages are not only transient queue payloads. Each visible Actor message should persist as `kind: "artifact"` with `metadata.artifact_type: "actor_message"`, and its body should remain a detailed short essay that may contain question, answer, and request content. Message queues remain valid implementation structures, but they hold delivery, selection, done, and soft-delete state that references message nodes.

This keeps User and Operator communication inside the same graph/artifact world as notes, replies, search reports, and external evidence. It also prevents queue cleanup from erasing the durable communication artifact. Detailed message protocol, threading, and body-part conventions remain follow-up design work.
