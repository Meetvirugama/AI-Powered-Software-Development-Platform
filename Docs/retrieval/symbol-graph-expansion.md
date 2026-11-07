# Bounded Symbol-Graph Expansion

## 1. Overview

While vector and lexical retrieval excel at isolated chunk matching, complex code questions require knowledge of relationships between functions, classes, and modules (callers, callees, inheritance, imports).

`SymbolGraphExpander` (`backend/ai/retrieval/graph_expansion.py`) connects initial retrieval candidates to their 1-hop dependencies using PostgreSQL `symbol_edges`.

## 2. Expansion Bounds

To preserve database performance and avoid context flooding, strict bounds are enforced:
- **Maximum Seeds**: 5 (selected from highest-ranking candidates having a valid `symbol_id`)
- **Maximum Hops**: 1 (no recursive or deep multi-hop traversal)
- **Maximum Related per Seed**: 10
- **Maximum Expanded Chunks**: 30

## 3. Intent-Directed Traversal

The edge traversal direction depends on the query intent:

- `impact_analysis`: Traverses incoming edges (`calls`, `imports`, `extends`, `implements`) to find who depends on or calls the seed symbol.
- `debugging`: Traverses both incoming and outgoing call edges (`calls`).
- `test_generation`: Traverses callers, callees, and imported symbols (`calls`, `imports`).
- `exact_symbol`: Traverses limited direct callers and callees (`calls`).
- `conceptual`: Explores general relationships.
- `path_lookup`: Graph expansion is bypassed entirely.

## 4. Multi-Tenant Repository Isolation

Every graph query strictly enforces `repository_id = :repo_id` across `symbol_edges`, `code_chunks`, and `repository_files`. Traversal across repository boundaries is physically impossible.
