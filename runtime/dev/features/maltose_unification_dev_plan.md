# Maltose 產品整合

狀態：in_progress。最後更新：2026-11-01（人員已解鎖，先完成新增聊天捲動需求）。

詳細規格與驗收以 [主計畫](../../../plans/maltose-unification-and-codex.md) 為準。決策見 [ADR 004](../decisions/ADR-004-unified-maltose.md)。

2026-11-01 後續追加的任務銜接、資訊輸出、簡短語音與「預設新增面板、明確要求才更新」另見 [新 feature plan](task_workflow_and_presentation_dev_plan.md)。目前僅規劃，不改變本頁既有完成／未完成驗收。

- [x] 保全原始歷史、未提交修改與私有資料，執行原生／Python 基準。
- [x] 以子目錄匯入來源歷史，按校驗清單保留現有工作，來源倉庫不變。
- [x] 改名為 `maltose` 套件與公開命令，保留舊設定讀取相容。
- [x] 按現有 lock 重建主 Python 3.12 與 KWS Python 3.10 環境。
- [x] 修正三項既存測試缺少已驗證身分的前提，補上未驗證時的拒絕檢查；不改正式政策。
- [x] 新設定優先、舊設定 fallback、CLI override 與相對路徑測試。
- [x] 原生 stdio 入口、App supervisor、就緒／逾時／重試與 kernel 單實例 lease。
- [x] 既有聊天／輸入串流、事件 journal、面板工具 schema、檔案權限 adapter 及人員批准橋接。
- [x] 以實際子程序驗證既有 TaskBrain 呼叫面板 model；文件 watcher 與資源失敗／退出清理。
- [x] 原生啟動以資料方式載入 owner-only 私有 `.env`，限定服務憑證名稱，不執行 shell；既有來源檔案解析驗證通過，未輸出值。
- [ ] 最終版本的啟動、退出、崩潰及協作程序恢復完整矩陣。
- [x] 正式資料與 App 專用主／KWS 環境切換，逐筆驗證既有狀態與原文。
- [x] Finder 啟動、真實模型／語音對話及共享面板操作；修正實測發現的 KWS 診斷輸出污染／訊框問題。
- [x] 實體根目錄 Maltose、正式開發設定與離線重建的開發環境；413 個來源檔案保全及 117 個套件版本核對。
- [ ] Codex 桌面專案／聊天執行環境重新定位、共用面板完整恢復矩陣及最終啟動回歸。
- [ ] Codex 委派、@codex 交接與完成後主動確認。
- [x] Codex stdio／任務持久化／來源與送達狀態核心；具名回合 steering、中斷、跨程序核對及 workspace baseline／diff。
- [x] 實際 Codex 0.155.1 的隔離程序握手、開始／中斷回合、退出與恢復；使用 localhost fixture provider，未驗收真實模型開發。
- [x] 共用 autonomy gate／活動 drain／舊工作 held、native pause／resume／snapshot、收件人前綴解析及來源保全核心；未啟用正式 composer 路由。
- [x] Native kernel lease 涵蓋背景 worker interpreter shutdown；中斷串流收尾、工具結果保全及 verification scope 隔離。
- [x] SessionCoordinator 接到原 composer／journal，持久 conversation、收件人、pending／deferred input、workspace、Codex 及完成後固定確認問句；隔離程序／store 重啟恢復。
- [x] controller-only durable routed input／專案選取／觀察服務，delegate_to_codex 依當次已驗證語音或本機文字來源授權選取的開發專案；本機文字仍 unknown，不能取得 Memory。舊主 Agent 批准也受 gate 保護。
- [x] Codex 原生批准／問題來源紀錄、秘密回答遮蔽、開始／停止競態及 UI 保存失敗恢復；正式 UI／服務仍待完整驗收。
- [x] Codex 模型分頁清單、自己的選擇、任務固定模型與不可用選擇的明確恢復；不修改全域設定。
- [x] 依本機 0.155.1 experimental 合約接入全部 36 個共用面板工具，持久去重／不確定結果、controller lease／FileService 及原生面板核心。
- [x] 以真實 Codex 模型完成隔離 calculator 修正／測試及原生筆記面板建立／寫入；不改正式專案，沒有自動批准。
- [x] 語音交回使用 runtime 單次驗證證據，排隊後重查，scope 世代／期限／來源／重送拒絕；原生文字仍 unknown。
- [x] UI 讀取的人員授權綁定目前 task／runtime／paused lease，可撤回；不取得 Memory 身分或額外檔案權限。
- [x] 主 Agent 入列／接納分開，轉交競態保留待確認輸入，journal 同步／跨重啟序號及未確認委派恢復拒絕。
- [x] 真實 Main 模型理解追加需求並產生確認問題，唯讀整理不提供工具／Memory；持久快取、過期問題拒絕、生成／聊天保存分開記錄。
- [x] 真實 Main → 真實 Codex 修正 → 使用者追加 docstring → 三項測試 → Main 確認新意圖的完整隔離流程。
- [x] Codex 真實背景終端 list／clean／重查；交回與 App 退出清理，未確認則維持暫停，尚未涵蓋所有突然崩潰。
- [x] 秘密問題拒絕一般輸入欄落盤，原生安全視窗回應遮蔽；公開問題在原對話框延續同回合；失敗原因同步。
- [x] 語音任務的其他說話者不能以 @maltose 交回；送達狀態在確認保存後才持久記錄。

先前協調層驗證（歷史）：collaboration Python 聚焦 8 項通過；完整 Python 361 項無失敗、5 Docker integration skip；完整 Swift 桌面及本機 Codex 113 項通過、無 skip。當時 Codex CLI 以 localhost fixture provider 驗證程序與恢復，尚未驗收正式帳號／真實模型開發。最初並行跑的 EOF／桌面時序失敗及其後重跑結果均保留在 [協調層報告](../../../docs/verification/session-coordination-report.md)；不以重跑通過宣稱已根治。先前 [交接控制報告](../../../docs/verification/autonomy-handoff-report.md) 及 [Codex 核心報告](../../../docs/verification/codex-integration-report.md) 保留歷史證據。

歷史 M4 證據：原生桌面 Swift 69 項全數通過、無 skip；正式 App 觀察到既有模型的真人語音多輪對話。M1 的 KWS 既有模型 READY／health／靜音 PCM／reset 證據保留。這些證據不替代目前尚未完成的 GUI／協作／真實 Codex 模型驗收。

前段理解交接的歷史結果：Python 378 項，0 failures／errors／skip，包含實際 Docker；完整 Swift 137 項、0 failures、15 GUI skip。新增邊界、明確任務選取、失敗重試與確認收據聚焦均通過。先前完整回歸發現送達 metadata 造成快取衝突，已修正並驗證重放；不抹除該次失敗。更早的完整桌面 124 項曾在同一全螢幕案例有七個失敗斷言，保留歷史紀錄；目前 Mac 鎖定，不能以非 GUI 通過取代桌面驗收。真實 Main／Codex 雙模型閉環與背景終端清理已有正式服務證據，見 [最新報告](../../../docs/verification/main-review-and-cleanup-report.md)。

下一步：完成全螢幕啟用、動態工具中斷／重啟、人員互動／真人語音、多任務原生操作及突然崩潰清理矩陣；再完成根目錄重新定位與 M7。0.7.0／build 9 已包含輸入／送達修正，來源逐檔比對、簽章、獨立匯入及私有資料檢查通過；新版正式資料 Finder 驗收仍待解鎖。正式切換與限制見 [遷移報告](../../../docs/verification/maltose-data-migration-report.md)；一般真人語音成功不取代逐項身分／中斷／裝置切換測試。

目錄重新定位證據：完整 Python 387 項無失敗／skip；新根目錄與全新快取 Swift 137 項、0 失敗、20 skip（15 桌面、五項未啟用的真實模型）。實體根目錄已為 Maltose；原 Maltose_UI 為暫時別名，目前聊天仍綁舊 writable root，一般沙箱不支援此別名，後續命令使用新 cwd 及明確的升級執行。build 10 已於舊路徑別名不存在時通過來源、簽章、獨立匯入及私有資料檢查；最終桌面重新定位仍待補驗，見 [重新定位報告](../../../docs/verification/project-relocation-report.md)。

新增生命週期修補：實際 Codex server 群組被 SIGKILL 時，另一群組的 HUP-resistant 工具程序原先殘留；已加入獨立 guardian 與有來源的 EOF／清理收據，相同案例及工具執行中的宿主崩潰均通過，同 thread 恢復沒有重送工作。啟動修復可重試，壞 token／未確認清理不能宣稱成功；17 MiB 訊框超限後仍排空收據，parser 改為只掃新片段。最新 Python 393 項通過、無 skip；最終 Swift 141 項、0 failures、15 GUI skip，含真實 Main／Codex 交接及實際背景程序清理。依賴只補齊既有 psutil 7.2.2 的 codex extra，164 個 lock 版本、116 main／66 KWS／117 開發套件版本維持。詳見 [生命週期驗證](../../../docs/verification/codex-lifetime-report.md)。

最新 trial 已更新為 0.7.0／build 11，142 個 bundle／126 個 runtime 檔案、strict 簽章、受管理 Python 的獨立匯入及既有憑證值掃描通過；驗證時舊別名不存在，之後還原。最終完整 Swift 141 項、0 失敗、15 GUI skip；Python 393 項、0 失敗／skip。原生 App 全體崩潰及桌面／真人語音仍待解鎖，不能以無 UI 宿主代替整體驗收。

## Build 11 解鎖後的桌面驗收進度

2026-11-01：當前來源完整 Swift 回歸 141 項、0 failures、0 skip，包含原生全螢幕、兩個顯示器可用時的跨窗口移動及真實 Main／Codex 面板流程。正式 build 11 已從 Finder 啟動、原主 Agent 自動就緒，原聊天輸入收到真實模型回覆；既有音訊只有一條 active stream。啟動前 3,407 檔備份校驗全部相符。真人語音、人員專案附件重新定位及正式退出／重啟／全體崩潰仍待驗收，已提出具體人員測試。早先鎖定與 GUI skip 是歷史狀態，不能再作為目前桌面狀態。詳見 [當前桌面驗收](../../../docs/verification/build11-desktop-acceptance.md)。

## 主 runtime 忙碌斷線修補

桌面重新鎖定後改查隔離程序，重現原 native EOF 無法結束阻塞模型呼叫的缺口。新增 App-owned 主 runtime 獨立 guardian、私有 EOF 控制管線、PID／建立時間及跨群組後代核對；和 Codex 共用程序追蹤。新增四項真實子程序故障測試及原有程序／IPC 聚焦共 21 項通過；完整回歸與 build 12 封裝進行中。正式 build 11 仍開啟等待人員測試，未以新版來源覆蓋其 bundle；Mac 目前再度鎖定，已請人員解鎖。詳見 [忙碌斷線驗證](../../../docs/verification/main-runtime-lifetime-report.md)。

主 runtime 修補完成本輪回歸：Python 397 項無失敗／skip；Swift 141 項無失敗、15 GUI skip。build 12 在獨立 cache 位置通過 144／128 檔來源比對、簽章、受管理 interpreter 匯入與憑證掃描；正式 build 11 未被覆蓋。另以真實 Docker 的 TERM-resistant 容器重現 root 群組崩潰後 daemon 仍寫入的缺口，probe 回傳 1，已精準清理 fixture；此項必須修正，不以既有 timeout finally 通過取代。下一步完成啟動前資源登記、守護清理與不確定／重啟處理，再進行 GUI 與正式新版驗收。詳見 [build 12 結果](../../../docs/verification/main-lifetime-build12-results.json)。

## 原生 Docker 崩潰清理修補（build 13）

已修復前輪 TERM-resistant 容器在 root 群組崩潰後繼續寫入的缺口。原生 guardian 接管 stopped-container 建立、PID／准入 barrier 與完整 ID 的持久化；主 runtime 只啟動已登記容器，kernel lease 延伸至 daemon 清理。未確認時關閉 gate 並失敗，重啟先清理且不重播。七項真實故障／同目錄恢復矩陣通過，含 API 失聯後的啟動阻擋與旁觀容器保全。聚焦 44 項、完整 Python 408 項無失敗／skip；Swift 141 項無失敗、15 GUI skip。獨立 build 13 的 145／129 檔來源、簽章、受管理匯入與憑證掃描通過；dist 的 build 11 未被覆蓋。正式 GUI、真人及全 App 故障驗收仍待人員解鎖，目標未完成。詳見 [容器生命週期驗證](../../../docs/verification/native-docker-lifetime-report.md)。

## Codex 認證失敗及不可用流程（build 14）

已以真正 0.155.1 app-server、空白 home／file-only 認證完成未登入驗證：先確認 account=null 才送要求；Maltose 維持 paused，原輸入保留，重試不重複訊息或建立 task。執行檔缺失後亦可用明確新 @maltose 意圖交回，舊 Codex 要求 deferred、原檔不變。修正未登入訊息指向舊選單的文字，改為現有 Codex 選單。完整 Swift 143 項無失敗、15 GUI skip；文字修正後兩項聚焦通過。獨立 build 14 的 145／129 檔來源、簽章、受管理匯入與憑證掃描通過；Python 與 build 13 相同，沿用 408 項及七項 Docker 故障證據。正式 App 仍未切換，GUI／真人／專案附件驗收持續待解鎖；整體目標仍 in_progress。詳見 [認證故障報告](../../../docs/verification/codex-auth-failure-report.md)。

## 文件入口與歷史方案整理（2026-11-01）

已將架構入口更新為既有原生面板、受管理主 Agent、協調層與 Codex 的實際責任；roadmap 改指現行產品整合，舊 Host／MUP feature、協定及使用方式明確標為歷史／相容資料。Python 架構保留匯入基準並說明現行命名，開發入口區分 App 的正式資料與 CLI 相容日誌。不更動執行程式、資料或套件；10 份文件的 79 個本機連結及 git diff --check 通過，沒有重跑應用測試，不將既有測試結果算為重新執行。M7 最終文件交付仍須等待新版正式驗收結果。

## 當前受阻條件（2026-11-01 15:21）

桌面工具再次確認 Mac 鎖定，本機 Codex 專案仍使用舊名稱／路徑。現有可獨立執行的整合、核心驗證及文件整理已完成；正式新版 GUI、真人語音及完整 App 故障驗收仍缺實際證據。正式 dist／執行中的 App 為 build 11，獨立 trial 為 build 14，未覆蓋 bundle。本輪沒有重跑測試。等待人員解鎖、語音配合及本機專案／聊天重新定位後，恢復主計畫的完整未完成驗收；目標沒有完成。具體續做條件見 [主計畫](../../../plans/maltose-unification-and-codex.md)。

## 新增聊天捲動需求（2026-11-01）

人員已解鎖桌面，先按追加要求完成原生聊天的新訊息／串流自動跟隨與 30 秒手動閱讀保護。聚焦 10 項通過；完整 Swift 回歸及新版 App 進行中。正式資料、Python Agent 及其依賴未修改；本機專案重新定位與其餘產品驗收仍按主計畫續做。

### 聊天修補交付與剩餘驗證

0.7.0／build 15 已部署並從 Finder 啟動，主 Agent 就緒且真實文字回答會追蹤至底部。新功能聚焦 10 項通過；完整 Swift 148 項有 2 skip 及 1 項全螢幕案例的 4 個失敗斷言，兩項 skip 已另行補驗通過，全螢幕單獨重現仍失敗。不能宣稱完整回歸通過。實際 wheel 因 CUA 多螢幕位置錯誤未送出，手動規則的原生通知／clip 測試與真人手勢驗收分開記錄。停寫備份 4,444 檔校驗相符，舊版及正式資料仍可回復；後續補齊主計畫驗收。詳見 [聊天捲動報告](../../../docs/verification/chat-autoscroll-report.md)。
