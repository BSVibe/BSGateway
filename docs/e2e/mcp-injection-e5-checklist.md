# E2E Checklist — TODO E5 (MCP injection + workspace_dir wire)

End-to-end validation of `metadata.mcp_servers` and `metadata.workspace_dir`
flowing from `POST /api/v1/chat/completions` → ChatService → WorkerDispatcher
→ Redis Stream → worker → ClaudeCodeExecutor → CLI.

## Static / unit-level

- [ ] `uv run --extra dev pytest bsgateway/tests/test_dispatcher.py -k "workspace_dir or mcp_servers"` 통과
- [ ] `uv run --extra dev pytest bsgateway/tests/test_worker/test_main.py -k "workspace_dir or mcp_servers"` 통과
- [ ] `uv run --extra dev pytest bsgateway/tests/test_worker/test_executors.py -k "workspace_dir or mcp_config or mcp_tmpfile"` 통과
- [ ] `uv run --extra dev pytest bsgateway/tests/test_chat_service_executor_streaming.py::TestMetadataForwarding` 통과
- [ ] 전체 스위트 `uv run --extra dev pytest --cov=bsgateway --cov-fail-under=80` 통과

## Wire / integration

- [ ] `metadata.mcp_servers` 비어있으면 worker가 `--mcp-config` 인자 추가하지 않음 (back-compat)
- [ ] `metadata.workspace_dir` 비어있으면 worker가 cwd `.`로 동작 (기존 default 보존)
- [ ] `metadata.mcp_servers` non-empty → worker가 임시 JSON 파일 생성, claude CLI가 `--mcp-config <path>`로 받음, JSON content는 `{"mcpServers": <forwarded dict>}` (claude CLI 표준 schema)
- [ ] tmpfile은 `os.chmod(0o600)` 후 작성됨 (보안)
- [ ] 정상 종료 / 에러 / 타임아웃 — 어느 경로든 tmpfile `os.unlink` 됨

## Document drift

- [ ] `docs/BSNEXUS_METADATA_CONTRACT.md`에 `workspace_dir`, `mcp_servers` 두 row 추가됨
- [ ] `docs/TODO.md`의 E5 row 제거되었거나 v1 done으로 마크

## opencode / codex 분기

- [x] codex executor는 `mcp_servers` 무시 (CLI MCP 미지원 — TODO 후행). 빈 mcp_servers 시 정상 동작
- [x] opencode executor는 `mcp_servers` 를 ``mcpServers`` 필드로 session create body에 forward (E5b done). 빈 mcp_servers 시 필드 absent
- [x] opencode executor는 `workspace_dir` 무시 (TODO E6b — long-lived `opencode serve` cwd 제한). claude / codex만 per-task cwd 적용
- [x] LLM-path strip: `metadata.mcp_servers` + `metadata.workspace_dir`이 LiteLLM kwargs / BSupervisor extras로 leak되지 않음 (`chat/service.py` strip)
- [x] Non-string `workspace_dir` → `"."` fallback (FileNotFoundError 방지)

## 회귀

- [ ] 기존 streaming 테스트 모두 통과 (`test_chat_service_executor_streaming::TestSystemPromptForwarding`, `TestStreamingResponse`, `TestAwaitPubsubCompletion`)
- [ ] 기존 dispatcher 테스트 모두 통과
- [ ] 기존 worker executor 테스트 모두 통과
