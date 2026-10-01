# Command Execution Sandbox 開發計畫

## 文件狀態

- 狀態：`planned`
- 目前階段：Phase 0 - Architecture & Boundary
- 最後更新：2026-10-01

## 目標

讓 Agent 能在接近 Codex 的開發體驗中執行 shell、Python、測試、編譯與 package install，
但讓受控 execution environment 與 MyAgent 主機、受保護 root、credentials、KDB state
保持隔離。執行能力的安全邊界必須由 OS / container / VM 強制，而不是由 prompt 或命令字串審查單獨提供。

## 非目標

- 不讓任意程式直接取得整台主機的 filesystem 權限。
- 不把 `OPENAI_API_KEY`、SSH agent、cloud credentials 或其他長期 secret 放入 execution sandbox。
- 不在本 feature 內重新實作 filesystem tool；輸入準備與輸出 promotion 重用 `FileService`。
- 不把 command execution 與一般 filesystem read/write policy 合併成萬用工具。
- 不承諾對具備主機管理員權限或 kernel exploit 的惡意程式提供防護；此 feature 的目標是普通腳本與 package 的越界防護。

## 架構與 service 邊界

```text
Agent -> ExecutionPolicy -> Approval/UI -> ExecutionBroker
                                      -> SandboxBackend
                                      -> ExecutionResult
                                      -> ArtifactPromoter -> FileService
```

- `ExecutionRequest`：只接受 argv array、明確 input/output artifact、limits 與 network profile；不接受任意 callback 或隱式 shell command。
- `ExecutionPolicy`：判斷 command、working root、network、resource limits 與 approval scope。
- `ExecutionBroker`：建立 disposable execution session，準備輸入、啟動 backend、收集輸出與清理。
- `SandboxBackend`：提供 OS-enforced isolation；第一版優先支援 rootless container，保留 macOS VM / App Sandbox backend interface。
- `ArtifactPromoter`：只將 sandbox output 經 FileService policy、hash 與 approval 後寫回 working root。
- `ExecutionAudit`：記錄 request、image/backend、argv hash、mounts、network policy、approval、exit code、resource usage 與 output manifest；不記錄 secrets。

### 預設 workspace profile

- sandbox root filesystem read-only。
- `working_root` 以可寫 mount 提供給 sandbox；受保護 roots 不 mount。
- readable roots 只讀 mount，或先由 FileService 複製到 input room。
- package cache、virtualenv、build artifacts 留在 sandbox 專用 storage。
- network 預設關閉；需要 package install 時使用受限 allowlist 並要求 approval。
- host socket、Docker socket、credentials、ptrace、特權 capabilities 均不提供。

## 開發階段

### Phase 0 - Architecture & Boundary

狀態：`planned`

- [ ] 定義 `ExecutionRequest`、profiles、approval scope、result 與 audit schema。
- [ ] 固定 execution sandbox 與 FileService 的責任邊界。
- [ ] 固定 mount、network、credential、resource-limit 的 default deny policy。
- [ ] 建立 backend capability interface，避免把 container implementation 直接散落在 Agent loop。

### Phase 1 - Disposable Workspace Backend

狀態：`planned`

- [ ] 實作 rootless container backend，支援 read-only image、working-root mount、temporary writable storage。
- [ ] 實作 argv-only execution，禁止未明確要求的 shell composition。
- [ ] 實作 timeout、CPU、memory、PID、disk、stdout/stderr limits。
- [ ] 實作 process-tree cleanup、crash cleanup 與 session recovery。

### Phase 2 - Dependencies & Network

狀態：`planned`

- [ ] 讓 `pip install` / npm / build tool 使用 sandbox 內獨立 environment，不污染 host environment。
- [ ] 實作 network profiles：off、restricted allowlist、explicit approved access。
- [ ] 防止 secrets 從 host environment、dotfiles、socket 或 mounted path 洩漏。
- [ ] 記錄 package install 與 network policy，但不把 credentials 寫入 logs。

### Phase 3 - Artifact Promotion & Runtime Integration

狀態：`planned`

- [ ] 將 output manifest、hash、size 與 MIME/type policy 接入 FileService。
- [ ] 高風險 output promotion 使用 scoped approval；不得由 sandbox 直接寫 protected roots。
- [ ] 將 command request、approval、running、completed、failed、killed 接入 runtime events。
- [ ] 提供可觀測 metrics 與 structured audit record。

### Phase 4 - Hardening & Platform Backends

狀態：`planned`

- [ ] 完成 container escape、mount、symlink、credential、network 與 resource exhaustion review。
- [ ] 在 Linux 評估 Landlock / namespaces / seccomp 的額外限制。
- [ ] 在 macOS 評估 App Sandbox helper 或 Virtualization.framework backend。
- [ ] 明確記錄 backend 不可用時的 fail-closed 行為；不得自動退回 unrestricted host shell。

## 驗收標準

- [ ] Agent 可以在 sandbox 內執行 Python、測試、編譯與 package install。
- [ ] 執行程式無法讀寫未掛載的 protected roots、credentials、KDB state 或主機其他目錄。
- [ ] working root 可依 profile 讀寫，但 command execution 不會取得整個 repository / home directory。
- [ ] readable roots 對 sandbox 是 read-only；readable-only source 不會因 command execution 變成可刪除。
- [ ] 所有 subprocess 都受 timeout、resource limit 與 process-tree cleanup 約束。
- [ ] network 預設 deny；restricted network 只允許 exact allowlist，且 approval 與 audit 可追蹤。
- [ ] package install 寫入 sandbox environment，不污染 host Python/npm environment。
- [ ] output 只有在 ArtifactPromoter + FileService 通過後才能寫回 working root。
- [ ] backend 初始化失敗、approval timeout 或 policy 不明時 fail closed。
- [ ] 不存在可由 Agent 直接取得的 host shell fallback。
- [ ] security regression、integration tests、runtime smoke tests 通過。

## 測試策略

- Unit tests：request/schema validation、argv policy、mount policy、network policy、approval scope、resource limits。
- Integration tests：在 temporary backend 中執行 script，驗證 working root 可寫、protected root 不可見、read-only input 不可修改。
- Security tests：symlink、`..`、host path probing、environment probing、subprocess spawning、network bypass、output escape。
- Runtime smoke tests：package install、pytest/build、timeout、large output、crash、recovery、artifact promotion。

## 目前進度

### 2026-10-01 Progress Update

- 狀態：`planned`
- 完成：
  - [x] 確認 command execution 應獨立於已完成的 Filesystem Sandbox feature。
  - [x] 確認採用 disposable execution environment、可寫 working root、唯讀 readable roots 與 output promotion 模型。
- 驗證：尚未開始實作。
- 結果：已建立 feature scope；可提供接近 Codex 的 package install、test、build 體驗，同時把主機保護交給 execution backend。
- 阻塞：尚無；backend 選型與本機 container/VM 可用性需在 Phase 0 確認。
- 下一步：建立 execution schema / backend boundary，然後選定第一個可在本機運行的 isolated backend。
