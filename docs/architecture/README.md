# Maltose 架構

Maltose 沿用既有 AppKit／SwiftUI 工作區，並接上受管理的 Python 主 Agent 與按需啟動的 Codex。兩個 Agent 使用相同的原生面板狀態與操作核心；不為 Agent 另建一份面板狀態。完整整合仍在驗收中，進度以 [產品整合計畫](../../plans/maltose-unification-and-codex.md) 及各版本驗證報告為準。

## 既有工作區與共用面板

1. `WorkspaceWindowManager` 管理各螢幕窗口、面板實例、歸屬與跨窗口移動，並持有共用 `WorkspaceAgentInterface`。
2. `WorkspaceRootView` 與 `WorkspaceLayoutState` 管理每個窗口的排列、主面板、選取、全局縮放與側欄。原生 UI 與 Agent 操作都經這些既有入口。
3. `GlassPanelView` 提供 Glass 外框、選取、拖曳／雙擊與內容容器，各內容 model 保有原本的編輯與瀏覽邏輯。
4. `WorkspacePanel` 描述面板類型與實例。示範面板大多仍為記憶體狀態；真實聊天使用持久 journal，流程圖可以另行保存為文件。不能把所有面板都視為已持久化。
5. `WorkspaceAgentInterface` 在 `MainActor` 執行面板指令，供主 Agent、Codex 與 ⌥⌘V 模擬共用。`get_user_view` 依可見模式提供摘要：主面板提供有界可見內容，格子、側欄及隱藏面板提供精簡資訊；原生全螢幕與面板放大是不同狀態。

36 種操作、snapshot v2、各面板能力及模擬方式見 [共用面板介面](workspace-agent-interface.md)。原有互動規格見 [Glass 工作空間計畫](../../plans/glass-workspace.md)。

## Agent 程序與協調

`WorkspaceAppDelegate` 在建立原生窗口後接上 `RuntimeSupervisor`、`AgentSessionCoordinator` 與既有聊天輸入欄。正常啟動會啟動主 Agent，`--ui-only` 僅開工作區。

`RuntimeSupervisor` 管理主 Agent 的初始化、就緒、錯誤、重試與退出。Python runtime 重用原有 VoiceAgent、TaskBrain、語音、Memory、KDB 及檔案政策；以私有 stdio／NDJSON 與 App 溝通。檔案操作先經 Python FileService 驗證，面板修改回到原生操作核心。

`AgentSessionCoordinator` 管理同一聊天的收件人、交接、輸入送達、任務及完成後意圖確認。`@codex` 後續訊息持續送至同一任務；觀看其他面板不改變收件人。交接透過 runtime 的執行權 gate 停止自主派發並等待已執行操作收尾，同時保留同步與持久化；Codex 完成後仍等待使用者的新意圖。

`CodexConnection`／`CodexAdapter` 按需啟動 app-server，`CodexTaskStore` 保存產品任務與 Codex thread、工作目錄和送達狀態的對應。面板工具使用已驗證版本的 experimental 動態工具能力，經同一權限與面板核心；不支援的 thread 不會自動取得能力。人員問題、批准、秘密輸入、失敗和完成分開處理。

## 資料、生命週期與驗收

正式資料與主／KWS 獨立環境位於 `~/Library/Application Support/Maltose/`。Memory 與 KDB 分離，使用者原始文件仍是 source of truth；設定與模型引用不依賴 Finder 的目前目錄。資料遷移及回復見 [正式遷移報告](../verification/maltose-data-migration-report.md)。

主 runtime 與 Codex 各有程序守護及清理確認。原生 Docker 執行另有持久資源登記，重啟先核對／清理，不能盲目重送不確定的寫入。架構決策見 [ADR 005](../decisions/005-unified-maltose-runtime.md)，驗證範圍見 [Codex 生命週期](../verification/codex-lifetime-report.md) 與 [原生 Docker 生命週期](../verification/native-docker-lifetime-report.md)。

舊 Host／MUP／MyAgent 整合文件保留為歷史與相容資料，並非目前 App 的啟動方式。現行啟動、環境與封裝入口見 [README](../../README.md)。build 14 的 [認證故障驗證](../verification/codex-auth-failure-report.md) 與 build 11 的 [桌面驗收](../verification/build11-desktop-acceptance.md) 分別保留其版本範圍；最新套件的正式 GUI、真人語音及完整 App 故障驗收仍待完成。
