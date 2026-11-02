# 共用面板狀態與 Agent 介面

基準：`1195340`（本次修改前 HEAD，工作樹乾淨）。本次沿用 AppKit／SwiftUI 工作區，新增程序內 JSON 指令入口及本機模擬。這是程序內介面的初始基準。2026-11-01 已加入受管理 Python runtime 的私有 stdio adapter；初期接線證據見 [原生 runtime 驗證](../verification/native-runtime-integration-report.md)。現行主 Agent／Codex 的責任與資料邊界見 [架構入口](README.md)，最新範圍及未完成驗收以 [產品整合計畫](../../plans/maltose-unification-and-codex.md) 為準。舊版 MUP／MyAgent 文件不代表目前 App 的執行狀態。

## 既有狀態與入口盤點

| 層級 | 狀態擁有者 | UI 操作入口／本次使用方式 |
| --- | --- | --- |
| 面板生命週期與窗口 | `WorkspaceWindowManager.catalog/panels/assignments/roots/windows` | `addPanel`、`closePanel`、`selectPanel`、`togglePanel`、`highlightPanel`；新增共用 `movePanels`、`setWorkspaceMode` |
| 每個窗口的排列 | `WorkspaceRootView.state: WorkspaceLayoutState` | `reconcile/select/highlight/toggle/repositionPanels`；保留既有排列、主面板、選取及形象固定位置 |
| 全局視口 | `WorkspaceRootView` | `setGlobalZoom`、`scrollGlobalGrid`，沿用既有縮放／捲動邊界 |
| 各面板內容 | `GlassPanelView` 保留各種 model 與 content view | UI 與 Agent 操作相同的 `ConversationHistoryModel`、`CSVLineChartModel`、`ImageGalleryModel`、`BrowserPanelModel`、`FlowchartCanvasModel`、`WorkspaceSampleContentModel` |
| 形象 | `AgentIdentityAnimationModel.shared` | 共用既有 preset，新增 `setState`；明確設定狀態時停止示範動畫 |
| 感知 | `WorkspaceWindowManager.getUserView()` | `1195340` 已實作；⌥⌘V 原本只有唯讀擷取，本次擴充指令模擬 |
| 互動示範 | `runAgentInteractionTest()`／底部 `test` | 保留原本還原狀態的動畫示範；完整 JSON 指令模擬使用 ⌥⌘V 與新增自動測試 |

面板內容沒有搬移或重建。原生拖曳與 Agent 跨窗口移動都使用 `movePanels`，再由既有 `synchronize` 更新歸屬與排列。全程在 `MainActor` 上操作；不維護 Agent 私有的平行狀態副本。

## 程序內合約

入口：`manager.agentInterface.handle(request)`，或 `await manager.agentInterface.handleJSON(json)`。Swift 合約定義在 `WorkspaceAgentInterface.swift`。指令 schema 為 1，視圖 snapshot schema 為 2，兩者獨立版本化。

```json
{
  "schemaVersion": 1,
  "requestID": "call-1",
  "command": {
    "focus_panel": { "panelID": "chart" }
  }
}
```

`command` 必須只有一個 case，以 case 名稱為 key，具名參數為 value。無參數指令仍使用空物件，例如 `{"get_user_view":{}}`。必填參數的型別由 Codable 驗證；optional 的 `screenID`、`row/column`、連線 `label` 可以省略。`schemaVersion` 與 `command` 必填。`requestID` 選填，只用於回應關聯，沒有去重語意。

```json
{
  "schemaVersion": 1,
  "requestID": "call-1",
  "ok": true,
  "result": {}
}
```

建立面板會在 `result.panelID` 回傳穩定 ID，建立流程節點回傳 `result.nodeID`。`get_user_view` 將 snapshot 放在 `view`，`list_capabilities` 回傳目前面板的 `capabilities`（指令名稱、panelID、完整可編輯 request 範例）。寫入後可再呼叫 `get_user_view` 檢查結果。建立類型和 snapshot `kind` 都使用 `WorkspacePanel.Kind` 的 raw value。

失敗回傳 `ok: false` 與 `error: {code, message}`：`invalid_request`、`unsupported_version`、`not_found`、`unsupported_operation`、`invalid_argument`、`invalid_state`、`panel_limit`、`unsaved_changes`、`busy` 、`operation_failed` 或 `encoding_failed`。型別／狀態驗證先於內容修改。瀏覽器導航成功表示已提交網址；頁面載入與 WebKit 操作非同步完成，載入結果仍由原生 model 顯示。

## 操作範圍

| 指令 | 語意與限制 |
| --- | --- |
| `get_user_view` / `list_capabilities` | 讀取目前 UI／列出每項操作的完整 request 範例 |
| `read_panel(panelID)` | 讀取指定面板的有界內容，不切換畫面或放大面板 |
| `create_panel(kind, screenID?)` | 類型：`canvas/notes/chart/table/conversationHistory/document/imageGallery/browser/agentIdentity`。形象與聊天單例，關閉後可重建；`agentCoreTest` 仍是獨立測試窗 |
| `close_panel(panelID, discardChanges)` | 關閉實例；流程圖未儲存時要求先儲存或明確丟棄 |
| `select_panel(panelID, extending)` | 沿用原生 highlight／⌘多選切換語意；保留目前模式。面板模式中須先回到 grid 才能選取形象 |
| `focus_panel` / `toggle_panel` | 選為主面板／切換放大；形象不支援放大 |
| `set_mode(screenID, mode)` | `grid/focused/sidebar`；空窗口不能放大，主面板必須支援放大 |
| `move_panels(panelIDs, screenID, row?, column?)` | 同窗口重排或跨窗口搬移；同批必須來自同一窗口且不能重複。row/column 一起指定或一起省略，從 0 起算；row ≤ 1000，column 在當前欄數內。形象須單獨重排；移動以形象為首的批次至其他窗口時使用 grid |
| `grid_viewport(screenID, zoom, scrollOffset)` | grid 模式使用絕對縮放與捲動量，沿用原本 clamp |
| `conversation_select_session(panelID, sessionID)` | 沿用 UI：僅 focused 聊天允許切換 session；snapshot 提供 session IDs |
| `notes_set_text(panelID, text)` | 直接更新既有編輯 model；編輯器與 snapshot 同步讀到內容 |
| `chart_load_csv` / `chart_open_csv` / `chart_set_series` / `chart_set_bands` / `chart_viewport` | CSV 字串或本機檔案、來源名、線條名稱、填色線對與透明度、X 軸絕對 zoom/pan；未知線名與無效線對回錯誤，沿用既有 clamp |
| `image_add_url` / `image_add_file` / `image_select` / `image_expand` / `image_collapse` / `image_viewport` | HTTP(S) 圖片或本機圖片檔、從 0 起算索引、展開／收合、絕對 zoom/pan；展開前先放大面板，設定視口前先展開圖片 |
| `browser_navigate` / `browser_control` | 沿用網址／搜尋驗證；control action：`back/forward/reload/stop/offlineTestPage`，無歷史時返回／前進會拒絕；離線頁供模擬使用 |
| `flowchart_add_node` / `flowchart_update_node` / `flowchart_select_node` / `flowchart_connect` / `flowchart_delete_selection` / `flowchart_viewport` | 沿用節點、連線、選取與視口 model；節點 ID 不存在、自連、重複連線回錯誤。主面板 snapshot 的 `nodesByID` 提供結構化 ID／文字／類型／座標 |
| `flowchart_new` / `flowchart_open` / `flowchart_save` | 沿用既有檔案格式與驗證；開啟與新建有未儲存防護。檔案需 `.maltoseflow.json` 絕對路徑；儲存可覆寫指定檔案 |
| `identity_set_state(panelID, state)` | `idle/listening/thinking/speaking/executing` |
| 文檔與資料表 | 沿用現有唯讀內容；可感知、建立、選取、放大、移動及關閉，沒有虛構內容寫入能力 |

檔案對話框、複製至剪貼簿、網頁內部任意 DOM／媒體控制及刪除磁碟檔案仍由原生 UI 提供，本次沒有將它們擴成 Agent 工具。程序內合約是供可信的本機呼叫端使用；原生 runtime 使用下述 adapter，不能直接把此物件當作公開網路 listener。

使用者拖曳期間或底部 `test` 示範播放中，Agent 寫入回 `busy`，避免與預覽／還原狀態交錯；唯讀呼叫仍可使用。

## 原生 runtime adapter

App 在初始化握手提供 `WorkspaceAgentToolDefinitions` 的 36 個具名工具與 JSON Schema，Python adapter 驗證參數，再經 `panel.call` 回到相同的 MainActor 操作核心。`get_user_view`、`read_panel` 等私有內容讀取保留現有已驗證身分要求；原生輸入來源不等同聲紋或使用者身分已驗證。

原生傳輸的四種檔案操作必須經 FileService：讀取先核對 root、權限、保護路徑、連結及大小，再傳入內容；App 不代替 Agent 開啟任意路徑。流程圖儲存先匯出文件快照，再由 FileService 核對寫入權限與 expectedSHA256，最後確認精確文件／版本。外部修改會拒絕覆寫，儲存途中新增的編輯保持 dirty，新開的文件不會被舊確認重新綁定。原生內部傳輸模式不暴露成模型工具。可信本機模擬仍可直接測試原本的檔案入口。

程序內 `requestID` 只供關聯；原生傳輸另以同連線的 ID 與參數比對，合併執行中重複請求，快取最近 512 個完成結果。同 ID 不同參數會拒絕連線，避免錯誤執行。重啟後不盲目重送寫入；快取不構成跨程序的永久執行紀錄。

## 視圖摘要規則（snapshot v2）

- 以每個窗口的工作區模式判斷內容詳略；macOS 原生全螢幕由獨立的 `isNativeFullscreen` 表示，不與「面板全屏」混用。`mode` 保留 UI 中文名稱，新增 `layoutMode: grid/focused/sidebar` 供指令使用。
- `focused/sidebar`：每個窗口的主面板 `detailLevel = content`，回傳既有內容摘要；其他面板均為 `summary`，包含標題、類型、選取狀態、presentation、能力與少量內容中繼資料。
- `grid`：面板全部為 `summary`，依幾何位置區分 `globalCell/offscreen`。可用 `focus_panel` 取得某個面板的內容摘要。
- 側欄縮圖不讀取整份文件或對話，離開側欄可視範圍的縮圖標為 `offscreen`；隱藏的 browser 不執行 JavaScript 擷取。
- 文檔沿用最多 32 區塊摘要、聊天最多 12 則訊息、筆記最多 4000 字；流程圖最多 100 節點／100 連線，並提供 `contentIsTruncated`。網頁使用目前 DOM 視口的文字／選取／媒體資訊。
- 這是語意摘要。文檔與聊天尚未追蹤逐行捲動可見範圍，流程圖也未做逐節點視口裁切；不宣稱是截圖或逐像素遮擋分析。WebKit 讀取期間使用者仍可能操作，因此 snapshot 不是跨所有視圖的原子交易。

## 逐項模擬

1. 建置並開啟預覽 app，使用「面板 → UI 感知測試…」或 ⌥⌘V。
2. 原本的「發送 get_user_view」仍可直接讀取 JSON。
3. 從「載入操作範例」選擇操作，修改 JSON 的目標與參數，按「執行指令」。它會透過 `handleJSON` 套用到目前工作區並顯示結構化結果；建議先建立測試面板。需要前置狀態的指令會回明確錯誤，先執行 focus／expand 等操作即可。
4. 自動測試 `WorkspaceAgentNativeTests` 使用相同 JSON 入口逐項執行全部 35 種指令，並比對 capability 名稱集合，避免新增能力卻漏測。測試另行建立自己的 manager，結束關閉所有測試窗口；只在暫存路徑寫測試流程圖。

```sh
./scripts/swift-test.sh
MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh
./scripts/package-workspace-preview.sh
```

GUI 測試需要可存取 WindowServer；跨螢幕測試需要第二個螢幕。結果見 [本次驗證報告](../verification/workspace-agent-interface-report.md)。
