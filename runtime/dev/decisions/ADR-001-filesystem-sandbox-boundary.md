# ADR-001: Filesystem Sandbox Boundary

- 狀態：`accepted`
- 日期：2026-10-01
- 相關 feature：[Filesystem Sandbox 開發計畫](../features/filesystem_sandbox_dev_plan.md)

## Context

MyAgent 需要讓 Agent 在本機檔案上進行閱讀、建立、修改與刪除，但不能讓模型直接取得任意 filesystem API 或整台電腦的路徑權限。

目前 KDB 已對 `documents/` 提供局部的 root containment 檢查，TaskBrain 也已有 capability registry；若不同 tool 各自處理路徑與權限，未來容易出現繞過檢查的能力入口。刪除、覆蓋與批次修改也需要人工確認、審計與恢復機制。

## Decision

採用應用程式層的 deny-by-default filesystem sandbox，並固定以下責任邊界：

1. Agent 只能使用具名、allowlisted filesystem roots 與 root-relative path。
2. 所有 path resolution 必須經過單一 `PathResolver`；它負責拒絕絕對路徑、`..` 越界、symlink component、protected path 與 root 外路徑。
3. 所有實際 filesystem I/O 必須經過 `FileService`；Tool adapter 不直接呼叫 `open()`、`unlink()` 或其他 filesystem API。
4. `PolicyEngine` 以 root、operation、目標狀態、檔案大小與批次規模決定 `allow`、`approval_required` 或 `deny`。
5. 高風險操作使用綁定 session、path、operation、expected hash 與 expiration 的一次性 approval。
6. 既有檔案修改使用 expected hash，避免 Agent 以過時內容覆蓋使用者的新修改。
7. 寫入採 atomic replacement；刪除先移到 Agent 專屬 trash，並記錄 audit operation，支援 restore / undo。
8. `copy` 與 `move` 分開授權：copy 的 source 只需 read，destination 必須可寫；move 的 source 也必須具備 delete / write 權限，因為 move 必然包含 source mutation。read-only root 只能作為 copy source，不能作為 move source。
9. 文件 root 的變更由 KDB coordinator 重新索引；KDB metadata、vectors 與 queue 永遠不是原始文件的替代品。
10. 本 feature 不包含任意 shell / subprocess execution；未來命令執行另立 feature，採更強的 OS-level sandbox 評估。

## Alternatives Considered

- 只在 system prompt 中告訴模型不能存取危險路徑：不採用。Prompt 不是 enforcement boundary，模型或工具 bug 都可能繞過。
- 讓每個 file tool 自行檢查 path：不採用。容易產生不一致的檢查與漏網入口。
- 直接暴露一個任意絕對路徑的 `filesystem` tool：不採用。權限範圍過大，難以審計與確認。
- 使用 shell command 取代 typed file operations：不採用。命令注入、環境變數、網路與 subprocess tree 會擴大攻擊面。
- 第一版立即依賴 container / VM：暫不採用。先完成單機應用程式邊界與可測試的恢復流程；若未來需要任意程式執行，再加入 OS-level isolation。

## Consequences

- File tools 的安全行為集中且可單元測試，KDB 與 Web UI 可以重用同一組邊界。
- 使用者能看到高風險操作的明確 diff、批准範圍與 audit record，且刪除可恢復。
- 第一版需要設計 root config、approval state、trash 與 audit persistence，實作成本高於直接包裝 `Path`。
- symlink、hardlink 與某些特殊 filesystem 行為需要保守拒絕，可能降低部分進階檔案操作的便利性。
- 應用程式層 sandbox 不能取代真正的 OS sandbox；未來若加入任意命令執行，必須另行設計與驗證。
