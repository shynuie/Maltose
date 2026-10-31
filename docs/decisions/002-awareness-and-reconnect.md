# ADR 002：Awareness 的隔離、時間與重連

- document revision 只因 ui.render / ui.patch 增加；context revision 按 principal 計算。未授權代理的活動不增加其他代理的 revision。
- native focus 由 AppKit / WebView first responder 蒐集；renderer 的 selection 只能細化目前該表面的焦點。bridge 綁定 surface + 每次 WebView 的 epoch，拒絕舊實例、舊文件版本與倒序 sequence。
- context 是結構化資料；不使用截圖、鍵盤紀錄、全域 Accessibility 或其他應用程式內容。
- 預設 freshness 門檻 5000ms；reference resolver 排除過期候選。僅依 explicit ID / focus / selection / interaction / visible nodes 排序，回傳 evidence、age 與 ambiguity，不執行語意推斷或破壞性操作。
- 每個訂閱 128 事件，超限丟棄並送 context.stale，要求完整 snapshot。每個 principal 最多 16 訂閱；斷線取消；SDK 重連重新訂閱再讀 snapshot。
- 權限更新終止該 grantee 全部訂閱，清除未送出事件與讀取快取，傳不含 surface 身分的 permission_changed 終止標記。每次事件送出重新檢查 scope。
- summary 僅標題、owner、種類、可見狀態與版本。詳細選取、viewport、文件、layout、interaction、events、data 各為明確 scope；本機使用者才可授權。
- zoom 是明確使用者偏好，獨立存入 userOverrides；重啟可還原 zoom，但 transient selection 與 active focus 不還原。資料 registry 記憶體保存；斷線/重啟標記 stale。
- 視窗座標與 screen_id 使用 Host 的 NSScreen/NSWindow，還原時限制於現存螢幕可視範圍。
