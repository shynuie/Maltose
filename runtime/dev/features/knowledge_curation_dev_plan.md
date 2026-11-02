# Knowledge Curation 開發計畫

## 文件狀態

- 狀態：`done`
- 目前階段：Milestone accepted; future vector/index extensions deferred
- 最後更新：2026-10-01

## 目標

讓 Agent 能夠累積可審核的長期知識，但不讓臨時筆記、開發中的程式碼、猜測或錯誤摘要直接污染 KDB truth。

知識分成三層：

```text
Truth documents             # 使用者原始文件，source of truth
        │
        ▼
Knowledge proposals         # Agent 候選知識，pending / rejected / expired
        │ review / approval
        ▼
Curated agent knowledge     # 已批准，獨立 namespace / index
```

## 非目標

- 不讓 Agent 自動修改 `documents/` 或把 proposal 當成 truth。
- 不把 `dev/`、`tests/`、source code、runtime data、models 或 recordings 預設加入 truth KDB。
- 不合併 Memory 與 KDB；個人偏好與使用者資料仍由 Memory 管理。
- 第一階段不自動批准低可信度或無來源內容。
- 第一階段不修改現有 truth KDB 的 parser、vector schema 或 retrieval ranking。

## 知識層級與資料邊界

### Truth documents

- 根目錄：`documents/`。
- 原始文件由使用者擁有，仍是權威來源。
- KDB 只索引允許的 truth roots。
- Agent 只能透過明確的 import / approval workflow 讓內容成為 truth source。

### Knowledge proposals

- 儲存於 `data/knowledge/proposals/` 或獨立 proposal store。
- 不進入預設 KDB retrieval。
- 每筆 proposal 必須有 type、content、status、來源、建立者與時間。
- `hypothesis`、`observation` 永遠需要明確標示，不能被當作已確認事實。

### Curated agent knowledge

- 儲存與 truth index 分離，使用 `agent_curated` source type / namespace。
- 只有明確批准的 proposal 才能發布。
- 回答時必須保留來源與「Agent 整理知識」的 provenance，不得偽裝成原始 truth。

### Memory boundary

- 使用者偏好、個人資訊與 session-specific facts 優先放入 Memory。
- 可重複供多個 session 使用、且有文件來源的穩定知識才適合進入 curated KDB。

## Proposal schema

```json
{
  "proposal_id": "...",
  "type": "fact | procedure | summary | preference | hypothesis | observation",
  "content": "...",
  "sources": [{"root": "documents", "path": "guide.md", "location": "..."}],
  "confidence": 0.86,
  "created_by": "agent",
  "status": "pending | approved | rejected | expired",
  "created_at": "...",
  "expires_at": null,
  "reviewed_by": null,
  "reviewed_at": null,
  "rejection_reason": null
}
```

品質邊界：

- content 不可為空，並有長度上限。
- type 必須是明確允許的類型。
- `fact`、`procedure`、`summary` 預設要求至少一個 source。
- confidence 必須在 `0..1`。
- proposal 不能直接覆蓋另一筆已批准知識；相似或衝突內容先標記待審核。
- 每次 Agent turn 的 proposal 數量與總字數要有限制。

## 架構與 service 邊界

- `KnowledgeProposalStore`：持久化 proposal、狀態轉換與審核 metadata。
- `KnowledgeQualityPolicy`：驗證 schema、來源要求、大小限制與可發布條件。
- `KnowledgeSourcePolicy`：限制 source root，拒絕 `.git`、`dev`、`tests`、runtime data、models、recordings 等非 truth source。
- `KnowledgeCurationService`：建立 proposal、去重 / conflict 檢查、approve / reject / expire 與後續 publish orchestration。
- `CuratedKnowledgeIndexer`：後續階段才建立，將 approved proposal 寫入獨立 curated index。
- `KnowledgeCurationToolAdapter`：暴露 `propose_knowledge`、`list_knowledge_proposals`；approve / reject 僅由使用者 review action 執行。

## 開發階段

### Phase 0 - Architecture & Boundary

狀態：`done`

- [x] 固定 truth、proposal、curated 三層模型。
- [x] 固定 Memory 與 KDB 的責任邊界。
- [x] 固定 proposal schema、source provenance 與 approval requirement。

### Phase 1 - Proposal Store & Quality Boundary

狀態：`in_progress`

- [x] 實作 proposal dataclass、持久化 store 與 atomic save。
- [x] 實作 create / list / approve / reject / expire 狀態機。
- [x] 實作 proposal schema 與 source / confidence / length validation。
- [x] 加入 duplicate proposal 與 invalid transition 測試。

### Phase 2 - Agent Tools & Web Review

狀態：`done`

- [x] 暴露 proposal / list tools，但不暴露直接寫入 truth KDB 的工具。
- [x] 將 proposal 映射到 Web UI review card。
- [x] approval action 綁定 proposal ID、session 與 reviewer。
- [x] 支援 reject reason、expire 與 user-visible provenance。

### Phase 3 - Curated Index

狀態：`in_progress`

- [x] 建立與 truth KDB 分離的 curated store。
- [x] 只有 approved proposal 可以 publish。
- [x] publish 時保留 proposal ID、sources、reviewer、confidence 與 timestamps。
- [x] curated search 回傳 `source_type`，避免把 curated knowledge 當成原始 truth。
- [x] 實作 revoke / unpublish，避免批准後永久不可修正。

### Phase 4 - Retrieval & Runtime Hardening

狀態：`done`

- [x] truth 優先於 curated knowledge，curated 優先於 pending proposal。
- [x] curated store 支援 optional embedding ranking，無 embedding 時使用 lexical fallback。
- [x] hypothesis / observation 預設不參與一般事實回答。
- [x] 加入 exact conflict detection、revoke 後 active-index repair 與 stale knowledge policy。
- [x] 驗證 curated store 重啟、stale、orphaned entry 與 repair consistency。
- [x] 加入 truth-side conflict signal、audit repair 與可恢復 rotation。

## 驗收標準

- [x] Agent 不能直接寫入 truth documents 或 truth index。
- [x] 無來源的 fact / procedure / summary proposal 會被拒絕。
- [x] 開發程式碼與 runtime files 不能作為預設 truth source。
- [x] proposal 狀態轉換只能是 pending → approved / rejected / expired。
- [x] approve / reject 綁定 proposal ID、session / reviewer，不能跨 proposal 重用。
- [x] approved proposal 尚未 publish 前不會出現在一般 KDB retrieval。
- [x] curated knowledge 與 truth index、Memory storage 保持分離。
- [x] 所有 proposal 與審核動作可追蹤 provenance。

## 測試策略

- Unit tests：schema、source policy、confidence / size validation、state transition、expiration。
- Integration tests：proposal store persistence、Web review action、approved-only publish boundary。
- KDB tests：truth / curated namespace separation、retrieval source labeling、revoke / repair。
- Runtime smoke tests：Agent propose → user review → approve → curated publish → labeled retrieval。

## 目前進度

### 2026-10-01 Progress Update

- 狀態：`done`
- 完成：
  - [x] 建立 truth / proposal / curated 三層架構規格。
  - [x] 建立 proposal schema、品質邊界與階段計畫。
  - [x] 實作 `KnowledgeProposalStore`、品質 policy 與 focused tests。
  - [x] 實作 source root policy、Agent proposal tools 與 Web UI review bridge。
  - [x] 實作獨立 `CuratedKnowledgeStore`、publish、revoke 與 labeled search。
  - [x] 接入 CLI runtime wiring，並保持 curation / truth / Memory storage 分離。
  - [x] 建立 truth-first unified retrieval 與 `source_type` labeling。
  - [x] 加入 curated optional embedding ranking 與 lexical fallback。
  - [x] 加入 exact conflict detection、stale exclusion 與 repair report。
  - [x] 將 hypothesis / observation 從預設回答中隔離，並支援 restart consistency audit。
  - [x] 加入 curated contradiction review 與完整 runtime audit event persistence。
  - [x] 加入 truth-side conflict signal、audit repair 與可恢復 rotation。
- 驗證：43 個 knowledge curation / filesystem focused tests 通過；相關 KDB regression 共 54 tests 通過；`git diff --check` 通過。
- 結果：本 feature milestone 已驗收；truth-side 高相似結果只會觸發人工 review，不會自動覆蓋 truth 或自動批准 proposal。
- 阻塞：無
- 下一步：暫停 Knowledge Curation 新增 scope；後續 vector-backed curated index、audit maintenance 可另立 enhancement。
