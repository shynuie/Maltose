# 面板 Agent 共用介面驗證

日期：2026-11-01（Asia/Shanghai）。實作基準為 `1195340 Add user view awareness test window`，開始時 HEAD 與該提交一致，工作樹乾淨。

## 完成內容

- 沿用 `WorkspaceWindowManager`、`WorkspaceLayoutState`、`GlassPanelView` 持有的各面板 model，新增 MainActor 上的程序內 Agent JSON 介面；沒有重建面板 UI 或另設 Agent 狀態副本。
- 35 種型別化指令：感知與能力查詢、生命週期、選取／放大／模式／多選移動／重排／全局視口、聊天 session、筆記、CSV 檔案或字串／線條／填色／視口、圖片 URL 或檔案／瀏覽／縮放平移、網頁基本控制、流程圖編輯與檔案、形象狀態。
- 共用原生拖曳與 Agent 的跨窗口移動邏輯；保留 content view 與 model 身分、來源選取修剪、形象拖曳位置。
- `get_user_view` 升至 snapshot v2，明確區分原生全螢幕與工作區模式。主面板回傳內容摘要，grid／側欄縮圖／隱藏面板回精簡資訊；流程節點提供結構化 ID／類型／文字／位置。
- ⌥⌘V 保留原本的感知按鈕，新增操作範例、JSON 編輯與執行結果。使用與 Agent 相同的 JSON 入口，執行時會更動目前工作區。
- 拒絕錯誤類型、未知面板／節點／線條、無效索引／數值／網址／移動位置、不支援的面板能力及未處理的流程圖變更；拖曳／互動示範中回覆 busy。
- README 與現行架構文件補齊入口和限制，舊 Host／MyAgent 文件加上歷史標示。

## 測試結果

| 驗證 | 結果 |
| --- | --- |
| 修改前 `./scripts/swift-test.sh` | 41 項：37 通過，4 項桌面測試依預設跳過，0 失敗 |
| 最終 `MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh` | **49 項通過，0 失敗，0 跳過** |
| 新增測試 | 2 項合約測試、6 項原生整合測試；35 種指令全部經 JSON 往返模擬，覆蓋集合與 capability 名稱一致 |
| 跨螢幕 | 實際兩個 WindowServer 螢幕執行；確認多面板搬移、原物件保留、來源／目標選取，以及原生形象拖曳位置 |
| 既有 UI 回歸 | 原生全螢幕、面板內容保存、拖曳、30 面板捲動與窗口 chrome 測試均通過 |
| Release 封裝 | `./scripts/package-workspace-preview.sh` 通過，包含 ad-hoc 簽章與 strict 驗證；已更新 `dist/Maltose Workspace Preview.app` |
| 格式檢查 | `git diff --check` 通過 |

完整測試輸出：[workspace-agent-tests.log](workspace-agent-tests.log)；封裝輸出：[workspace-agent-package.log](workspace-agent-package.log)。桌面測試在可存取 macOS WindowServer 的本機環境執行；受限環境中不將「無螢幕而跳過」視為 GUI 已通過。

測試以獨立 manager 建立並關閉自己的窗口，CSV／圖片／流程圖檔案僅寫暫存路徑並清理。測試驗證：Agent 更新原有 model 後 UI 仍保留同一個 content view；UI model 的修改也會由 Agent 的 get_user_view 讀回；無效指令不造成部分寫入；有效但超出整數範圍的流程圖座標仍可安全編碼；形象／聊天關閉後可重新建立且不重複。

## 範圍與限制

目前交付的是程序內合約、本機模擬與可供 adapter 呼叫的入口，尚未連接真實 Agent runtime，沒有恢復舊版 Host、傳輸、配對或授權服務。文檔／資料表沿用現有唯讀能力；未新增任意 Markdown 載入、任意 DOM 操作、媒體控制或 Agent 刪除磁碟檔案。

感知是語意摘要：網頁有 DOM 視口擷取，文檔／聊天尚未追蹤逐行捲動可見內容，流程圖未逐節點裁切。外部網站的真實網路／影音載入不是本輪驗收範圍；瀏覽器模擬使用既有離線測試頁。舊 `tests/ui_runtime_test.py` 依賴已移除的 `maltose_runtime`，不在現行 Swift Package 測試 target 內，本輪沒有將舊 Host 測試當作目前 UI 的驗證。

詳細合約與操作前置條件見 [共用面板介面](../architecture/workspace-agent-interface.md)。
