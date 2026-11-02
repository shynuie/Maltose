# 主 Agent 成果理解、交接邊界與背景工作清理

日期：2026-11-01。狀態：部分驗收完成，整體目標仍進行中。

## 已實作的流程

- 主 Agent 使用原設定的模型，依有來源的目標、追加需求、成果、測試與差異整理下一步問題。這是暫停中的唯讀模型呼叫：不載入個人 Memory、舊對話／計畫或面板內容，不提供工具，不恢復自主動作。
- 新要求保留於獨立摘要欄位，避免大量工具輸出擠掉需求；包含 JSON 跳脫後的總長度上限。模型回傳必須符合摘要／新要求／確認問題的結構，工具呼叫與不合格回應直接拒絕。
- 確認稿先持久化，再送往聊天；重試重用同一 ID 與已保存結果。生成與聊天保存分開記錄，只有原生聊天保存成功才記為 accepted。更新的使用者要求會使舊確認失效；交回時主 Agent 可看到先前的確認稿及送達狀態。
- 本機鍵盤可要求主 Agent 委派已選取專案的開發工作，仍保留 unknown 身分，不能因此取得個人 Memory。未辨識語音及 Web 輸入沒有此例外；開發討論本身不表示授權實作。
- 直接互動的普通問題可由原輸入欄回答，沿用同一回合。秘密問題使用原生安全輸入視窗；一般輸入欄在寫入 outbox／聊天前拒絕答案，保留草稿；安全視窗回應在產品紀錄內遮蔽。
- 語音任務的其他說話者不能藉 `@maltose` 交回目前任務；訊息保留待人員確認。Codex 失敗原因也同步給主 Agent，不因缺少最終回答而遺失。

## 背景工作

Codex 使用已安裝版本支援的 experimental `thread/backgroundTerminals/list`／`clean`，僅清理目前連線附著的 Maltose 任務。分頁、重複 ID 與格式均驗證；清理回覆後再次查詢，確認清單為空才保存成功收據。正常交回與 App 退出均走此流程；沒有將模型提供的主機 PID 當作任意終止權限。

實測包含獨立 process group 的受控子程序、清理失敗時保持 Maltose 暫停，以及真實 Codex 終端建立的長時間 Python 工作。後者在交回後由系統查核 PID 已退出，再恢復同一 thread／worktree 建立第二個背景工作，驗證 App 退出清理。突然崩潰及失聯的完整清理矩陣仍未驗收。

Docker timeout 原本只結束 client，現在另外查詢 daemon，以唯一名稱及 execution ID 標籤取得完整容器 ID，移除並重查。daemon 不可用、ID 不符或清理未確認會回報失敗。實測 TERM-ignoring 父子程序的 heartbeat 停止、自己容器消失，獨立測試容器持續運作。沒有使用 prune 或全面停止容器。

本機沿用 Docker Desktop 4.12.0／Docker 20.10.17 及既有 python:3.12-slim 快取，測試使用 `--pull never`，未升級或下載映像。已啟動既有 Docker engine；其上另有獨立容器運作，因此保留 engine，不停止其他容器。指定 Maltose execution 標籤的清理查核為空。

## 驗證證據

- 歷史完整版本：Swift 133 項、0 失敗、15 GUI skip；Python 377 項、0 失敗、0 skip（包含五項真實 Docker 整合）。這些結果早於本輪新增的輸入／送達邊界修正。
- 真實雙模型流程已通過：既有 Main 模型接受自然語言開發要求並委派，真實 Codex 修正 calculator，使用者直接追加 docstring，Codex 保持三項測試通過，主 Agent 理解追加要求並確認新意圖。工作與資料全部使用隔離 fixture，原專案不變。
- 本輪秘密／公開問題、失敗同步、其他說話者控制及確認保存的 Swift 聚焦五項通過；Python review／collaboration 聚焦通過。公開問題首次失敗為 fixture 將合法的並行 account/read 誤當答案，修正 fixture 後通過，未將此歸因為產品協定問題。
- 新增的明確多任務選取測試核對 task／thread／worktree 對應、不跨對話選取、不在其他任務執行時切換，也不因觀看歷史成果而產生新指令或完成確認。它是協調層測試，原生選單互動仍須桌面驗收。
- 第一次完整 Swift 136 項發現同一確認在 UI 保存後重放時，送達 metadata 造成模型快取 fingerprint 衝突。已將送達資訊與模型請求分開，重放不降級 accepted；三項針對性收據／交回回歸通過。失敗後重試也清除已失效的舊錯誤，四項選取／恢復聚焦通過。
- 最終完整 Swift 137 項、0 failures、15 GUI skip，包含真實雙模型閉環、同 thread／worktree 恢復及實際 Codex 背景終端清理；耗時 132.317 秒。最終完整 Python 378 項、0 failures／errors／skip，耗時 19.883 秒。review／collaboration 聚焦 22 項及收據修正後 review 八項亦通過。
- Git 修改與未追蹤來源共 111 個檔案已掃描，沒有私有設定／資料庫／環境／模型目錄或兩項既有服務憑證值；未輸出憑證。`git diff --check` 通過。此檢查涵蓋目前工作樹，不表示已提交或完成發行。
- 發行包曾重建為 0.7.0／build 8，141 個 bundle 檔案、125 個 runtime 檔案，當時與來源逐檔 hash 相符；strict 簽章、獨立 cwd 匯入及兩項既有服務憑證值掃描通過。0.6.0／build 7 保留於忽略的私有備份。新增修正後必須重新封裝及查核，不能沿用此結果宣稱目前來源已部署。
- 修正後已重建 **0.7.0／build 9**，141 個 bundle／125 個 runtime 檔案；來源逐檔 hash、strict 簽章、獨立 cwd 匯入與兩項憑證值掃描全部通過。build 8 另保留私有備份；build 9 未啟動正式 Agent 或使用麥克風，Finder 驗收仍未完成。可核對的來源及執行檔 hash、測試旗標與未驗證項目見 [build 9 結果](main-review-build9-results.json)。

可重現入口：

```sh
MALTOSE_CODEX_TESTS=1 MALTOSE_CODEX_LIVE_TESTS=1 MALTOSE_MAIN_LIVE_TESTS=1 ./scripts/swift-test.sh
MALTOSE_RUN_DOCKER_INTEGRATION=1 PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests
./scripts/package-maltose.sh
runtime/.venv/bin/python scripts/verify-maltose-package.py --python "$HOME/Library/Application Support/Maltose/environments/main/bin/python" --credential-file "$HOME/Library/Application Support/Maltose/.env"
```

真實服務測試沿用現有帳號及模型設定，必要時產生服務用量；報告不含金鑰、個人資料或完整模型對話。原生桌面驗收另需 `MALTOSE_GUI_TESTS=1` 及可互動的已解鎖桌面。

## 尚未完成

- 目前 Mac 鎖定，原生控制工具已明確回報無法解鎖；本輪不反覆執行全螢幕。此狀態解釋目前無法驗收，不能證明先前間歇失敗都由鎖定造成。
- 新版 Finder 冷啟動／再次開啟／退出、原生全螢幕與跨螢幕、真人語音／身分／裝置切換及秘密問題的語音端到端矩陣。
- 多任務人員選取、動態面板操作中斷／重啟、突然崩潰及程序失聯的完整故障矩陣。
- 最終根目錄 Maltose_UI → Maltose、工作環境與舊路徑重新定位、舊日常入口退役、完整 Git／資料／發行交付查核。

重新定位盤點：最終目錄尚不存在；受管理設定仍有 `taskbrain.codex_cwd` 指向舊根目錄，尚無另外保存的正式開發專案選取紀錄。Codex App 的本機專案「麥芽糖UI」目前仍附著舊根目錄。更名需一併更新這些位置及開發環境的 editable 入口，不以舊目錄 symlink 作為產品的長期依賴。

完整目標及驗收依 [主計畫](../../plans/maltose-unification-and-codex.md)，本報告不取代 M7。

後續補充：實際 server 群組突然退出時，HUP-resistant 背景工具原先殘留，已以獨立守護及可信 EOF 收據修補。單獨 server 崩潰而宿主仍存活，以及工具執行中的宿主崩潰均通過；同 thread 恢復未重送工作。最新結果與範圍見 [生命週期報告](codex-lifetime-report.md)，本頁前段 build 9／10 結果保留為歷史。
