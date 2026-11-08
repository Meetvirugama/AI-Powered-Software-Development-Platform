# Future Improvements — AI-Powered Code Review Intelligence (F14)

## 1. Roadmap & Future Enhancements

While the F14 code review architecture provides production-ready PR review comments, precision gating, multi-language static scanning, and lifecycle tracking, the following enhancements represent natural evolutions for future milestones:

### 1.1 Direct GitHub "Suggested Changes" Commit Suggestions
- **Current Capability**: Review comments present formatted remediation markdown blocks with copy-to-clipboard functionality.
- **Future Enhancement**: Emit GitHub markdown code suggestion blocks (` ```suggestion ... ``` `), enabling developers to apply fixes with a single click directly from the GitHub PR interface.

### 1.2 Fine-Tuned Review Models
- **Current Capability**: Leverages Gemini 1.5 Pro / Flash models with tailored prompt templates and few-shot examples.
- **Future Enhancement**: Train domain-adapted LoRA or fine-tuned model checkpoints on repo-specific historical PR discussions and code standards to minimize stylistic disagreements.

### 1.3 Static Analysis Multi-Language Parity
- **Current Languages**: Python (Ruff, Bandit), JavaScript/TypeScript (ESLint, Biome).
- **Future Additions**:
  - Go: `golangci-lint`
  - Rust: `cargo clippy`
  - Java/Kotlin: `spotbugs` / `detekt`

### 1.4 Active Learning from Developer Feedback
- **Current Capability**: Developers mark findings as `useful`, `not_useful`, or `false_positive`, and aggregate metrics are tracked per repository.
- **Future Enhancement**: Feed aggregated negative feedback back into few-shot negative prompts or classifier re-ranking gates to suppress specific false-positive patterns automatically.
