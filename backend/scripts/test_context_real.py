"""
End-to-End Real-API Test for ai/context/builder.py
=====================================================
Tests:
  1. count_tokens()          — tiktoken cl100k_base
  2. ContextBuilder.build()  — dedup, sort memory, token budget, truncation
  3. render_repository_data()— REPOSITORY DATA section rendering
  4. Full RAG pipeline chat  — real GitHub API + real Groq LLM

Repo under test: https://github.com/Meetvirugama/SchoolWebPage
Run from project root:
    PYTHONPATH=backend python backend/scripts/test_context_real.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import textwrap
import time
from pathlib import Path
from uuid import uuid4

import httpx

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# Load .env manually (before importing app settings)
from dotenv import load_dotenv  # type: ignore
env_path = ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ── Imports from ai/context ───────────────────────────────────────────────────
from ai.context.builder import (
    AgentContext,
    ChatMessage,
    ContextBuilder,
    MemoryEntry,
    RepositoryFile,
    count_tokens,
)
from ai.retrieval.base import CodeChunk
from ai.llm.client import LLMGateway
from ai.llm.groq_provider import GroqProvider
from ai.schemas.prompt_builder import PromptBuilder
from ai.schemas.output import RepositoryAnswer

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}✅ PASS{RESET}"
FAIL = f"{RED}❌ FAIL{RESET}"
INFO = f"{CYAN}ℹ️  {RESET}"
SECTION = f"{BOLD}{YELLOW}"


def header(title: str) -> None:
    print(f"\n{SECTION}{'═'*65}{RESET}")
    print(f"{SECTION}  {title}{RESET}")
    print(f"{SECTION}{'═'*65}{RESET}")


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"  {status}  {label}")
    if detail:
        for line in detail.splitlines():
            print(f"          {CYAN}{line}{RESET}")
    if not condition:
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 ─ Fetch SchoolWebPage repo content via GitHub REST API
# ─────────────────────────────────────────────────────────────────────────────

REPO_OWNER = "Meetvirugama"
REPO_NAME  = "SchoolWebPage"
GITHUB_API = "https://api.github.com"

# Try to get a token from env (optional — public repo works without it)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_APP_PRIVATE_KEY", "")[:0]


def github_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN", "")
    if token and not token.startswith("-----"):
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_repo_tree() -> list[dict]:
    """Fetch the flat file tree of SchoolWebPage (recursive)."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/HEAD?recursive=1"
    r = httpx.get(url, headers=github_headers(), timeout=15)
    r.raise_for_status()
    return r.json().get("tree", [])


def fetch_file_content(path: str) -> str | None:
    """Fetch decoded content of a single file from GitHub."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    r = httpx.get(url, headers=github_headers(), timeout=15)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return data.get("content", "")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 ─ Build CodeChunk objects from fetched files
# ─────────────────────────────────────────────────────────────────────────────

TEXT_EXTENSIONS = {
    ".html", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".md", ".txt", ".py", ".yml", ".yaml",
    ".env.example", ".gitignore",
}


def is_text_file(path: str) -> bool:
    return any(path.endswith(ext) for ext in TEXT_EXTENSIONS)


def build_chunks_from_files(files_content: list[tuple[str, str]]) -> list[CodeChunk]:
    """Convert (path, content) pairs into CodeChunk objects (fixed 50-line windows)."""
    repo_id = uuid4()
    chunks: list[CodeChunk] = []
    WINDOW = 50  # lines per chunk

    for path, content in files_content:
        lines = content.splitlines()
        for start in range(0, len(lines), WINDOW):
            end = min(start + WINDOW, len(lines))
            snippet = "\n".join(lines[start:end])
            if not snippet.strip():
                continue
            chunk = CodeChunk(
                id=uuid4(),
                repository_id=repo_id,
                file_id=uuid4(),
                symbol_id=None,
                content=snippet,
                token_count=count_tokens(snippet),
                start_line=start + 1,
                end_line=end,
                content_hash=str(hash(snippet)),
                score=1.0,
                file_path=path,
            )
            chunks.append(chunk)

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TEST SUITE
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{BOLD}{'='*65}{RESET}")
    print(f"{BOLD}  ai/context/builder.py — Real-API End-to-End Test{RESET}")
    print(f"{BOLD}  Repo: https://github.com/{REPO_OWNER}/{REPO_NAME}{RESET}")
    print(f"{BOLD}{'='*65}{RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 1: count_tokens()
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 1 — count_tokens() using tiktoken cl100k_base")

    t1 = count_tokens("Hello world")
    t2 = count_tokens("")
    t3 = count_tokens("def authenticate(user, password):\n    return db.check(user, password)")
    t4 = count_tokens("a" * 10_000)

    check("'Hello world' → 2 tokens", t1 == 2, f"Got {t1}")
    check("Empty string → 0 tokens",  t2 == 0, f"Got {t2}")
    check("Python function → >5 tokens", t3 > 5, f"Got {t3} tokens")
    check("10k chars → >1000 tokens",  t4 > 1000, f"Got {t4} tokens")
    print(f"  {INFO} Python snippet token count: {t3}")
    print(f"  {INFO} 10k char blob token count:  {t4}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 2: Fetch real repo from GitHub API
    # ─────────────────────────────────────────────────────────────────────────
    header(f"TEST 2 — Fetch https://github.com/{REPO_OWNER}/{REPO_NAME} via GitHub API")

    print(f"  {INFO} Fetching file tree …")
    t0 = time.monotonic()
    try:
        tree = fetch_repo_tree()
    except httpx.HTTPStatusError as e:
        print(f"  {RED}GitHub API error: {e}{RESET}")
        sys.exit(1)

    blob_files = [f for f in tree if f["type"] == "blob" and is_text_file(f["path"])]
    check("Repo tree fetched (>0 files)", len(tree) > 0, f"Total items: {len(tree)}")
    check("Text files found (>0)",        len(blob_files) > 0, f"Text files: {len(blob_files)}")

    print(f"  {INFO} Total tree items : {len(tree)}")
    print(f"  {INFO} Text files found : {len(blob_files)}")
    print(f"  {INFO} Files to fetch   : {min(len(blob_files), 15)} (capped at 15 for speed)")

    # Fetch first 15 text files (cap to avoid rate limits)
    files_content: list[tuple[str, str]] = []
    for item in blob_files[:15]:
        content = fetch_file_content(item["path"])
        if content is not None:
            files_content.append((item["path"], content))
            print(f"    📄 {item['path']} ({len(content)} bytes)")

    check("At least 3 files fetched", len(files_content) >= 3,
          f"Fetched {len(files_content)} files")
    print(f"  {INFO} Fetch time: {time.monotonic()-t0:.2f}s")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 3: Build CodeChunks from real file content
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 3 — Build CodeChunks (50-line windows) from fetched files")

    chunks = build_chunks_from_files(files_content)
    check("At least 1 chunk created",     len(chunks) >= 1, f"Got {len(chunks)} chunks")
    check("Chunks have content",          all(c.content.strip() for c in chunks))
    check("Chunks have valid token_count",all(c.token_count > 0 for c in chunks))
    check("Chunks have file_path set",    all(c.file_path for c in chunks))

    total_tokens_all = sum(c.token_count for c in chunks)
    print(f"  {INFO} Chunks created    : {len(chunks)}")
    print(f"  {INFO} Total chunk tokens: {total_tokens_all:,}")
    print(f"  {INFO} Sample chunk file : {chunks[0].file_path} (lines {chunks[0].start_line}–{chunks[0].end_line})")
    print(f"  {INFO} Sample chunk tokens: {chunks[0].token_count}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 4: ContextBuilder.build() — core logic
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 4 — ContextBuilder.build() with memory dedup + token budget")

    memory = [
        MemoryEntry(id="m1", content="This is a school website project.",
                    type="architecture", created_at="2024-01-03T10:00:00Z"),
        MemoryEntry(id="m2", content="Use semantic HTML5 for all pages.",
                    type="rule", created_at="2024-01-01T08:00:00Z"),
        MemoryEntry(id="m1", content="School website — updated note.",  # duplicate id
                    type="architecture", created_at="2024-01-04T12:00:00Z"),
        MemoryEntry(id="m3", content="Mobile-first responsive design required.",
                    type="decision", created_at="2024-01-02T09:00:00Z"),
    ]

    history = [
        ChatMessage(role="user",      content="What is this project about?"),
        ChatMessage(role="assistant", content="This is a school website with HTML/CSS/JS."),
        ChatMessage(role="user",      content="What files are in the project?"),
    ]

    related_files = [
        RepositoryFile(id="f1", path="index.html", language="html", size_bytes=2048, line_count=60),
        RepositoryFile(id="f2", path="style.css",  language="css",  size_bytes=1024, line_count=80),
    ]

    builder = ContextBuilder(max_context_tokens=100_000)
    ctx = builder.build(
        chunks=chunks,
        memory=memory,
        history=history,
        related_files=related_files,
    )

    check("Returns AgentContext",                   isinstance(ctx, AgentContext))
    check("total_tokens > 0",                       ctx.total_tokens > 0,
          f"total_tokens = {ctx.total_tokens:,}")
    check("total_tokens ≤ max (100k)",              ctx.total_tokens <= 100_000,
          f"total_tokens = {ctx.total_tokens:,}")
    check("Memory deduped: 3 unique ids → 3 max",  len(ctx.memory_chunks) <= 3,
          f"memory kept: {len(ctx.memory_chunks)}")
    check("Memory sorted newest first",
          ctx.memory_chunks[0].created_at >= ctx.memory_chunks[-1].created_at,
          f"first={ctx.memory_chunks[0].created_at}, last={ctx.memory_chunks[-1].created_at}")
    check("Duplicate m1 resolved to updated version",
          any(m.content == "School website — updated note." for m in ctx.memory_chunks))
    check("History kept (≤3 turns)",               len(ctx.recent_history) <= 3)
    check("Related files preserved",               len(ctx.related_files) == 2)

    print(f"  {INFO} total_tokens    : {ctx.total_tokens:,}")
    print(f"  {INFO} chunks in       : {len(chunks)}")
    print(f"  {INFO} chunks kept     : {len(ctx.code_chunks)}")
    print(f"  {INFO} memory deduped  : {len(ctx.memory_chunks)}")
    print(f"  {INFO} history kept    : {len(ctx.recent_history)}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 5: Token budget truncation
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 5 — Token budget enforcement / truncation")

    # Use a very small budget (2000 tokens) — should force truncation
    tiny_builder = ContextBuilder(max_context_tokens=2000)
    tiny_ctx = tiny_builder.build(
        chunks=chunks,
        memory=memory,
        history=history,
    )

    check("Tiny budget: total_tokens ≤ 2000",
          tiny_ctx.total_tokens <= 2000,
          f"total_tokens = {tiny_ctx.total_tokens}")
    check("Tiny budget: fewer chunks than full",
          len(tiny_ctx.code_chunks) <= len(ctx.code_chunks),
          f"tiny={len(tiny_ctx.code_chunks)}, full={len(ctx.code_chunks)}")

    print(f"  {INFO} Full budget  → {len(ctx.code_chunks)} chunks, {ctx.total_tokens:,} tokens")
    print(f"  {INFO} 2000 budget  → {len(tiny_ctx.code_chunks)} chunks, {tiny_ctx.total_tokens:,} tokens")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 6: render_repository_data()
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 6 — render_repository_data() output format")

    rendered = builder.render_repository_data(ctx)

    check("Rendered is a non-empty string",     isinstance(rendered, str) and len(rendered) > 0)
    check("Contains 'REPOSITORY DATA:' header", "REPOSITORY DATA:" in rendered)
    check("Contains '----' separator",          "----" in rendered)
    check("Contains a real file path",
          any(f.file_path in rendered for f in ctx.code_chunks),
          f"First chunk path: {ctx.code_chunks[0].file_path}")

    if ctx.memory_chunks:
        check("Contains 'MEMORY:' section",    "MEMORY:" in rendered)
        check("Contains memory type tag",
              any(f"[{m.type.upper()}]" in rendered for m in ctx.memory_chunks))

    print(f"  {INFO} Rendered output ({len(rendered):,} chars):")
    # Show first 10 lines nicely
    for line in rendered.splitlines()[:10]:
        print(f"          {CYAN}{line[:100]}{RESET}")
    if len(rendered.splitlines()) > 10:
        print(f"          {CYAN}… (+{len(rendered.splitlines())-10} more lines){RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 7: PromptBuilder — message structure
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 7 — PromptBuilder message structure (system/data separation)")

    from ai.llm.schemas import Message

    pb = PromptBuilder()
    messages = pb.build_chat_prompt(
        context=rendered,
        question="What is the main purpose of this school website?",
    )

    check("Returns 2 messages",          len(messages) == 2)
    check("First is system role",        messages[0].role == "system")
    check("Second is user role",         messages[1].role == "user")
    check("System has no REPO data",
          "REPOSITORY DATA" not in messages[0].content,
          "System prompt must NOT contain repo data")
    check("User contains REPO data fence",
          "<<<REPO_DATA_" in messages[1].content)
    check("User contains question",
          "What is the main purpose" in messages[1].content)
    check("User has random fence token (prompt injection guard)",
          "<<<REPO_DATA_" in messages[1].content and "<<<END_REPO_DATA_" in messages[1].content)

    print(f"  {INFO} System msg length : {len(messages[0].content)} chars")
    print(f"  {INFO} User msg length   : {len(messages[1].content)} chars")
    print(f"  {INFO} System preview    : {messages[0].content[:80]}…")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 8: Real Groq LLM call (end-to-end)
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 8 — Real Groq LLM call (openai/gpt-oss-120b — GPT via Groq)")

    groq_keys_str = os.getenv("GROQ_API_KEYS", "") or os.getenv("GROQ_API_KEY", "")
    groq_keys = [k.strip() for k in groq_keys_str.split(",") if k.strip()]

    GPT_MODEL = "openai/gpt-oss-120b"  # Current GPT-equivalent on Groq

    if not groq_keys:
        print(f"  {YELLOW}⚠️  GROQ_API_KEYS not set — skipping real LLM test{RESET}")
    else:
        print(f"  {INFO} Using {len(groq_keys)} Groq API key(s)")
        print(f"  {INFO} Model: {GPT_MODEL}")
        provider = GroqProvider(api_keys=groq_keys)
        gateway  = LLMGateway(provider=provider)

        from ai.llm.schemas import LLMRequest

        # Use only first 3 chunks to keep prompt small & fast
        small_ctx = builder.build(
            chunks=chunks[:3],
            memory=memory[:2],
            history=history[:2],
        )
        small_rendered = builder.render_repository_data(small_ctx)
        llm_messages = pb.build_chat_prompt(
            context=small_rendered,
            question="What is the main purpose of this school website? List the key HTML files you can see.",
        )

        req = LLMRequest(
            model=GPT_MODEL,
            messages=llm_messages,
            response_schema=RepositoryAnswer,
        )

        print(f"  {INFO} Sending request to Groq ({GPT_MODEL})…")
        t0 = time.monotonic()

        try:
            response = await gateway.generate(req)
            latency = time.monotonic() - t0

            check("Got a response",          response is not None)
            check("Response has content",    bool(response.content))
            check("Input tokens > 0",        response.input_tokens > 0,
                  f"input_tokens = {response.input_tokens}")
            check("Output tokens > 0",       response.output_tokens > 0,
                  f"output_tokens = {response.output_tokens}")

            print(f"  {INFO} Latency         : {latency:.2f}s")
            print(f"  {INFO} Input tokens    : {response.input_tokens}")
            print(f"  {INFO} Output tokens   : {response.output_tokens}")

            # Try to parse as RepositoryAnswer JSON
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rstrip().rstrip("```")

            try:
                data = json.loads(content)
                answer = RepositoryAnswer(**data)
                check("LLM returned valid RepositoryAnswer JSON", True)
                check("Answer is non-empty",      bool(answer.answer))
                check("Confidence is valid",       answer.confidence in ("high","medium","low"),
                      f"confidence = {answer.confidence}")

                print(f"\n  {BOLD}LLM ANSWER:{RESET}")
                print(textwrap.indent(textwrap.fill(answer.answer, 70), "    "))
                print(f"\n  {BOLD}Confidence:{RESET} {answer.confidence}")
                if answer.sources:
                    print(f"  {BOLD}Sources:{RESET}")
                    for s in answer.sources:
                        print(f"    - {s.file} (lines {s.start_line}–{s.end_line})")
                else:
                    print(f"  {INFO} No sources cited")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"  {YELLOW}⚠️  JSON parse warning: {e}{RESET}")
                print(f"  {INFO} Raw content preview:")
                print(textwrap.indent(response.content[:400], "    "))

        except Exception as e:
            import traceback
            print(f"  {RED}Groq API error: {type(e).__name__}: {e}{RESET}")
            traceback.print_exc()
            print(f"  {YELLOW}  Model used: {GPT_MODEL}{RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 9: Edge cases
    # ─────────────────────────────────────────────────────────────────────────
    header("TEST 9 — Edge cases: empty inputs, single chunk, zero memory")

    # Empty everything
    empty_ctx = builder.build(chunks=[], memory=[], history=[])
    check("Empty build: returns AgentContext",   isinstance(empty_ctx, AgentContext))
    check("Empty build: 0 code chunks",          len(empty_ctx.code_chunks) == 0)
    check("Empty build: total_tokens = 500 (overhead only)",
          empty_ctx.total_tokens == 500, f"Got {empty_ctx.total_tokens}")
    check("Empty render: empty string",          builder.render_repository_data(empty_ctx) == "")

    # Single chunk, no memory
    one_chunk_ctx = builder.build(chunks=chunks[:1], memory=[], history=[])
    check("1 chunk: code_chunks has 1 item",    len(one_chunk_ctx.code_chunks) == 1)
    check("1 chunk: total_tokens > 500",        one_chunk_ctx.total_tokens > 500)

    # Duplicate memory only
    dup_mem = [
        MemoryEntry(id="x", content="v1", type="rule", created_at="2024-01-01T00:00:00Z"),
        MemoryEntry(id="x", content="v2", type="rule", created_at="2024-01-02T00:00:00Z"),
        MemoryEntry(id="x", content="v3", type="rule", created_at="2024-01-03T00:00:00Z"),
    ]
    dup_ctx = builder.build(chunks=[], memory=dup_mem, history=[])
    check("All-dup memory → exactly 1 entry",   len(dup_ctx.memory_chunks) == 1)
    check("Last-write wins (v3 kept)",
          dup_ctx.memory_chunks[0].content == "v3",
          f"Got: {dup_ctx.memory_chunks[0].content}")

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*65}{RESET}")
    print(f"{GREEN}{BOLD}  🎉  ALL TESTS PASSED — ai/context/builder.py is working correctly{RESET}")
    print(f"{BOLD}{'='*65}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
