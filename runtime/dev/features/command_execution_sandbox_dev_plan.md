# Command Execution Sandbox 開發計畫

## 文件狀態

- 狀態：`in_progress`
- 目前階段：Phase 4 - Hardening & Platform Backends
- 最後更新：2026-11-01

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

狀態：`done`

- [x] 定義 `ExecutionRequest`、profiles、approval scope、result 與 audit schema。
- [x] 固定 execution sandbox 與 FileService 的責任邊界。
- [x] 固定 mount、network、credential、resource-limit 的 default deny policy。
- [x] 建立 backend capability interface，避免把 container implementation 直接散落在 Agent loop。
- [x] 建立 `ExecutionBroker`，集中處理 policy、approval、ephemeral session 與 backend dispatch。

### Phase 1 - Disposable Workspace Backend

狀態：`done`

- [x] 實作 Docker backend command boundary，支援 read-only image、working-root mount、temporary writable storage。
- [x] 實作 argv-only execution，禁止未明確要求的 shell composition。
- [x] 實作 timeout、memory、PID 與 stdout/stderr limit enforcement hooks。
- [x] 完成跨 Docker storage driver 的 writable-layer disk quota enforcement；支援的 driver 使用 `--storage-opt`，unsupported driver 明確暴露 capability 並不偽造保證。
- [x] 實作 process-group cleanup hook；session recovery 與 daemon-level validation 待 integration phase。

### Phase 2 - Dependencies & Network

狀態：`in_progress`

- [x] 讓 `pip install` / npm / build tool 使用 sandbox 內獨立 environment，不污染 host environment。
- [ ] 實作 network profiles：off、restricted allowlist、explicit approved access。
- [x] 實作 network-off 與 approval-gated explicit bridge access；restricted allowlist proxy 尚待 backend。
- [x] 防止 secrets 從 host environment、dotfiles、socket 或 mounted path 洩漏。
- [x] 記錄 package install 與 network policy，但不把 credentials 寫入 logs。

### Phase 3 - Artifact Promotion & Runtime Integration

狀態：`done`

- [x] 將 output manifest、hash、size 與 destination policy 接入 FileService。
- [x] 高風險 output promotion 使用 scoped approval；不得由 sandbox 直接寫 protected roots。
- [x] broker 在 promotion approval pending 時保留 session，支援同一 execution ID resume promotion。
- [x] 將 pending promotion session、artifact plan 與 hash 持久化，支援 broker restart recovery。
- [x] 加入單一 artifact、整批 artifact quota 與可選 MIME/content-type allowlist。
- [x] 對多 artifact promotion 使用單一 batch-scoped approval，避免一次性 approval 被部分消耗。
- [x] 將 command request、approval、running、completed、failed、timed_out、output_limit 接入 runtime events。
- [x] 提供可觀測 metrics 與 structured audit record。
- [x] 將 typed execution events 適配到 shared EventHub，並讓 Web UI 顯示 execution lifecycle。
- [x] 以 explicit `--execution-enabled` flag 暴露 `execute_command` tool；tool 不直接呼叫 subprocess。
- [x] 將 execution/network/artifact approvals 接入 Web UI confirmation actions。
- [x] Web UI approve artifact promotion 後可依 approval ID 自動 resume pending execution。
- [x] workspace profile 只將 configured working root 以 `/workspace` 可寫 mount 暴露；safe profile 不掛載 project root。
- [x] workspace profile 將 configured readable roots 以 `/inputs/<name>` 唯讀 mount 暴露。
- [x] readable roots 改為 explicit `input_paths` 按需 mount；未請求的 root 不暴露。

### Phase 4 - Hardening & Platform Backends

狀態：`done`

- [x] 完成第一輪 Docker command/mount/network/credential fail-closed review。
- [x] Docker backend 執行前驗證 daemon 可用性；不可用時不退回 host shell。
- [x] 以真实 Docker integration test 驗證 read-only mount、read-only container root 與 stdout limit。
- [x] 以真实 Docker integration test 驗證 timeout/process cleanup，並拒絕 symlink mount source。
- [x] Docker execution 禁止 runtime image pull，避免 sandbox 外部出現隱含 network side effect。
- [x] 批量 artifact promotion 在任何寫入前完成 source hash 與 destination preflight。
- [x] 完成 container escape、symlink 與 resource exhaustion integration review。
- [x] 在 Linux 評估 Landlock / namespaces / seccomp 的額外限制；結論記錄於 ADR-002，Docker backend 不冒充未驗證的平台能力。
- [x] 在 macOS 評估 App Sandbox helper 或 Virtualization.framework backend；結論記錄於 ADR-002，保留為後續獨立 backend 而不降低目前 Docker 隔離邊界。
- [x] 明確記錄 backend 不可用時的 fail-closed 行為；不得自動退回 unrestricted host shell。

## 驗收標準

- [x] Agent 可以在 sandbox 內執行 Python、測試、編譯與 package install。
- [x] 執行程式無法讀寫未掛載的 protected roots、credentials、KDB state 或主機其他目錄。
- [x] working root 可依 profile 讀寫，但 command execution 不會取得整個 repository / home directory。
- [x] readable roots 對 sandbox 是 read-only；readable-only source 不會因 command execution 變成可刪除。
- [x] 所有 subprocess 都受 timeout、resource limit 與 process-tree cleanup 約束。
- [ ] network 預設 deny；restricted network 只允許 exact allowlist，且 approval 與 audit 可追蹤。
- [x] package install 寫入 sandbox environment，不污染 host Python/npm environment。
- [x] output 只有在 ArtifactPromoter + FileService 通過後才能寫回 working root。
- [x] backend 初始化失敗、approval timeout 或 policy 不明時 fail closed。
- [x] 不存在可由 Agent 直接取得的 host shell fallback。
- [x] security regression、integration tests、runtime smoke tests 通過。

## 測試策略

- Unit tests：request/schema validation、argv policy、mount policy、network policy、approval scope、resource limits。
- Integration tests：在 temporary backend 中執行 script，驗證 working root 可寫、protected root 不可見、read-only input 不可修改。
- Security tests：symlink、`..`、host path probing、environment probing、subprocess spawning、network bypass、output escape。
- Runtime smoke tests：package install、pytest/build、timeout、large output、crash、recovery、artifact promotion。

## 目前進度

### 2026-11-01 Maltose 整合驗證

- 已實際執行本機既有 Docker engine 與快取映像的五項整合測試，未升級依賴或下載映像。新 opt-in 名稱為 `MALTOSE_RUN_DOCKER_INTEGRATION`，舊 `MYAGENT_RUN_DOCKER_INTEGRATION` 保留 fallback。
- 修正 timeout 只終止 Docker client 的缺口：唯一 execution 名稱／標籤查詢完整容器 ID，daemon 強制移除後再確認不存在；身分不符、daemon 失聯或清理未確認不宣稱成功。
- 強化 timeout fixture：忽略 TERM 的父子程序持續寫入 heartbeat，回傳後 heartbeat 停止且容器消失；另外建立的獨立容器不被清理。加入 daemon 失聯／錯誤 ID 的拒絕測試。
- 最新完整 Python 378 項，0 failures／errors／skip，包含五項實際容器整合。指定 Maltose execution 標籤無殘留；engine 上仍有其他獨立容器，因此保留 engine 運作。
- restricted-network proxy 及原規劃的跨平台能力仍未完成，不因本次 timeout 驗收而勾選。詳細證據見 [整合清理報告](../../../docs/verification/main-review-and-cleanup-report.md)。

### 2026-10-01 Progress Update

- 狀態：`in_progress`
- 完成：
  - [x] 確認 command execution 應獨立於已完成的 Filesystem Sandbox feature。
  - [x] 確認採用 disposable execution environment、可寫 working root、唯讀 readable roots 與 output promotion 模型。
  - [x] 建立 `ExecutionRequest`、profiles、limits、network policy 與 stable approval scope models。
  - [x] 建立 default-deny `ExecutionPolicy`，禁止未授權 privileged / network execution。
  - [x] 建立 `SandboxBackend`、`MountSpec` 與 explicit capability boundary。
  - [x] 建立 Docker backend 的 isolated argv/mount command builder 與 fail-closed checks。
  - [x] 建立 broker 的 scoped approval、mount target validation 與 ephemeral session cleanup。
  - [x] 建立 artifact promotion plan、hash/size/symlink validation 與 FileService byte-write path。
  - [x] 將 broker lifecycle 接入 typed events、runtime metrics 與 structured audit log。
  - [x] 串接 execution session 與 promotion approval resume，避免 approval 等待期間提前清理 sandbox。
  - [x] 建立 pending promotion JSON store，並驗證重啟 broker 後可恢復 promotion。
  - [x] 將 execution events 接入 shared EventHub 與 Web UI SSE。
  - [x] 加入 Docker daemon preflight，区分 client 可用與 daemon 可用。
  - [x] 加入 Docker approved network bridge 與 writable-layer/tmpfs quota command parameters；restricted network 維持 fail-closed。
  - [x] 在已啟動的 Docker Desktop 上通過 5 個真实 container security regression tests（含 PID fan-out limit）。
  - [x] 修正多 artifact promotion lifecycle，並驗證 batch approval 與 broker resume。
  - [x] 以 opt-in CLI flag 接入 `ExecutionToolAdapter`，並驗證 malformed tool arguments 會拒絕。
  - [x] 將 execution approval UI bridge 接入 CLI，且未配置 ArtifactPromoter 時拒絕帶 outputs 的 execution。
  - [x] 驗證 workspace/safe profile 的 mount 差異，避免 safe execution 意外取得 project root。
  - [x] 驗證 readable roots 的 command mount 永遠是 read-only。
  - [x] 驗證未請求 readable root 不會出現在 execution mounts。
  - [x] 將 restricted-network 與 disk-quota backend capability 明確化；不支援時由 broker 提前拒絕。
  - [x] 修正 Docker daemon storage-driver preflight parsing，讓支援 quota 的 storage driver 能正確啟用 writable-layer quota。
- [x] 驗證 approval UI 可觸發 pending promotion resume。
- 驗證：40 個 execution model/backend/broker/artifact/runtime/UI/tool/integration tests 通過；5 個 Docker integration tests 在 Docker Desktop 上通過；approved bridge package-install smoke test 通過；`py_compile` 與 `git diff --check` 通過。完整 unittest 仍有既有 optional-dependency/port sandbox failures。
- 結果：Phase 0/1 control-plane 與 disposable Docker workspace backend 已完成；Phase 3 artifact/runtime integration 已完成；Phase 2 僅剩 restricted allowlist proxy。
- 阻塞：restricted network proxy；目前沒有可用的強制 allowlist proxy runtime，Docker `bridge` 不能安全地宣稱 exact-domain isolation。
- 下一步：需要可用的 restricted-network proxy runtime，才能完成最後的 exact-domain network isolation 驗收。

## 原生 Docker 崩潰清理修補（build 13）

已修復前輪 TERM-resistant 容器在 root 群組崩潰後繼續寫入的缺口。原生 guardian 接管 stopped-container 建立、PID／准入 barrier 與完整 ID 的持久化；主 runtime 只啟動已登記容器，kernel lease 延伸至 daemon 清理。未確認時關閉 gate 並失敗，重啟先清理且不重播。七項真實故障／同目錄恢復矩陣通過，含 API 失聯後的啟動阻擋與旁觀容器保全。聚焦 44 項、完整 Python 408 項無失敗／skip；Swift 141 項無失敗、15 GUI skip。獨立 build 13 的 145／129 檔來源、簽章、受管理匯入與憑證掃描通過；dist 的 build 11 未被覆蓋。正式 GUI、真人及全 App 故障驗收仍待人員解鎖，目標未完成。詳見 [容器生命週期驗證](../../../docs/verification/native-docker-lifetime-report.md)。
