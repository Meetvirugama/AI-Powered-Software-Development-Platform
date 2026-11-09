# 06 — Self-Refinement, Loop Detection, and Execution Budgets

## 1. Executive Summary

Autonomous LLM code generation occasionally produces subtle mistakes on the first attempt—such as slight whitespace discrepancies in `search_block`, minor syntax errors, or missed brackets. Rejecting the entire workflow on the very first transient error reduces system reliability.

To balance reliability and safety, `EditSynthesizer` implements a **bounded self-refinement loop** based on the Reflexion and Self-Refine research paradigms, governed by strict execution budget ceilings and loop detection.

---

## 2. Bounded Self-Refinement Architecture

```mermaid
sequenceDiagram
    autonumber
    participant Loop as AgentExecutionLoop
    participant Synth as EditSynthesizer
    participant LLM as LLM Provider
    participant Val as Validation Engine

    Loop->>Synth: synthesize_sync(step, plan, repo_context)
    Note over Synth: Attempt 1 (Initial Generation)
    Synth->>LLM: generate_patch(prompt)
    LLM-->>Synth: EditBlock JSON
    Synth->>Val: validate_patch(EditBlock)
    alt Validation Succeeded
        Val-->>Synth: Success (Valid AST & Single Match)
        Synth-->>Loop: Modified Content + Patch Hash
    else Validation Failed (e.g. Zero Matches or AST Syntax Error)
        Val-->>Synth: Error: "Zero matches found for search_block"
        Note over Synth: Attempt 2 (Refinement 1)
        Synth->>LLM: refine_patch(original_prompt, error_feedback)
        LLM-->>Synth: Corrected EditBlock JSON
        Synth->>Val: validate_patch(Corrected EditBlock)
        alt Passed on Retry
            Val-->>Synth: Success
            Synth-->>Loop: Modified Content + Patch Hash
        else Failed Again
            Note over Synth: Attempt 3 (Final Refinement)
            Synth->>LLM: refine_patch(original_prompt, second_error)
            LLM-->>Synth: Third EditBlock JSON
            Synth->>Val: validate_patch(Third EditBlock)
            alt Passed
                Val-->>Synth: Success
                Synth-->>Loop: Modified Content
            else Exhausted
                Val-->>Synth: Failure
                Note over Synth: Hard Budget Cap Reached
                Synth-->>Loop: EditSynthesisResult(success=False, attempts=3)
            end
        end
    end
```

### 2.1 The Hard 3-Attempt Budget Ceiling
- Total attempts allowed per plan step: **Maximum 3** (1 initial generation + up to 2 self-correction retries).
- Once `attempts == 3` and validation fails, the synthesizer immediately ceases generation and returns `success=False`.
- The `AgentExecutionLoop` marks the step as `FAILED` and halts. It never enters an infinite correction loop.

---

## 3. Verbal Reinforcement and Error Feedback

When a validation stage fails, the exact failure is converted into an actionable feedback prompt:

1. **Zero Matches Feedback**:
   ```
   Your search_block was not found in file '{file_path}'.
   Ensure that search_block matches the target file verbatim, including exact line indentation, spacing, and quotes.
   Do not guess code. Quote directly from the provided source.
   ```
2. **Multiple Matches Feedback**:
   ```
   Your search_block matched {count} separate locations in '{file_path}'.
   Expand the search_block with unique leading or trailing context lines so that occurrences == 1.
   ```
3. **Python Syntax Error Feedback**:
   ```
   Applying your patch produced a Python syntax error: {error_details} at line {lineno}.
   Ensure all brackets, colons, indentation levels, and string literals are valid Python.
   ```

---

## 4. Loop Detection and Cycle Prevention

The `AgentExecutionLoop` utilizes `LoopDetector` to prevent repeating cycles across steps:
1. **Action-State Fingerprinting**: Tracks `(action_type, target_file, patch_hash)` tuples.
2. **Repeating Cycle Detection**: If the same action on the same file with identical patch contents is encountered twice in the execution window, `LoopDetector` triggers `CYCLE_DETECTED`.
3. **Immediate Abort**: Execution halts, recording the cycle event to the timeline and failing safely.
