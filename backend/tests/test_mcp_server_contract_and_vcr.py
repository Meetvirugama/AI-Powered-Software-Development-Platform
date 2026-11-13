from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock
import uuid

import pytest

from agent.tools.adapters.mcp import MCPToolAdapter
from agent.tools.models import ToolDefinition
from ai.llm.client import LLMGateway
from ai.llm.gemini_provider import GeminiProvider
from ai.llm.schemas import LLMRequest, Message
from ai.retrieval.cache import RetrievalResultCache, TwoLevelRetrievalCache
from ai.retrieval.cache_keys import get_repository_index_version
from ai.security.taint_tracker import TaintTracker
from app.api.v1.mcp_registry import (
    RegisterMCPServerRequest,
    UpdateToolApprovalPolicyRequest,
    list_mcp_servers,
    ping_mcp_server,
    register_mcp_server,
    toggle_mcp_server,
    update_mcp_tool_policy,
)
from app.core.errors import APIError
from app.mcp.server import PlatformMCPContractDispatcher, PlatformMCPServer
from app.observability.langfuse_adapter import LangfuseAdapter
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.code_symbol_repository import CodeSymbolRepository
from app.services.sse_redis_streams import (
    RedisStreamEventBroker,
    SSEEnvelope,
    compare_stream_ids,
    normalize_stream_cursor,
    publish_chat_token,
    publish_mcp_notification,
    publish_tool_progress,
)
from tests.fixtures.vcr_llm_cassette import (
    VCRCacheMissError,
    VCRLLMCassette,
    redact_secrets_in_obj,
)


def test_teammate_commits_fixes_batch_slicing_langfuse_cache_and_taint() -> None:
    # 1. Verify ChunkRepository.create_batch & CodeSymbolRepository.create_batch batch slicing & redaction
    batches = []
    mock_sess = MagicMock()
    mock_sess.execute.side_effect = lambda stmt, params: batches.append(list(params))
    chunk_repo = ChunkRepository(mock_sess)
    rid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    synth_openai_secret = "sk-proj-" + "1234567890abcdefghij123456"
    rows = [
        {
            "id": str(uuid.uuid4()),
            "repository_id": rid,
            "file_id": fid,
            "symbol_id": "invalid-uuid",
            "content": f"row {i} secret {synth_openai_secret}",
        }
        for i in range(510)
    ]
    assert chunk_repo.create_batch(rows, batch_size=250) == 510
    assert [len(b) for b in batches] == [250, 250, 10]
    assert "[REDACTED]" in batches[0][0]["content"]
    assert batches[0][0]["symbol_id"] is None

    sym_batches = []
    mock_sym_sess = MagicMock()
    mock_sym_sess.execute.side_effect = lambda stmt, params: sym_batches.append(list(params))
    sym_repo = CodeSymbolRepository(mock_sym_sess)
    sym_rows = [
        {
            "id": str(uuid.uuid4()),
            "repository_id": rid,
            "file_id": fid,
            "parent_id": "not-a-uuid",
            "name": f"sym_{i}",
            "kind": "function",
            "start_line": 1,
            "end_line": 5,
        }
        for i in range(260)
    ]
    assert sym_repo.create_batch(sym_rows, batch_size=250) == 260
    assert [len(b) for b in sym_batches] == [250, 10]
    assert sym_batches[0][0]["parent_id"] is None

    # 2. Verify LangfuseAdapter redaction & SSRF guard
    recorded = []
    lf = LangfuseAdapter(
        enabled=True,
        capture_prompts=True,
        capture_responses=True,
        client=SimpleNamespace(generation=lambda **kw: recorded.append(kw)),
    )
    synth_gh_token = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    lf.record_generation(
        trace_id="t1",
        model="gemini-2.5-pro",
        provider="gemini",
        prompt=f"token={synth_gh_token}",
        completion=synth_openai_secret,
    )
    dumped = json.dumps(recorded[0], default=str)
    assert synth_gh_token not in dumped
    assert synth_openai_secret not in dumped

    # 3. Verify Redis bytes decoding in cache_keys, TwoLevelRetrievalCache._get_client & bounded TaintTracker
    fake_redis = SimpleNamespace(get=lambda k: b"v170000123")
    assert get_repository_index_version("repo-1", fake_redis) == "v170000123"
    two_level = TwoLevelRetrievalCache(l2_cache=RetrievalResultCache(redis_client=fake_redis, enabled=True))
    assert two_level._get_client() is fake_redis

    tracker = TaintTracker(max_entries=100)
    prov = tracker.deserialize(
        {
            "provenance_id": "prov-ext-1",
            "source_type": "github_issue",
            "trust_level": "EXTERNAL_UNTRUSTED",
            "tainted": False,
        }
    )
    assert prov.tainted is True


@pytest.mark.asyncio
async def test_sse_redis_streams_replay_and_gap_detection() -> None:
    broker = RedisStreamEventBroker(redis_client=None, maxlen=3)
    e1 = await publish_chat_token(
        user_id="u1", channel="t1", session_id="s1", message_id="m1", token="a", index=0, broker=broker
    )
    e2 = await publish_tool_progress(
        user_id="u1", channel="t1", task_id="t1", call_id="c1", tool_name="grep", stage="started", broker=broker
    )
    e3 = await publish_mcp_notification(
        user_id="u1",
        channel="t1",
        server_name="mcp",
        method="notifications/progress",
        params={"p": 50},
        kind="progress",
        broker=broker,
    )
    replayed, cursor = await broker.read_batch(user_id="u1", channel="t1", cursor=e1.stream_id, block_ms=5)
    assert [x.stream_id for x in replayed] == [e2.stream_id, e3.stream_id]
    assert cursor == e3.stream_id

    await publish_chat_token(
        user_id="u1", channel="t1", session_id="s1", message_id="m1", token="b", index=1, broker=broker
    )
    await publish_chat_token(
        user_id="u1", channel="t1", session_id="s1", message_id="m1", token="c", index=2, broker=broker
    )
    gap_batch, _ = await broker.read_batch(user_id="u1", channel="t1", cursor=e1.stream_id, block_ms=5)
    assert gap_batch[0].event_type == "sse.stream.gap_detected"


def test_sse_envelope_rejects_header_injection() -> None:
    with pytest.raises(ValueError, match="Unsafe SSE event_type"):
        SSEEnvelope(
            stream_id="100-0",
            event_type="chat.token\r\nevent: injected",
            channel="t1",
            user_id="u1",
            payload={},
        )
    assert normalize_stream_cursor("0") == "0-0"
    assert compare_stream_ids("1763000100-1", "1763000100-2") == -1


@pytest.mark.asyncio
async def test_mcp_contract_pre_init_guard_adapter_and_registry(tmp_path: pathlib.Path) -> None:
    synth_gh = "ghp_" + "1234567890abcdefghijklmnopqrstuv"
    (tmp_path / "env.py").write_text(f'TOKEN = "{synth_gh}"\n', encoding="utf-8")
    dispatcher = PlatformMCPServer(tmp_path)
    assert isinstance(dispatcher, PlatformMCPContractDispatcher)

    pre_init = dispatcher.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert pre_init is not None and pre_init["error"]["code"] == -32002

    init_ok = dispatcher.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "initialize"})
    assert init_ok is not None and init_ok["result"]["protocolVersion"] == "2024-11-05"

    assert dispatcher.handle_jsonrpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    trav = dispatcher.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "repo_read_file", "arguments": {"path": "../../etc/passwd"}},
        }
    )
    assert trav is not None and trav["result"]["isError"] is True

    call_ok = dispatcher.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "repo_read_file", "arguments": {"path": "env.py"}},
        }
    )
    assert call_ok is not None
    assert synth_gh not in call_ok["result"]["content"][0]["text"]
    assert "[REDACTED" in call_ok["result"]["content"][0]["text"]

    # Verify MCPToolAdapter executes against PlatformMCPServer
    adapter = MCPToolAdapter(server_id="mcp-platform-core", workspace_root=tmp_path, dispatcher=dispatcher)
    tdef = ToolDefinition(
        name="repo_read_file",
        description="Read file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    adapter_res = adapter.execute(tdef, {"path": "env.py"}, {})
    assert adapter_res["isError"] is False

    # Verify MCP Registry API endpoints & SSRF protection
    servers = await list_mcp_servers()
    assert len(servers) >= 1
    pinged = await ping_mcp_server("mcp-platform-core")
    assert pinged.status == "connected"
    toggled = await toggle_mcp_server("mcp-platform-core")
    assert toggled.enabled is False
    toggled_back = await toggle_mcp_server("mcp-platform-core")
    assert toggled_back.enabled is True
    pol_updated = await update_mcp_tool_policy(
        "mcp-platform-core",
        "repo_read_file",
        UpdateToolApprovalPolicyRequest(requiresApproval=True),
    )
    assert any(t.name == "repo_read_file" and t.requiresApproval is True for t in pol_updated.tools)

    with pytest.raises(APIError):
        await register_mcp_server(
            RegisterMCPServerRequest(
                name="Bad SSRF MCP",
                transport="sse",
                endpointOrCommand="http://169.254.169.254/latest/meta-data/",
            )
        )


@pytest.mark.asyncio
async def test_vcr_cassette_record_replay_gateway_and_drift_diagnostic(tmp_path: pathlib.Path) -> None:
    cassette_path = tmp_path / "cassettes" / "suite.json"
    rec = VCRLLMCassette(cassette_path=cassette_path, mode="record")
    synth_gemini_key = "AIzaSyD-" + "1234567890abcdefghijklmnopqrstuv"

    async def _live() -> Dict[str, Any]:
        return {"content": "SSE stream via Redis Streams", "api_key": synth_gemini_key}

    recorded = await rec.execute_or_replay(
        provider="gemini",
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "Explain events.py"}],
        live_callable=_live,
    )
    assert recorded["api_key"] == "[REDACTED_SECRET]"

    rep = VCRLLMCassette(cassette_path=cassette_path, mode="replay")
    hit = await rep.execute_or_replay(
        provider="gemini",
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "Explain events.py"}],
    )
    assert hit["content"] == "SSE stream via Redis Streams"
    hit["content"] = "MUTATED"
    hit_again = await rep.execute_or_replay(
        provider="gemini",
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "Explain events.py"}],
    )
    assert hit_again["content"] == "SSE stream via Redis Streams"

    with pytest.raises(VCRCacheMissError, match="Prompt drift vs closest cassette entry"):
        await rep.execute_or_replay(
            provider="gemini",
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "Explain events.py with drift"}],
        )

    # Verify committed platform_llm_vcr.json replays through LLMGateway without network egress
    committed_cassette_path = (
        pathlib.Path(__file__).resolve().parent / "fixtures" / "cassettes" / "platform_llm_vcr.json"
    )
    platform_cassette = VCRLLMCassette(cassette_path=committed_cassette_path, mode="replay")
    gateway = LLMGateway(
        provider=GeminiProvider(api_keys=["test-key"]),
        vcr_cassette=platform_cassette,
    )
    gw_resp = await gateway.generate(
        LLMRequest(
            model="gemini-flash-lite-latest",
            messages=[Message(role="user", content="Explain backend/app/api/v1/events.py")],
            temperature=0.0,
        )
    )
    assert "Last-Event-ID" in gw_resp.content
