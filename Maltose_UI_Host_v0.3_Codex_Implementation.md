# Maltose UI Host v0.3 — Codex Implementation Specification

**Status:** implementation-ready engineering brief  
**Target:** macOS native, local-first, multi-agent desktop UI runtime  
**Priority:** Agent UI Awareness is a P0 architectural capability, not a later add-on.

## 0. Instructions to Codex

Build this as a new independent repository unless an existing `maltose-ui-host` repository is provided. Inspect the environment and existing code first; preserve compatible work. Implement in small buildable milestones with tests. Do not claim an Xcode build or macOS GUI test passed unless it actually ran on macOS. If executing in a non-macOS environment, implement protocol, SDK, and web renderer portions and explicitly list native verification blockers. Record assumptions in `docs/decisions/`. Do not silently widen system permissions.

## 1. Product goal

Create a universal **Agent Desktop Runtime** where Maltose Brain, an investment agent, and a coding agent independently create and modify persistent interactive surfaces. Surfaces can live inside a main Workspace, in detached native windows, or as constrained overlays. User gestures work locally without LLM round trips. The Agent UI Awareness subsystem exposes **structured, permission-scoped, time-aware context** so a user can say 'this chart', 'the selected interval', 'put it on the other screen', and the agent can resolve the referent without screenshots.

## 2. Stack

- Swift 6, SwiftUI for app shell, AppKit for `NSWindow`/`NSPanel`, WKWebView for dynamic content; Swift actors for concurrency.
- React + TypeScript + Vite, Zod, ECharts for renderer; all assets bundled offline.
- Authenticated WebSocket bound to `127.0.0.1` (and optionally `::1` with equivalent controls), JSON messages; local credentials in Keychain, revocable agent registration.
- SQLite WAL and schema migrations; serialized mutations through a state actor.
- JSON Schema 2020-12 as protocol source of truth; generated or conformance-tested Swift/TypeScript/Python models.
- Python SDK first, TypeScript SDK second; XCTest, Vitest, pytest, protocol integration tests.

## 3. Components and trust boundaries

`Agent -> SDK -> MUP WebSocket -> Auth/ACL -> Command Router -> Surface Manager + State Actor -> AppKit/SwiftUI/WKWebView`.

`Renderer -> Native Bridge -> Context Collector / Event Router -> Context Store -> ACL-filtered ui.context.* API -> Agent`.

`Data Provider -> Data Registry -> Renderer` (high-rate data bypasses LLM).

The Host is authoritative for surface ownership, focus, geometry, visibility, user preferences, and event ordering. Renderer is authoritative for ephemeral gesture state, but reports semantic selections. Agent owns semantic UI document content only within its permissions. Do not allow renderer input to bypass Host ACL or registered action validation.

## 4. Multi-agent and surface model

Agents have unique authenticated principals, quotas, and grants. A surface has `surface_id`, `owner_agent_id`, `kind` (`workspace|window|overlay`), `revision`, `document`, `placement`, `visibility`, `lifecycle`, and timestamps. Every component has a stable `node_id`. Detach/reattach must preserve node identity, data subscription, selection, and user zoom. A cross-agent grant is explicit, scope-limited, revocable and enforced at every query/event; ownership is never inferred from a client-provided ID.

Surface layout and user overrides are stored separately from semantic UI document. App restart restores durable surfaces with disconnected data marked stale; temporary focus and hover must not be incorrectly restored as active.

## 5. MUP v0.3 envelope

```json
{
  "protocol":"mup/0.3",
  "message_id":"uuid",
  "session_id":"uuid",
  "request_id":"uuid",
  "idempotency_key":"optional-uuid",
  "type":"command",
  "name":"ui.context.get",
  "payload":{}
}
```

Responses correlate by `request_id`, with `ok`, `result` or structured `{code,message,details}` error. Events carry unique event IDs, source agent, surface, monotonic sequence within an event stream, and wall-clock timestamp. Validate size, types, and allowed fields before mutation. Support protocol capability negotiation; do not silently treat v0.2 as v0.3.

### Commands

- Existing: `host.capabilities`; `surface.create/list/get/set_visibility/close/detach/attach`; `ui.render`; `ui.patch`; `ui.inspect`; `events.subscribe/unsubscribe`; `data.register/publish/unregister`.
- Awareness: `ui.context.get`, `ui.context.subscribe`, `ui.context.unsubscribe`, `ui.context.resolve_reference`.
- `ui.patch` supports typed atomic operations `set_props`, `insert_node`, `remove_node`, `move_node`; requires `expected_revision`; revision conflict fails without partial changes.
- `ui.context.get` supports filters `surface_id?`, `include?` (`focus,selection,viewport,layout,visible_nodes,interaction`), `max_age_ms?`, and `since_context_revision?`. Host returns only authorized fields.
- `ui.context.subscribe` supports allowed event kinds and optional surface filters. Subscriptions are scoped to authenticated principal, bounded, revocable, and re-established on reconnect.
- `ui.context.resolve_reference` accepts a short phrase and optional candidate scope, but MUST return ranked **candidates with evidence**, never pretend semantic certainty. Language-level inference remains in the Brain; Host resolution uses structured references, focus, selection, recency, and stable IDs. Ambiguity requires user clarification rather than arbitrary destructive action.

## 6. Agent UI Awareness: required domain model

Create `UIContextSnapshot` with:

```json
{
  "context_revision": 42,
  "captured_at": "2026-10-29T03:00:00Z",
  "active_app": "Maltose UI Host",
  "focused_surface_id": "market-1",
  "focused_node_id": "chart-nvda",
  "surfaces": [{
    "surface_id": "market-1",
    "owner_agent_id": "agent.investment",
    "kind": "window",
    "visible": true,
    "title": "Market Monitor",
    "selected_node_ids": ["chart-nvda"],
    "selection": {
      "node_id": "chart-nvda",
      "kind": "chart.time_range",
      "value": {"start": "2026-10-01", "end": "2026-10-15"}
    },
    "viewport": {"node_id": "chart-nvda", "x_domain": ["2026-10-01", "2026-10-15"]},
    "document_revision": 8,
    "context_revision": 42
  }]
}
```

This is an illustrative snapshot, not real market data. Schema must support nullable/absent fields and privacy redaction. Keep `document_revision` separate from `context_revision` because focus and selection changes must not conflict with document patches.

### Context event types

`context.focus_changed`, `context.selection_changed`, `context.viewport_changed`, `context.surface_visibility_changed`, `context.surface_moved`, `context.surface_detached`, `context.surface_attached`, `context.user_override_changed`, `context.stale`, `context.permission_changed`.

Events should carry stable IDs, event timestamp, context revision, and minimal changed fields. Do not stream raw mouse coordinates or keystrokes to LLM. Debounce/throttle viewport and resize changes; focus/selection events should be prompt. Snapshot and event subscription must agree after reconnect or event gaps.

### Referential resolution

The Brain should call `ui.context.get` or use an authorized fresh context cache before resolving 'this/that/the chart I selected'. Prioritize explicit node reference > currently focused node > active semantic selection > recent interaction > visible candidates. Return confidence/evidence and freshness metadata. If multiple candidates remain, ask the user. Never use stale context to perform destructive actions. No screen capture, global accessibility scraping, or observing other apps in MVP.

### Privacy and permissions

Default: agents can inspect only their own surfaces. A grant can allow Maltose to read a **redacted summary** of another agent's surface; detailed selection or data values require explicit scopes. Do not leak cross-agent data through global focused-surface metadata, event broadcasts, diagnostics, logs, or reference resolution. Revocation must invalidate existing subscriptions immediately. Sensitive input fields must never appear in awareness snapshots or logs. Host may expose 'another private surface is focused' without identity or content if no grant.

## 7. State and concurrency

Persist documents, layouts, explicit user preferences, grants and audit records. Keep ephemeral focus, hover, transient selection, and gesture-in-progress in memory. Use an actor/serialized state machine to apply commands and context updates in defined order. Maintain context revisions independently per applicable scope and document revisions per surface. Reconnect with `context_revision` and resync via snapshot on gaps. Idempotency for side-effecting commands, event deduplication, bounded queues and backpressure. Define stale data behavior explicitly.

## 8. Renderer / Native bridge

Expose a minimal allowlisted message bridge, never arbitrary JavaScript execution. Renderer sends validated semantic events, not full DOM dumps. `chart.line` must emit meaningful `selection_changed` and `viewport_changed` payloads; buttons dispatch registered action IDs. Native focus changes come from AppKit; map NSWindow to stable surface IDs. All rendering assets local, restrictive CSP, blocked unapproved navigation and network destinations. No runtime CDN, no arbitrary agent-generated JS/Swift/shell.

## 9. Repository structure

```text
maltose-ui-host/
  apps/macos/MaltoseApp/
  native/{Transport,Protocol,AgentRegistry,Permissions,StateStore,SurfaceManager,ContextCollector,ContextStore,ReferenceResolver,EventRouter,DataRegistry,RendererBridge}/
  packages/{mup-protocol,renderer,sdk-python,sdk-typescript}/
  examples/{hello-world,market-dashboard,awareness-demo,two-agents}/
  tests/{protocol,integration,e2e,security}/
  docs/{architecture,mup-spec,ui-awareness,security,decisions}/
```

## 10. Milestones — build and test after each

**M0:** Inspect toolchain, repo, and platform. Document architecture decisions, build commands, supported deployment target. Establish CI-capable protocol/renderer tests.

**M1:** Implement MUP v0.3 JSON Schemas, validators, SDK stubs and golden fixtures. Include invalid input, unknown version, duplicate request and revision conflict tests.

**M2:** Implement native Host loopback transport, registration/auth, permissions, state store, workspace and native window lifecycle.

**M3:** Implement bundled React renderer and validated Native bridge; text/button/table/chart; `ui.render`, atomic `ui.patch`, user interaction events.

**M4 (P0):** Implement Context Collector, snapshots, context revisions, focus/selection/viewport event flow, `ui.context.get/subscribe`, and scoped reference candidates. Do not postpone this milestone until visual polish.

**M5:** Implement detach/attach, persisted user layout, Python SDK, data subscriptions and reconnect/resync.

**M6:** Implement two-agent demo, scoped cross-agent sharing, revocation, security regression tests, packaging and docs. Only then consider overlays/Companion animation polish.

## 11. Acceptance tests (must be automated where possible)

1. Agent A creates chart; patches title with expected revision; stale revision rejected atomically.
2. User selects chart interval; Host context snapshot exposes selected chart ID and interval to authorized Agent A without screenshots.
3. User asks 'this chart' after focus changes; resolver returns focused chart candidate with provenance; if two equally plausible charts, it returns ambiguity.
4. User zooms chart; local interaction is immediate; debounced context viewport event reaches subscribed Agent A; no LLM required for zoom.
5. Agent B cannot inspect Agent A's selection, document, or events without grant; unauthorized `resolve_reference` also redacts.
6. Grant Agent Maltose summary-read of Agent B; verify allowed fields only; revoke grant and confirm immediate subscription termination.
7. Detach chart from Workspace to NSWindow; stable node ID, selection, zoom and stream subscription survive.
8. Host restart restores durable windows/layout, but does not invent live focus/selection or claim disconnected streams are fresh.
9. Out-of-order/duplicate events, reconnect gaps, malformed/oversized messages, unregistered actions and invalid patches are handled safely.
10. Offline launch works with packaged React assets; README includes exact build/test steps and test evidence.

## 12. Demo script

Run Host; connect `agent.maltose` and `agent.investment` with separate credentials. Investment creates a chart and streams synthetic data. User zooms and selects a time interval. Investment reads context and can answer 'what happened in this selected period?' with the selected interval. Maltose cannot see details until the user grants summary read. User detaches chart into native window; context updates and selection persist. Revoke grant, disconnect/reconnect, verify redaction and state restoration. Do not use live trading or real credentials in demo.

## 13. Non-goals

Global macOS screen awareness, Accessibility automation of third-party apps, arbitrary agent code execution, external network listener, automated trading, autonomous destructive actions, full 3D editor, voice-avatar animation, MCP Apps compatibility. Leave extension points but do not implement prematurely.

## 14. Completion report required from Codex

Provide: repository tree, implemented milestone checklist, exact commands executed, test/build results with environment, known limitations, security decisions, demo instructions, and next priorities. If macOS GUI verification was impossible, clearly mark it unverified.
