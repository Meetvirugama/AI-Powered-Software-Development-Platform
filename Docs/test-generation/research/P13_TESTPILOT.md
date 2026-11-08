# Research Summary: TestPilot (JavaScript/TypeScript Unit Test Generation)

**Citation**: Schäfer, M., Nadi, S., Eghbali, A., & Tip, F. (2023). *Adaptive Test Generation Using a Large Language Model*. ACM Transactions on Software Engineering and Methodology (TOSEM).

---

## 1. Problem Formulation
JavaScript and TypeScript applications present unique challenges for automated testing:
- Diverse module loaders (ESM vs CommonJS).
- Asynchronous APIs (`Promise`, `async/await`).
- Divergent mocking paradigms across Jest (`jest.fn()`, `jest.mock()`) and Vitest (`vi.fn()`, `vi.mock()`).
- Complex bundlers (Vite, Webpack, Rollup) and config files (`vitest.config.ts`, `vite.config.ts`).

## 2. TestPilot's Approach
- Inspects `package.json` scripts and dependency manifests to determine runner commands.
- Derives framework-specific test templates and mock syntax.
- Bounded iterative feedback: feeds runtime errors back to the model to repair missing imports or invalid mocking configurations.

## 3. Applicability to Our Platform
We incorporated TestPilot's framework-first principles in our Vitest upgrade:
- Manifest detection for `vitest.config.ts`, `vitest.config.js`, `vite.config.ts`, and `package.json` scripts (`npm test -- --run`).
- LLM prompt guidelines (`backend/ai/prompts/test_generation_system.txt`) enforce idiomatic Vitest imports: `import { describe, it, expect, vi } from 'vitest'`.
- Structural parser validation accepts `vi.fn()` and `vi.mock()` without triggering Python or Jest syntax errors.
