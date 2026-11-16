# Glossary

| Term | Meaning in this project |
|---|---|
| Analysis run | One explain / bug detection / test generation / review execution, stored in `analysis_runs` |
| Approval gate | Server check that a task's approved plan version, plan hash and base revision match before execution |
| AST | Abstract syntax tree produced by tree-sitter for supported languages |
| Blast radius | Symbols/files/tests likely affected by a change, computed from the symbol graph |
| cAST chunking | Chunking along AST boundaries: split large symbols at child boundaries, merge small siblings |
| Draft PR | GitHub pull request created with `draft=true`; the platform's final output for tasks |
| Edit synthesis | LLM generation of search/replace blocks validated before application |
| Elicitation (MCP) | A request for user input (form or URL) that pauses tool execution |
| Embedding profile | Provider, model, dimensions, task type and version that define compatible vectors |
| Graph expansion | Adding 1-hop caller/callee chunks of top results to retrieval candidates |
| Grounding | Verifying that every citation refers to retrieved chunks / real file lines |
| HNSW | Hierarchical Navigable Small World approximate nearest-neighbour index (pgvector) |
| Index generation | Counter on `repositories` bumped after a sync; used to invalidate caches |
| Lease | Time-bounded claim on a job/event so only one worker processes it |
| LoopDetector | Detects repeated actions and cycles in the agent execution loop |
| MCP | Model Context Protocol; tool/resource protocol used by the tool adapter |
| Plan hash | Hash of a plan version's content used to bind approvals |
| Provenance / taint | Tracking of untrusted data origin and propagation to block unsafe use |
| RRF | Reciprocal Rank Fusion, `score = Σ 1/(k + rank)`, k=60 |
| Reranker | Cross-encoder (`ms-marco-MiniLM-L-6-v2`) scoring query–chunk pairs |
| Runner | Standalone service executing commands in hardened containers |
| Sandbox backend | `local` (dev), `container` or `runner` implementation of isolated execution |
| Tool router | Policy-enforcing dispatcher for workspace tools |
| Workspace | Per-task git worktree where edits and tests happen |
