# Filesystem Sandbox 開發計畫

## 文件狀態

- 狀態：`done`
- 目前階段：Phase 4 - KDB Integration & Runtime Hardening
- 最後更新：2026-10-01

## 目標

為 MyAgent 建立受策略約束的本機檔案能力，讓 Agent 能夠在明確授權的範圍內：

- 閱讀、搜尋與列出檔案。
- 建立、修改、複製與移動檔案。
- 在需要時刪除檔案，並提供可恢復的 trash / undo 機制。
- 透過 Web UI 或其他互動入口取得高風險操作的明確確認。
- 對所有檔案操作留下可追蹤的結構化 audit record。

核心原則：

> LLM 只能提出檔案操作意圖；Path Resolver、Policy Engine 與 File Service 由程式碼強制執行安全邊界。

Sandbox 的預設策略是 deny-by-default。Agent 不應直接取得任意 `Path`、`open()`、`unlink()` 或 shell 權限。

## 非目標

- 第一版不提供任意 shell command execution；檔案能力與命令執行能力保持獨立。
- 不讓 Agent 直接操作 Memory、KDB metadata、vector store、credentials 或模型 cache。
- 不支援遠端、多使用者或跨機器檔案服務。
- 不把 prompt 中的安全規則視為真正的權限控制。
- 不在第一版處理完整的作業系統級 VM / container isolation；先建立應用程式層的 allowlist、policy、approval 與恢復機制。
- 不改變 KDB 的 source-of-truth 原則：`documents/` 下的原始文件仍是權威內容。

## 架構與 service 邊界

### 受控 filesystem roots

以具名 root 暴露檔案範圍，每個 root 個別設定路徑與權限，而不是讓 Agent 傳入任意絕對路徑。初始建議：

```toml
[filesystem.roots.documents]
path = "documents"
read = true
write = true
delete = false

[filesystem.roots.workspace]
path = "workspace"
read = true
write = true
delete = true

[filesystem.roots.data]
path = "data"
read = true
write = false
delete = false
```

`models/`、`recordings/`、`.env`、SSH keys、credentials 與其他敏感路徑預設不暴露。

Session 另有一個由使用者或 runtime 授予、不可由 Agent 自行擴大的 `working_root`。讀取可以使用 session 的 readable roots allowlist；create、write、patch 與 delete 只能作用於 working root。working root 不是額外的繞過，而是本次 session 的寫入上限。

### PathResolver

`PathResolver` 是所有檔案操作的唯一路徑入口，負責：

- 拒絕絕對路徑與 `..` 越界。
- 解析後確認路徑仍位於指定 root 內。
- 檢查 symlink、父目錄與目標路徑，避免繞過 root containment。
- 驗證 source 與 destination，涵蓋 copy / move 等雙路徑操作。
- 套用 protected path 規則。

其他 service 不自行實作 path safety。

### PolicyEngine

`PolicyEngine` 根據 root、操作類型、目標狀態、檔案大小、批次規模與 session context 回傳：

- `allow`：可直接執行。
- `approval_required`：建立一次性待批准操作。
- `deny`：拒絕並回傳原因。

風險分級：

- Low：list、search、read。
- Medium：create、write、copy、move、覆蓋既有檔案。
- High：delete、批次變更、修改受保護或重要 root。
- Critical：credentials、系統目錄、任意命令執行；預設拒絕。

### FileService

`FileService` 提供原子且可審計的檔案操作：

- `list_files`
- `read_file`
- `search_files`
- `create_file`
- `write_file`
- `apply_patch`
- `copy_file`
- `move_file`
- `delete_to_trash`
- `restore_operation`

修改既有檔案時支援 `expected_sha256`。若檔案在讀取後已被其他人修改，操作必須失敗而不是覆蓋最新內容。

寫入採用暫存檔、`fsync` 與 atomic rename；刪除先移入 Agent 專屬 trash，第一版不直接永久 `unlink()`。

### ApprovalManager

高風險操作建立一次性 approval record，並綁定：

- session / user identity。
- root、相對路徑與操作類型。
- 預期檔案 hash。
- diff、檔案大小與風險說明。
- expiration time。

批准後只能執行該筆 operation，不能泛化成「允許 Agent 修改這個資料夾」。

### AuditLog

每次操作記錄 operation ID、session、root、相對路徑、舊 / 新 hash、approval ID、狀態、錯誤與 timestamp。Audit log 不由普通 filesystem tools 暴露修改能力。

### FileCapabilityAdapter

透過現有 `CapabilityAdapter` 與 `ToolRegistry` 暴露檔案工具。Adapter 只負責 schema 與 tool handler wiring，不承擔路徑安全、權限判斷或直接 filesystem I/O。

### KDB 整合

`documents/` 的建立、修改、移動與刪除完成後通知 KDB coordinator：

- 新檔案或修改檔案觸發 re-index。
- 移動更新 source path 與 index metadata。
- 刪除標記相關 index 為 deleted，不能以 metadata / vector 取代原始文件。

現有 `DocumentIngestionService`、`SourceReader` 與 watcher 可重用，但所有寫入仍須經過新的檔案安全邊界。

## 開發階段

### Phase 0 - Architecture & Boundary

狀態：`done`

- [x] 建立 `filesystem_sandbox_dev_plan.md` 並固定 feature scope。
- [x] 建立 ADR，記錄 allowlisted roots、default deny、approval、trash、hash conflict 與 shell separation 決策。
- [x] 定義 filesystem config schema、root permissions、protected paths 與 operation risk model。
- [x] 定義 `PathResolver` 的第一版 interface。
- [x] 定義 `PolicyEngine`、`FileService`、`ApprovalManager`、`AuditLog` 的 interface。
- [x] 決定 approval 與現有 Web UI `ui_confirmation` / action endpoint 的事件格式。

### Phase 1 - Safe Read Surface

狀態：`done`

- [x] 實作具名 root 設定與安全 path resolution。
- [x] 實作 `list_files`、`read_file`、`search_files`。
- [x] 加入 symlink、`..`、絕對路徑、protected path 與 root containment 測試。
- [x] 將檔案 read tools 透過 `CapabilityAdapter` 暴露。
- [x] 限制單次讀取大小、搜尋結果數量與列出結果數量。

### Phase 2 - Controlled Writes

狀態：`done`

- [x] 實作 working root 內的 create、write、copy 與受約束文字替換。
- [x] 加入 expected hash，拒絕 stale read overwrite。
- [x] 實作 atomic write、temporary file cleanup 與基本檔案結果 metadata。
- [x] 對既有檔案覆蓋與非 working root 寫入套用 policy。
- [x] 固定 copy / move 的雙邊權限：copy 允許 read source 到 working destination；move 只有在 source 也可寫 / 可刪除時才允許。
- [x] 由檔案操作結果產生結構化 operation result。

### Phase 3 - Approval, Delete & Recovery

狀態：`done`

- [x] 實作 PolicyEngine 的 allow / approval / deny decision。
- [x] 實作一次性、具 expiration 的 approval record。
- [x] 將 approval request / approve / reject 接入現有 Web UI confirmation transport。
- [x] 實作 delete-to-trash、restore 與 undo operation。
- [x] 實作不可由普通 file tool 修改的 audit log。

### Phase 4 - KDB Integration & Runtime Hardening

狀態：`done`

- [x] 建立 typed filesystem mutation event 與 observer interface。
- [x] 將 documents root 的 create / modify / copy / trash / restore 映射到 KDB coordinator。
- [x] 驗證 KDB 原始文件、metadata、vectors 與 queue 的責任邊界。
- [x] 將 mutation event 接入現有 durable indexing queue，支援 worker 後續 retry。
- [x] 加入服務重啟後 queued / running job recovery 測試。
- [x] worker 執行前驗證 mutation freshness，舊 job 以 `superseded` 結束而不覆蓋新內容。
- [x] 加入 runtime metrics / events，讓 runtime 能呈現 pending、success、failure、restored 基本 counters。
- [x] 完成 security review，確認 filesystem tools 均只能透過 FileService 操作受控檔案。

### Phase 5 - Future Command Sandbox Evaluation

狀態：`deferred`

- [ ] 只有在明確需求出現後，另立 command execution feature plan。
- [ ] 評估 macOS sandbox、container 或其他 OS-level isolation。
- [ ] 定義 network、environment、CPU、memory、timeout、stdout 與 subprocess tree 限制。
- [ ] 不將 command execution 與本 feature 的 file tools 合併成萬用工具。

## 建議工具介面

第一版 Agent tools 建議採用 root + relative path：

```text
read_file(root, path, max_bytes)
list_files(root, path, recursive, limit)
search_files(root, query, path, limit)
create_file(root, path, content)
apply_patch(root, path, patch, expected_sha256)
copy_file(source_root, source_path, destination_root, destination_path)
move_file(source_root, source_path, destination_root, destination_path)
delete_file(root, path, reason)
restore_file(operation_id)
```

工具結果必須包含 `operation_id`、root、相對路徑、狀態與必要的 hash / size metadata。工具不能接受任意 Python expression、shell command 或 callback。

`copy_file` 的 source 可以是 readable root，但 destination 必須落在 session `working_root`。`move_file` 不可把 readable-only root 當作 source；因為 move 會刪除 source，source 與 destination 都必須通過 mutation policy。若只有 read 權限，Agent 必須改用 copy，不得以 copy + remove 的方式自行拼出 move。

## 驗收標準

- [x] Agent 無法透過 `..`、絕對路徑、symlink 或 hardlink 越過 configured root。
- [x] 未註冊或未授權的 root 預設拒絕。
- [x] `data/`、credentials、models 與 recordings 不會因為一般 file tool 被意外寫入或刪除。
- [x] 讀取、搜尋、建立、patch、copy、move 均只能透過 FileService 執行。
- [x] stale hash 會拒絕覆蓋，且不產生部分寫入。
- [x] 寫入是 atomic 的；程序中斷不會留下不完整的目標檔案。
- [x] 高風險操作在沒有有效 approval 時一定不會執行。
- [x] approval 只適用於單一 operation，過期或 scope 不符時必須拒絕。
- [x] delete 可從 trash restore，且 audit record 可追蹤完整生命週期。
- [x] KDB 文件變更後仍以原始文件為 source of truth，index 能正確更新或標記刪除。
- [x] 沒有 filesystem tool 可以直接啟動 shell 或任意 subprocess。
- [x] `git diff --check` 通過，focused tests 與相關完整測試通過。

## 測試策略

- Unit tests：
  - root containment、相對路徑、symlink / hardlink、protected path。
  - policy risk classification、approval scope、expiration。
  - hash conflict、atomic write、patch failure、trash / restore。
  - operation result 與 audit record schema。
- Integration tests：
  - `ToolRegistry` 到 `FileCapabilityAdapter` 的完整 tool flow。
  - Web UI confirmation 到 backend approval consume 的流程。
  - documents root 變更到 KDB re-index / delete mark 的流程。
  - 服務重啟後 pending approval、trash 與 audit record 的恢復行為。
- Runtime smoke tests：
  - 在 temporary roots 中完成 read / create / patch / move / restore。
  - 驗證預設禁止 data、credentials 與 root 外路徑。
  - 驗證不啟動任意 shell / subprocess。

## 目前進度

### 2026-10-01 Progress Update

- 狀態：`in_progress`
- 完成：
  - [x] 讀取現有 `ToolRegistry`、`CapabilityAdapter`、KDB source reader / ingestion 與 Web UI confirmation 邊界。
  - [x] 建立本 feature 的目標、非目標、service 邊界與分階段實作計畫。
  - [x] 建立 ADR-001，固定 filesystem sandbox 的安全責任邊界。
  - [x] 實作 `PathResolver` 與 temporary-root focused tests。
  - [x] 實作 `PolicyEngine`、read-only `FileService` 與 `FileToolAdapter`。
  - [x] 實作 working-root constrained create、write、copy 與 expected-hash text replacement。
  - [x] 實作一次性 approval、delete-to-trash、restore 與 audit log。
  - [x] 將 filesystem approval record 映射到 `ui_confirmation` 與 scoped UI actions。
  - [x] 定義 `FilesystemConfig` schema 並驗證 working root / readable root 邊界。
  - [x] 建立 typed mutation events 與 `DocumentMutationCoordinator` KDB bridge。
  - [x] 將 mutation event 接入 durable indexing queue 並驗證 restart recovery。
  - [x] 加入 coordinator runtime metrics 與 ignored / failed / indexed counters。
  - [x] 加入 worker freshness guard，避免 stale queue job 覆蓋新內容。
  - [x] 實作雙邊 scoped approval 的 working-root move，並拒絕 readable-only source。
- 驗證：42 個 filesystem / KDB queue / worker focused tests 通過；`py_compile` 與 `git diff --check` 通過。
- 結果：Phase 0–4 已完成。审查中修复了 restore operation ID 的 trash path traversal，并补上 restore 的 working-root policy check；move 采用 source、destination、hash 三重 scoped approval。
- 阻塞：無
- 下一步：filesystem feature scope 完成；Command sandbox 维持 deferred，若未来需要应另立 feature plan。
