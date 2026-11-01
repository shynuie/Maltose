# Maltose 根目錄重新定位

日期：2026-11-01。實體目錄、正式開發設定與開發環境已完成重新定位；桌面專案附件與最終 Finder 驗收仍待完成。

## 實際變更

- 實體主倉庫為 `/Users/Marvin/Workspace/Maltose`。原 `/Users/Marvin/Workspace/Maltose_UI` 保留為指向新目錄的暫時別名，供目前聊天及歷史連結續用；產品設定及新開發環境使用新路徑。
- 搬移採相同 volume 的排他 rename，目的地已存在時不覆寫。搬移前保存 Git HEAD、工作樹狀態及 413 個來源檔案的聚合 hash；搬移後全部相符。未提交修改、刪除、未追蹤檔案及忽略的資料均保留，沒有再次匯入 MyAgent 或正式資料。
- 正式設定只將 `taskbrain.codex_cwd` 改至新根目錄，其餘解析後設定完全相同。完整原設定及分階段收據留在 Application Support 的私有 `migrations/project-relocation-v1/`，不加入 Git 或 App。
- 搬移同時取得 native runtime 與產品 task store 的 kernel lease，避免與 App／Agent 寫入競爭。正式 Codex task store／另選專案紀錄當時不存在；工具遇到已有任務或額外需改寫的 operational paths 會停止，沒有以字串取代改寫 Codex 歷史或個人記憶。
- 原開發 venv 留在忽略的 `.cache/unification/development-environments/pre-relocation/`，套件版本清單也留有私有收據。依原鎖檔離線重建 Python 3.12.10；117 個套件名稱／版本與原環境完全相同，editable 路徑及 CLI 入口均使用新根目錄。App 專用 main／KWS 環境及模型沒有因更名重建或升級。
- Git 自行識別新實體路徑，HEAD 仍為 `28dded81596402410812954f623e426631a6ff6b`；沒有新增或重設提交，也沒有 linked worktree 需要修復。

## 工具與驗證

`runtime/dev/tools/relocate_project.py` 預設僅盤點，明確加上 `--apply` 才執行。已保存 receipt 的中斷操作以原目錄 device／inode 續做；設定或來源被修改、目的地衝突、符號連結、其他資料寫入者或任務需另行遷移時拒絕覆寫。這是一次性的開發目錄工具，不是重新執行 M4 資料匯入的入口。

九項隔離測試涵蓋唯讀盤點、原始／忽略內容保全、目的地競態、兩種 kernel lease、搬移後中斷恢復、設定並行修改、未知 operational path、既有任務及惡意符號連結／收據。搬移前完整 Python 387 項全數通過。

搬移後新環境完整 Python 387 項，0 failures／errors／skip，包含五項實際 Docker 整合。新根目錄配合全新 Swift 編譯快取，完整 137 項、0 failures、20 skip；其中 15 項需桌面、另五項真實模型本輪未重複執行。搬移前 build 9 的真實雙模型及背景工作證據保留於 [成果理解與清理報告](main-review-and-cleanup-report.md)，不將本輪未啟用的服務旗標說成已執行。

建置腳本支援 `MALTOSE_BUILD_DIRECTORY`，便於使用全新快取驗證根目錄變更，不必刪除舊編譯產物。新 trial package 為 **0.7.0／build 10**，由新根目錄及新快取封裝。暫時移除舊路徑別名時，141 個 bundle／125 個 runtime 檔案的來源比對、strict 簽章、獨立 cwd 匯入與兩項既有憑證值掃描均通過，之後立即還原別名。該檢查沒有啟動正式 Agent／麥克風，不能代替 Finder 驗收；詳見 [build 10 結果](relocated-build10-results.json)。build 9 已留私有備份。

## 回復與剩餘工作

原 MyAgent 與 M0 備份、M4 正式資料遷移收據均保留。若需撤回目錄更名，先退出 App／Agent／所有建置，核對新實體目錄及舊別名的身分，移除自己建立的別名，將實體目錄搬回，再依私有備份只復原對應設定；開發 venv 須在回復後的路徑重新建立。若更名後已有新修改或設定，不能直接重放舊快照覆蓋。

目前 Codex 的本機專案「麥芽糖UI」仍記錄舊路徑，且桌面鎖定，尚無法在 App 內更新專案名稱及附件位置。當前聊天的一般執行沙箱不接受已成為 symlink 的舊 writable root；這不是自動批准拒絕，後續工作已明確使用新 cwd 及符合目標範圍的升級執行，沒有修改 Codex 全域設定。桌面可用後需完成專案位置及目前聊天執行環境的重新定位，再移除不再需要的別名。

最終 Finder 冷啟動／再次開啟／退出、全螢幕及真人語音驗收仍待解鎖；本報告只證明目錄與環境重新定位，不代表整體 M4／M7 完成。
