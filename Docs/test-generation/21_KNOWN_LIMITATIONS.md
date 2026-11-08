# Known Limitations & Future Roadmap

---

## 1. Technical Limitations

1. **Non-Standard Compilers**:
   - The test generation system supports Python (`pytest`, `unittest`) and JavaScript/TypeScript (`jest`, `vitest`).
   - Compiled languages requiring external build tools (`cargo` for Rust, `go test` for Go, `mvn`/`gradle` for Java) are detected by `FrameworkDetector` and rejected with `400 UNSUPPORTED_TARGET`.
2. **Heavy Database Integration Tests**:
   - The isolated sandbox does not spawn ephemeral Docker PostgreSQL or Redis containers by default. Integration tests requiring active external database daemons must provide mock fixtures or in-memory sqlite/fakeredis adapters.
3. **Flakiness Boundary**:
   - Three consecutive successful test runs (`MAX_STABILITY_RUNS = 3`) offer strong empirical evidence of test stability, but do not mathematically guarantee the absence of race conditions in high-concurrency systems.
4. **Synchronous Mutation Testing Overhead**:
   - Mutation testing is intentionally restricted to offline quality benchmarking. Running full mutation suites during synchronous interactive API calls would exceed latency budgets.
5. **Coverage Attribution on External Libraries**:
   - Coverage attribution measures lines in the targeted repository source file. Tests that execute standard library internals or third-party packages without exercising user code will show 0% target coverage and remain `UNVERIFIED`.

---

## 2. Future Roadmap

1. **gVisor / Firecracker MicroVM Sandboxing**:
   - Upgrade from directory/worktree subprocess isolation to hardware-isolated microVMs for multitenant SaaS environments.
2. **Automated Fixture Synthesis**:
   - Automatically analyze SQLAlchemy models to synthesize factory fixtures (`pytest-factoryboy`).
3. **Property-Based Testing Integration**:
   - Integrate Hypothesis (Python) and fast-check (TypeScript) for fuzzing invariants.
