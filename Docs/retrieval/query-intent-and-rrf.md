# Query Intent Classification & Adaptive RRF

## 1. Query Intent Classification

The retrieval engine uses a deterministic, rule-based classifier (`backend/ai/retrieval/fusion.py`) to categorize queries into 7 canonical classes without invoking expensive LLMs:

1. `exact_symbol`: Direct identifier lookup (`Where is getUserById defined?`, `Find UserAuthenticationService`)
2. `path_lookup`: File path navigation (`Open src/auth/login.py`)
3. `conceptual`: High-level explanation or architectural questions (`How does user authentication work?`)
4. `debugging`: Error diagnosis and bug fixing (`Why does token refresh fail?`)
5. `impact_analysis`: Callers, callees, and dependencies (`What functions call validate_user?`)
6. `test_generation`: Test scaffolding and synthesis (`Generate tests for payment service`)
7. `configuration_lookup`: Settings and environment variables (`Where is the database URL configured?`)

Ambiguous or open-ended queries safely default to `conceptual`.

## 2. Adaptive Source Weights

Different query intents benefit from different retrieval sources. The `RRFFusion` class applies intent-specific weight multipliers:

| Intent | Vector Weight | Lexical Weight | Graph Weight |
|---|---:|---:|---:|
| `exact_symbol` | 0.7 | 1.6 | 0.2 |
| `path_lookup` | 0.6 | 1.0 | 0.3 |
| `conceptual` | 1.4 | 0.7 | 0.5 |
| `debugging` | 1.2 | 1.0 | 1.0 |
| `impact_analysis` | 0.8 | 1.0 | 1.5 |
| `test_generation` | 1.0 | 1.2 | 1.2 |
| `configuration_lookup` | 0.8 | 1.4 | 0.4 |

## 3. Reciprocal Rank Fusion Formula

For each candidate chunk:
$$\text{RRF Score}(c) = \sum_{s \in \text{sources}} \frac{w_s}{k + \text{rank}_s(c)}$$

Where:
- $k = 60$ (smoothing constant)
- $w_s$ is the intent-specific source weight
- $\text{rank}_s(c)$ is the 1-based rank of chunk $c$ in source $s$
- Chunks appearing across multiple sources accumulate scores, boosting consistently retrieved code.
