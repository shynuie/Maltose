# ADR-002: Isolate Command Execution from the Host Filesystem

- 狀態：`accepted`
- 日期：2026-10-01
- 相關 feature：[Command Execution Sandbox](../features/command_execution_sandbox_dev_plan.md)

## Context

Agent 需要執行測試、編譯、Python、shell tooling 與 package install 才能提供接近 Codex 的開發體驗。
但執行中的程式可以直接呼叫 filesystem、subprocess、network 與 environment API；單靠 Agent prompt、命令 allowlist 或 FileService policy 無法限制這些行為。

## Decision

command execution 透過獨立的 `ExecutionBroker` 與 `SandboxBackend` 執行。預設 backend 必須提供 disposable filesystem、受控 mounts、resource limits、network default deny 與 process cleanup。

只將 working root 以可寫 mount 暴露；readable roots 以唯讀 mount 或 input copy 暴露；protected roots、credentials、host sockets 與 KDB state 不暴露。sandbox output 必須經 `ArtifactPromoter` 與既有 `FileService` 才能寫回真實 working root。

第一個 backend 以 rootless container 為優先候選；backend 不可用時 fail closed，不退回 unrestricted host shell。macOS VM / App Sandbox helper 與 Linux Landlock 等能力保留在 backend interface / hardening phase 評估。

目前可用 backend 為 Docker。Docker Desktop 上採用 `overlay2` 時，writable-layer
quota 會明確標示為 unsupported；`tmpfs`、memory、PID、timeout 與 output quota
仍然啟用。restricted allowlist network 在沒有 proxy backend 時明確 fail closed，
不以 `bridge` 假裝 exact-domain isolation。

Linux Landlock、額外 namespace/seccomp profile 與 macOS
Virtualization.framework/App Sandbox 屬於替代 backend 的平台實作，不會在 Docker
backend 中以不可驗證的 flags 冒充支援。

## Alternatives Considered

- **直接在 host shell 執行**：能力最完整，但任意腳本可繞過 FileService 修改受保護 root，不接受。
- **只用 prompt 或命令 allowlist**：無法限制已允許腳本內的 `os.remove`、subprocess、network 等行為，不是安全邊界。
- **只建立 temporary working directory**：若 subprocess 仍繼承 host filesystem 權限，temporary directory 不能阻止它讀寫其他路徑。
- **每個命令都在一次性 VM 執行**：隔離較強，但啟動成本較高；先透過 backend interface 保留，按平台與風險 profile 採用。

## Consequences

- Agent 可以在 sandbox 內安裝 dependencies、執行 tests/build、產生 artifacts，體驗接近 Codex。
- 主機安全性依賴 backend 的正確配置與 OS/container hardening，必須有 security regression tests。
- package cache、virtualenv、network access 與輸出 promotion 都需要額外 lifecycle、audit 與 quota 管理。
- execution sandbox 與 Filesystem Sandbox 成為兩個互補 feature：前者限制程式，後者限制 Agent 直接工具操作。
