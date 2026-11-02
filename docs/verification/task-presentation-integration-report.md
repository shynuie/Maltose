# 任務工作流與資訊輸出驗證紀錄

## 2026-11-02 build 20：行為紀錄與圓環任務樹

新增兩種透明內容的共用面板；任務樹讀取既有 ProductTask／Codex 執行狀態，Main 細步驟進度保存在原 store，完成判定沿用原核對。Python 577 項通過；完整原生 284 個案例有 1 個研究收尾案例失敗，同來源補驗通過，新面板與進度傳輸 9 個案例均通過。該失敗模型把新增成果面板誤解成修改舊板，並非新增進度工具路徑；首次失敗與補驗均保留。build 20 簽章、內含來源、隔離匯入及實際 UI-only 雙窗口啟動／正常退出通過；新面板種類已從該 App 的快照核對。實際 SwiftUI 執行中／完成截圖使用虛構資料，無真人語音驗收。詳細 [本批直接結果](agent-work-panels-build20-results.json) 與 [feature plan](../../runtime/dev/features/task_workflow_and_presentation_dev_plan.md)。正式 App 保持原樣，未 commit，整體工作流仍進行中。

## 2026-11-02 最新面板權限決定（優先於歷史規則）

依使用者「面板給 Agent 最大自由度，除本地文件增刪改外跳過授權」的新指示，Main 與 Codex 共用常設的面板讀取／操作權限。建立、聚焦、選取、切換、移動、關閉及面板內內容修改不再檢查逐次人員授權、聲紋或二次意圖模型；新成果預設新增只是呈現偏好，Agent 可依需要重用既有面板，並遵守人員明確要求保留的內容。這取代下方歷史紀錄的「只有明確更新才可操作舊面板」硬性限制。

本地檔案建立、覆寫、刪除仍依原 FileService／檔案權限機制；流程圖匯出仍保留既有匯出同意與檔案版本核對。面板內容編輯不等於修改磁碟原檔。真正的任務暫停、取消、過期來源與 Main／Codex 執行權交接仍有效；操作回執保存、讀回及去重繼續處理傳輸結果不確定，均不增加人員授權步驟。Memory／KDB 身分不因面板權限而改變。

此次只修正實際阻斷的面板授權問題，進階恢復／呈現維持 deferred。聚焦原生 20 項、完整 Python 574 項／原生 275 項全部通過，無 skip。build 19 已封裝至 `dist/trials/build19/Maltose.app`；簽章、140 份 runtime 來源一致性、隔離匯入及 UI-only 雙窗口啟動／正常退出通過，未啟動 Agent 或使用麥克風；正式 build 15 與試用 17／18 保持原樣。詳細 [本批驗證結果](panel-autonomy-build19-results.json)。真人語音驗收與正式切換仍未完成，未提交本批修改。


以下保留歷史批次，最新交付以上節與 build 19 結果為準。

最後更新：2026-11-02（Asia/Shanghai）。來源基準：`11d67c2` 加未提交修改。狀態：進行中；正式 App 保持 0.7.0／build 15，尚未封裝或部署本批來源。

需求與完成條件以 [詳細計畫](../../runtime/dev/features/task_workflow_and_presentation_dev_plan.md) 為準。本報告記錄階段證據，不能作為 P0–P5 全數完成的聲明。

## 已接通範圍

- Native runtime 協商 presentation v1；舊 client 不會收到新面板命令。TaskBrain 沿用原串流工具循環，產生完整結果與獨立語音摘要。
- 聊天逐步顯示 JSON 中的頂層 `full_text`，處理跨 chunk 的跳脫與 Unicode；工具回合草稿會重設，完成後以完整驗證結果核對正文與限制。不將原始 envelope 或口頭摘要混入全文串流。
- 長結果透過既有核心新增具標題文檔。舊 `publish_document` 相容路徑的去重限同一執行期；後續新增的 `deliver_result` 持久路徑及跨重啟證據見下節。建立成功須有有效 panel ID 回執。
- 設定檔 `[presentation]` 保存 `speech_mode=auto|summary|mute` 與摘要秒數目標；auto 對語音輸入短講、鍵盤輸入靜音。尚未新增產品設定 UI。
- 「念給我聽」可朗讀同一身分／來源／會話的上一份結果，不重新執行原任務或開面板；「詳細說」要求詳答並詳讀；「先別說話」及帶明確分隔符的前置控制只影響該次。一般引用這些詞不會變成控制命令。
- 詳讀分段播放；新鍵盤／已路由語音輸入或退出會取消待播內容與當前結果播放。播放失敗保留全文；面板結果未知不重跑原工作。既有 CLI／Web／舊 brain 相容路徑保留。
- 符合預算的摘要不需額外模型呼叫；不合格時最多一次工具禁用的語意修整，完整文字先送達。不允許修整變更全文、限制或結果 ID。失敗時明示無法可靠精簡。

## 測試證據

| 執行 | 結果與證據範圍 |
| --- | --- |
| 修改前基準 | Python TTS 1 項及 Swift 聊天／合約 8 項通過；歷史整合缺口見 [build 15 報告](chat-autoscroll-report.md) |
| 第一批完整 Python | 受限沙箱 414 項：4 failures／12 errors／5 skip，含程序查詢及 localhost 拒絕；必要存取與 Docker 啟用後 415 項通過；補串流工具相容／協商後 417 項通過 |
| 第一批完整 Swift | 150 項有 9 個失敗斷言：串流模型工具路徑 2 個及既有全螢幕 7 個；修正工具路徑後 151 項仍有 8 個：正常退出 1 個及全螢幕 7 個。跨程序結果交付案例通過 |
| 退出診斷 | 錯誤 70 的日誌確認終止訊號打斷 guardian 最終清理 ACK。使 finalization 對該訊號保持冪等；另觀察到 0.1 秒測試期限造成解譯器退出時收到訊號 15。正常案例改用正式的 3 秒 grace；強制終止案例仍明確使用 0.1 秒，沒有移除失敗斷言 |
| 最新原生聚焦 | 13 項通過、無 skip，4.803 秒。包含真實受管理子程序的全文分段送達、新文檔、舊內容保留、鍵盤靜音及正常退出；日誌 `/tmp/maltose-presentation-controls-native.log` |
| 最新程序生命週期 | 5 項通過、10.943 秒。新增在 final cleanup 期間送出真正 SIGTERM 的案例，並保留 guardian 遺失、host 崩潰、獨立 worker 清理與 lease 檢查；日誌 `/tmp/maltose-presentation-lifetime-focused.log` |
| 最新完整 Python | 428 項通過、無 skip，34.945 秒；包含 Docker。日誌 `/tmp/maltose-presentation-p1-python.log`。稍早受限執行的 73 項聚焦有 1 個程序 fixture 逾時，記錄於 `/tmp/maltose-presentation-controls-focused.log`，不以受限執行替代完整結果 |
| 摘要修整後聚焦／完整 Python | 聚焦 62 項通過，1.382 秒；最終完整 430 項通過、無 skip，36.507 秒，包含 Docker。日誌 `/tmp/maltose-presentation-repair-focused.log`、`/tmp/maltose-presentation-p1-final-python.log` |
| 串流／控制版本完整 Swift | 151 項、無 skip，199.282 秒；只有既有原生全螢幕案例的 7 個斷言失敗，正常退出、新結果面板、串流與真實 Main／Codex 案例通過。`/tmp/maltose-presentation-p1-swift.log`。摘要修整接上後的最終整合回歸另行執行 |
| 真實 TTS render | 系統預設 voice／rate 的兩段公開摘要產生音訊，實際長度 0.987528／5.107347 秒；未播放、未收音，產物已清理。`/tmp/maltose-presentation-tts-render-results.json`；不能替代真人聽感或實際打斷 |
| 真實主模型初次驗證 | 公開虛構資料，13.567 秒，全文 1326 字元；結構、全文、連結／程式碼、限制、串流、單次原模型回合及無私有 Memory 寫入通過。語音通用降級沒有保留測試資料限制，此項失敗，待修整後重驗；`/tmp/maltose-presentation-real-model.json` |
| 真實主模型修正後 | 公開 fixture 兩輪驗證分別 12.975／11.323 秒。一般回答均只用一個原模型回合；完整正文 1145／1069 字元，短摘要保留測試資料限制，估計 8.186／8.25 秒。第二輪另外刻意送入過長摘要，真正執行一次無工具修整：保留虛構資料與未查核來源，估計 10.25 秒，全文／限制／ID 不變、原任務沒有重跑。`/tmp/maltose-presentation-real-model-repaired.json`、`/tmp/maltose-presentation-real-model-with-repair.json`。未收音／播放，不能當作聽感驗收 |

摘要修整接上後完整 Swift 151 項、無 skip，194.974 秒；仍僅有既有原生全螢幕案例的 7 個斷言失敗，日誌 `/tmp/maltose-presentation-p1-final-swift.log`。其後補上一項純 Python 通知靜音保護，另以完整 Python 與原生聚焦核對，結果另記下方，不混用來源版本。

測試 fixture 初次新增分段時缺少時間模組，造成跨程序案例失敗；已修正並以 13 項原生聚焦重驗通過，沒有把該次 fixture 失敗計為產品成功。

### 靜音與待處理輸入的通知保護

尚未改接完整背景結果之前，原通知路徑先遵守「先別說話」與明確打斷；通知保留文字，不立刻接續朗讀。新的正常要求才解除該次靜音，保存的 mute 偏好仍生效。有待處理人員輸入或退出時先不 drain 通知，避免移除尚未處理的背景回報。此保護不等於背景通知已具備持久 outbox 或完整成果面板。

聚焦 Python 63 項通過，1.496 秒；`/tmp/maltose-presentation-notification-quiet.log`。最終完整 Python **431 項通過、無 skip**，35.196 秒，包含 Docker；`/tmp/maltose-presentation-notification-quiet-full-python.log`。原生聚焦 **12 項通過、無 skip**，4.705 秒；`/tmp/maltose-presentation-notification-quiet-native.log`。正常退出、新結果面板與真正的全文串流均通過。

最後直接讀回 dist App 仍為 0.7.0／build 15，executable SHA256 為 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`。29 份修改／新增檔案的行尾與 Markdown fence 檢查、73 個本機連結及 `git diff --check` 通過。沒有新 commit 或部署。

## 尚未完成

1. 原生 TaskManager 背景結果與 Codex 收尾已有共用新文檔交付；其他外部通知、Codex 暫停期間安全短語音播放及設定偏好 UI 尚未完成，語音打斷仍需實際裝置與真人驗證。
2. 共同任務、要求版本與前景 Main 自動核對已有下節證據；背景／Codex 的完整證據核對、接續／分類與收尾尚未完成，不能把局部核對或 awaitingEvidence 狀態當作整體工作流已完成。
3. 多面板自主編排與全部 Main／Codex 直接工具的明確更新許可；目前新文檔路徑不代表所有入口都已限制。
4. 背景 outbox 及原生接納後的恢復已有下節直接證據；前景回答在原生接納前的 runtime outbox、完整亂序／崩潰矩陣及使用者編輯衝突保護仍待完成。容量超限及非法 Unicode 等模型輸出錯誤的完整保留／受控 artifact 降級還需補齊。
5. 原生全螢幕的間歇性啟用問題、實際啟動／手勢及真人語音驗收；正式資料備份、新 App 封裝、切換、回復與最終稽核。本輪全螢幕有通過紀錄，但未修訂相關程式，不抹除先前失敗。

## 下一批寫入入口盤點

目前 36 個模型面板工具仍由共用 `WorkspaceAgentInterface.handle` 修改原生狀態；Main 經 Python `NativePanelToolAdapter`，Codex 經受交接 lease 保護的 `execute_codex_panel`，檔案操作另經既有 FileService 及 transfer。新增的 runtime-only `publish_document` 不在模型工具清單中。尚未全域落實更新許可，下一批須同時覆蓋：

| 入口類型 | 需覆蓋命令 |
| --- | --- |
| 純讀取 | get_user_view、list_capabilities、read_panel；保留既有身分限制 |
| 新建立 | create_panel；綁定同一發表的初始填入範圍，不能因建立過面板便永久取得修改權 |
| 內容寫入 | notes_set_text；chart_load_csv／chart_open_csv；image_add_url／image_add_file；browser_navigate／browser_control；flowchart_add_node／update_node／connect／delete_selection／new／open |
| 檔案副作用 | flowchart_save；保留檔案政策、外部修改 SHA 核對與未儲存保護，不能以面板許可取代檔案授權 |
| 視圖與工作區 | close／select／focus／toggle／move_panels、set_mode、grid_viewport、conversation_select_session，各面板 selection／viewport／series／bands／expand／collapse；同樣核對人員要求或當次新成果的允許範圍，避免搶焦點與改動閱讀狀態 |
| 即時單例 | identity_set_state 與聊天追加；依計畫保留單例語意，不為每次輸出新增形象／聊天面板 |

不能只在模型提示寫「不要覆寫」；實際寫入邊界須綁定人員輸入來源、操作範圍、穩定目標、版本與生命週期，且在非同步檔案 transfer 完成後再次核對。

## 背景成果持久交付與重啟恢復

本批仍為未提交來源，正式 App 沒有切換。Python 在既有 TaskStore 增加通知表，通知 payload 與準備好的 AnswerResult 均為 v1。worker 終態及通知同一交易提交；待交付通知的讀取不移除資料，原生 `chatStored` 回執才 ACK。完整原始內容仍在 TaskStore，準備結果穩定保存，重送不重新呼叫 worker。舊的歷史終態不回填通知。

原生以可選 resultDeliveryVersion=1 協商 runtime-only 的 deliver_result；模型工具仍為原 36 個。既有聊天 journal 保存全文／呈現意圖、面板套用與關閉紀錄，固定衍生 panel ID 恢復同一新文檔。聊天串流與 durable upsert 共用 message ID 與 conversation ID；同發表內容或不同發表重用訊息 ID 均拒絕。新發表仍新增，不覆寫原文檔或移動使用者焦點。關閉紀錄無法保存時保留面板、回報操作失敗，避免虛報成功或重啟後意外重開。

閒置期間每半秒只核對 pending ID，能在原生文字模式沒有下一則輸入時交付背景結果；偵測到使用者正在說話時不切斷聆聽。回執不明採穩定 ID／有間隔的重送，原生去重；重啟後只恢復文字／成果，不補播舊語音。speech claim 先保存，不等於已播放或使用者聽見。取消後的遲到結果保留取消狀態與完整內容，僅交付文字；既有 attempt 尚未 drain 時拒絕重跑。其他正常新成果仍遵守新增面板規則。

長背景結果若需摘要，使用完整的有界來源與末尾限制，不以任意前 12,000 字截斷。provider 若拒絕或逾時仍保留全文並明示無法可靠精簡；未聲稱所有 provider 的最大 context 都相同。

| 範圍 | 結果／證據 |
| --- | --- |
| 初輪既有聚焦 | Python 76 項、原生 13 項通過；先確認相容路徑與新協商未破壞既有行為 |
| 原生恢復與故障聚焦 | 18 項通過、無 skip，11.323 秒；`/tmp/maltose-durable-results-context-fixed-native.log`。包括保存意圖後尚未建面板的重建、已關閉 tombstone、不同內容／訊息 alias 拒絕、日誌不可用時不虛報關閉 |
| 真實跨程序故障案例 | worker 在 Agent 就緒且閒置後才釋放；原生寫入成功後刻意丟棄 ACK。正常關閉並重建 App 與 runtime，確認 worker-count=1、完整連結／限制保留、聊天與成果各一份，再取得 ACK。fixture 身分由測試程式提供，不能替代真人聲紋驗收 |
| 純 Python 狀態與故障 | 原生接納前留 pending／同 ID 重送／一次 speech claim、owner 隔離、重啟不補播、完成與 outbox 的交易 rollback、報告失敗不改寫成功、取消遲到結果、拒絕重疊重跑、超限內容保留及後續有效結果仍可交付、舊 CLI adapter 不讀舊答案；聚焦 88 項通過，1.703 秒 |
| 完整 Python（長來源檢查前） | 443 項通過、無 skip，36.810 秒，包含 Docker；`/tmp/maltose-durable-results-full-python.log` |
| 完整 Swift | 156 項、無 skip，212.245 秒；只有既有原生全螢幕案例的 7 個斷言失敗，其他案例通過。`/tmp/maltose-durable-results-full-swift.log`。不報成完整回歸綠燈 |

新增長來源完整保留測試後抓到空摘要被狀態提示誤認合格的問題：初次聚焦 89 項與完整 444 項各 1 個失敗，未真正呼叫摘要模型；`/tmp/maltose-durable-results-long-summary-focused.log`、`/tmp/maltose-durable-results-final-full-python.log`。修正後聚焦 **89 項通過**，1.737 秒；最終完整 Python **444 項通過、無 skip**，34.225 秒、含 Docker；`/tmp/maltose-durable-results-summary-cue-fixed.log`、`/tmp/maltose-durable-results-summary-cue-full-python.log`。原生最新聚焦 **18 項通過、無 skip**，13.836 秒；`/tmp/maltose-durable-results-final-native.log`。最後的摘要判定修改為純 Python，對應聚焦、全套與下方真實模型證據，不把之前的全套綠燈當作它的證據。

真實配置主模型 `gpt-5.6-luna` 以 **26,057 字元**公開虛構背景原文、空摘要與末尾來源限制測試通過；一次工具禁用的摘要呼叫，口頭內容「這是虛構測試資料；乙組最多，但未查核來源，不能視為研究成果。仍有待確認事項。」估計 **8.25 秒**。全文、限制及結果 ID 保持，原任務沒有重做；另一次正常回答仍只有一個原模型回合。總驗證 17.479 秒，`/tmp/maltose-durable-results-real-background-summary.json`。沒有播放、收音、真人聽感或原生面板驗證，這些證據範圍分開保存。

此前的新原生案例曾因缺少共同 conversation ID 產生三則而非一則聊天；已修正 bridge 事件 metadata 並重驗 18 項通過，失敗日誌保留於 `/tmp/maltose-durable-results-focused-final-native.log`。另一個新測試最初把故障注入 worker 的早期 progress，沒有命中預定的終態報告點；修正 fixture 後通過，初次日誌為 `/tmp/maltose-durable-results-python-focused.log`。

整個 P0–P5 仍未完成。下一階段優先中立 ProductTask／TaskOutcome 與要求版本／完成證據，並接上 Main／Codex，共用單一原生 writer；本節的 worker 終態與交付回執不能替代產品任務完成證據。

## 共用產品任務、要求版本與派發條件

本批為未提交來源；正式 dist App 仍是 0.7.0／build 15，執行檔 SHA256 再次讀回為 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`，沒有封裝、切換或新 commit。

原生 schema 3 在同一 writer 保存 v1 ProductTask。遷移測試核對 schema 2 原始位元組的私有備份；schema 1 相容測試也通過。原始人員輸入、委派來源、版本、舊計畫／成果與驗證證據保持。舊版本成功不滿足追加要求，較晚的不完整成果使先前結案失效，既有失敗須由對應且較晚的實際通過證據解決。成果回報整筆保存，重送衝突不局部改動執行狀態。

Main 經 workflow v1 實際保存／讀取計畫與原始輸入，鍵盤仍不取得 Memory 身分。未知聲紋的不同回合不共用 owner，已識別 profile 互相隔離。Codex 收到同一根任務的當前版本與自己的委派範圍，不附未委派的 Main／其他 worker 內容。停止要求、延後訊息與產品 held 原子保存，交回 Main 保持舊工作 held。

Python 先保存未開放派發的工作，host ACK 與引用落地 SQLite 後才開放 dispatch_ready；不知道結果時保持 held。完成 outbox 要同時取得 chatStored 與 workflowStored 才 ACK。測試另確認 observer 不延伸到下一次 plan／排程，原始版本不因新要求改寫。

| 驗證 | 結果與範圍 |
| --- | --- |
| 最初共同任務領域／相容聚焦 | 14 項通過，1.126 秒；`/tmp/maltose-product-task-domain.log`。包含遷移、追加要求、證據不足與既有 store／委派相容 |
| Main 實際規劃／追加要求 | 透過真正 managed desktop CLI 與 TaskBrain 工具循環，先保存計畫，下一次人員輸入使要求版本從 1 到 2，模型實際看見追加要求；兩份成果各建新面板，根任務保持同一份且待驗證 |
| 真正相依 Python workers | 受控已識別語音來源先經 VoiceAgent 保存；兩個實際 worker 在原生接納引用後才執行，第二個查到第一個 succeeded，三份 Main／worker 成果回到同一根任務。身分為 fixture，沒有真人／麥克風證據 |
| Codex 範圍與版本 | 實際 SDK 程序收到的兩回合 input 帶當前要求版本；檢查其原始 JSON 不包含 Main 私人目標／步驟／完成條件、其他 worker 內容或引用，原始使用者訊息保持 |
| 最終 Swift 聚焦（派發並行修正前） | 22 項通過、無 skip，6.773 秒；`/tmp/maltose-product-workflow-final-focused.log`。含九個領域案例、遷移／儲存、Main／Python／Codex、身分隔離與停止交回 |
| 第一輪完整 Python | 451 項，34.548 秒，5 個 Docker errors，其他通過；`/tmp/maltose-product-workflow-full-python.log`。唯讀檢查確認 daemon 未運行，啟動既有 Docker Desktop 後重驗 |
| Docker 恢復後完整 Python | 451 項通過、無 skip，42.288 秒；`/tmp/maltose-product-workflow-full-python-docker.log`，包含真正 Docker 案例 |
| 第一輪完整 Swift | 167 項，205.253 秒、無 skip，只有既有全螢幕案例的 4 個斷言失敗；`/tmp/maltose-product-workflow-full-swift.log`。這一版在最後的未識別語音／停止映射之前 |
| 最後 Swift 來源完整回歸 | 169 項，219.300 秒、無 skip，只有既有全螢幕案例的 7 個斷言失敗；`/tmp/maltose-product-workflow-final-full-swift.log`。真實配置 Main／已登入 Codex 與其他案例均通過。Python 派發條件其後單獨修正，另跑下列全套與原生聚焦 |
| 並行派發故障重現 | 新測試讓既有依賴在 host ACK 前真正完成，抓到新工作已進 running；8 項中 1 error，`/tmp/maltose-product-workflow-admission-race-before.log`。不是格式／fixture 失敗；實際新增持久派發條件修正 |
| 並行修正後 Python | 8 項聚焦通過，0.046 秒；完整 452 項通過、無 skip，41.343 秒，含 Docker；`/tmp/maltose-product-workflow-admission-race-fixed.log`、`/tmp/maltose-product-workflow-admission-full-python.log`。另補同一 SQLite 新連線讀回未開放狀態與重開已綁定引用的斷言，8 項通過，`/tmp/maltose-product-workflow-admission-persistence.log` |
| 最新原生聚焦 | 使用最新 Python 持久派發條件，22 項通過、無 skip，6.492 秒；`/tmp/maltose-product-workflow-admission-native.log`。真正的 Main／相依 workers／Codex 範圍、來源隔離、停止與 store／領域案例通過 |

新 Python 測試初次使用不存在的 tick_schedules 與錯誤的既有 identity error 斷言，7 項出現 1 failure／2 errors；修正 fixture 後 7 項通過，0.041 秒，日誌 `/tmp/maltose-product-workflow-boundary.log`、`/tmp/maltose-product-workflow-boundary-fixed.log`。Codex 摘要的 Swift 初次編譯因單一表達式型別推斷逾時失敗，拆開後 17 項通過，`/tmp/maltose-product-workflow-shared-context.log`、`/tmp/maltose-product-workflow-shared-context-fixed.log`。以上失敗保留，不當成成功證據。

本批結束時尚未接通自動工具驗證證據蒐集／語意核對／接續；前景核對後續進度見下節。不能以保守停留 awaitingEvidence 取代最終工作流。排程來源、每次 retry attempt、全部恢復點與需求分類仍待補；所有面板更新許可、Codex 收尾輸出分流、偏好 UI、真人語音、原生全螢幕與正式封裝也未完成。P2 與 P0–P5 均不宣告完成。

本批最後檢查 46 份修改／新增檔案，18 份 Python AST、75 個本機 Markdown 連結、fence／行尾與 `git diff --check` 通過。沒有用測試 skip、刪除斷言或更改正式 App 取代尚未完成的驗收。

## 前景 Main 自動核對與具體剩餘事項

本節是 P2 的新切面，沒有將背景／Codex 的完整自動工作流算作完成。原工作循環使用受控模型選擇工具；FileService 讀取、隔離 Docker 測試、原生 RPC／儲存／聊天／面板均為實際執行。下列 live 案例的**語意核對**使用當下配置的真實主模型，只提供公開 fixture，沒有讀個人 Memory／KDB，沒有收音或播放。

工具在真實返回邊界產生版本固定的不可變觀察；只收錄受支援的 FileService、命令、面板與時間回執，私有 Memory／KDB／TaskStore 及整個工作區感知內容不複製進共同任務紀錄。一般 echo／python -c／版本查詢不因 exit 0 成為測試證據；截斷、非法內容與 64 項預算溢出保留不完整標記，不能結案。同目標的已知後續修改使舊讀回失效。

全文與前景成果先保存，再條件式執行一次無工具核對；缺少合格證據、來源超限、格式錯誤或工作尚未完成時明列原因，不重跑工作。host 再核對最新要求、計畫、全部未結束／不明執行、未解失敗與 witness，才能保存完成判斷；無依據的 completed 降為 partial。assessment 與原 outcome 分開，核對文字另存聊天、原成果面板保留。保存後重送使用原核對；新要求／過期成果不能重用舊結案。

背景通知的 runtime-only delivery_origin 依實際通知來源設定；舊 v1 prepared 回報也正規化為 background，沒有原 worker 引用的舊排程不會套用最近的 Main 執行。模型最終 JSON 不接受此欄位。核對未通過時不口頭宣告全部完成；要求詳讀仍先說明核對限制，再保留原全文。

| 驗證 | 結果與直接證據 |
| --- | --- |
| 純 Python 核對與播放 | 新增 7 項通過，0.006 秒；`/tmp/maltose-workflow-assessment-speech-focused.log`。包含完整來源／條件／限制、禁用工具、錯誤／重複 JSON／虛構 witness、暫停傳播、要求版本、別執行緒隔離、超限標記及不播報未驗證成功；另有原呈現 22 項通過，0.071 秒 |
| 核對來源／原生 gate | 原生領域／store 聚焦 19 項通過，0.073 秒；`/tmp/maltose-workflow-assessment-schema-focused.log`。含無實際 witness 的模型完成宣告降級、保存重送／重開、檔案內容不能冒充測試與寫入後讀回失效 |
| 新前景場景聚焦 | 25 項通過、無 skip，16.545 秒；`/tmp/maltose-workflow-assessment-final-native-focused.log`。實際檔案足夠時結案、保留具體剩餘事項、追加要求競態拒絕舊結案；原工作只走一次規劃／讀取／回答，沒有重跑 |
| 真實模型正／反例 | 同一聚焦中，當前配置主模型真正核對本機來源並完成，5.067 秒；檔案自稱測試已通過且含改寫核對指令，但沒有本次測試觀察時不完成，4.560 秒。這是 live 核對，不是模型自主選擇工具的證據 |
| 第一輪完整 Python | 459 項通過、無 skip，45.086 秒，包含 Docker；`/tmp/maltose-workflow-assessment-full-python.log`。最後來源標記／私有觀察範圍修正的結果另列 |
| 第一輪完整 Swift | 176 項通過、無 skip，217.896 秒；`/tmp/maltose-workflow-assessment-full-swift.log`。啟用 GUI、真實 Main／Codex；本輪全螢幕案例通過，未移除或放寬原斷言 |
| 前景／背景來源修正 | 通知聚焦 14 項通過，0.113 秒；`/tmp/maltose-workflow-assessment-origin-focused.log`。新增舊通知＋最近 Main 任務的反例，不發送 mainResult、不改掛任務；完整 Python 460 項通過、無 skip，39.282 秒，`/tmp/maltose-workflow-assessment-origin-full-python.log` |
| 來源修正後原生 | 26 項通過、無 skip，17.039 秒；`/tmp/maltose-workflow-assessment-origin-native.log`。真正 Main／worker、實際模型正反例、全文面板與領域／store 均通過 |
| 真正隔離命令與核對 | 私有 fixture 的 Docker 容器真正執行 test_receipt.py，實際一項測試通過，stdout baseline verified、stderr Ran 1 test／OK 成為本次 observed verification；主模型真正核對後完成。原工作模型呼叫 3 次、核對 1 次，沒有重跑命令。與背景 App／runtime 遺失 ACK 恢復合跑 2 項通過，8.962 秒；`/tmp/maltose-workflow-assessment-actual-command-fixed.log` |
| 新測試納入完整原生 | 177 項通過、無 skip，213.790 秒；`/tmp/maltose-workflow-assessment-final-full-swift.log`。GUI、真實 Main、真實 Codex、Docker 全啟用；最後的 Python 私有觀察範圍修正再以全套 Python／原生聚焦驗證 |
| 私有邊界最後回歸 | 最新完整 Python 460 項通過、無 skip，40.520 秒，包含 Docker；`/tmp/maltose-workflow-assessment-private-full-python.log`。最新原生聚焦 28 項通過、無 skip，23.125 秒；`/tmp/maltose-workflow-assessment-private-native.log`，含真實主模型正反例／容器核對、背景重啟與面板交付 |

中途失敗保留：初版原生 18 項有 1 個舊斷言失敗，因新增工具觀察使 execution 證據由 2 到 3，改為核對真正 worker 回執而不把一般工具觀察混計，`/tmp/maltose-workflow-assessment-initial-native.log`。完整觀察預算判斷最初因 Swift throwing 短路運算編譯失敗，拆開後 24 項通過，`/tmp/maltose-workflow-assessment-native-live.log`、`/tmp/maltose-workflow-assessment-native-live-fixed.log`。實際容器核對 fixture 初次只接受 sourceRead、漏收已有的 verification，2 項有 1 failure；修正 fixture 後通過，`/tmp/maltose-workflow-assessment-actual-command.log`。私有邊界新斷言最初重複註冊既有 recall 工具造成 1 error，改用觀察邊界驗證後 7 項通過，`/tmp/maltose-workflow-assessment-private-boundary.log`、`/tmp/maltose-workflow-assessment-private-boundary-fixed.log`。沒有把這些失敗改報為成功。

目前原生全螢幕有兩輪全套通過，但沒有修訂全螢幕實作，不宣稱已找到或修復先前間歇性啟用失敗的原因。真人語音／手勢、正式 App 啟動／封裝仍無本批驗收證據。

下一步優先接上 Python 背景／Codex SDK 命令與差異的驗證來源、完成後有界承接，以及具體收尾；需求分類、排程來源、retry attempt、前景接納前 outbox／中斷證據恢復、所有面板更新許可與多面板編排、偏好 UI、真人驗收和正式切換也仍有工作。整體目標保持進行中。

最後直接讀回正式 dist App 仍是 0.7.0／build 15，執行檔 SHA256 仍為 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`；本批沒有新 commit、封裝或部署。

最終靜態檢查涵蓋 50 份修改／新增檔案、20 份 Python AST、76 個本機 Markdown 連結，fence／行尾及 `git diff --check` 通過。

## Codex SDK 證據與共用收尾交付

此批接上真正 SDK item/started 的來源固定、實際命令／測試回執、唯讀來源專案基準、暫停期間無工具主模型核對，以及新文檔收尾。較晚的人員要求不能替早先執行換版本，缺少 started／無法辨識／不完整的 SDK 資料保持 unknown。已知 fileChange 使較早同工作區測試失效，必須有較晚測試才能以該證據完成。完整未知 SDK 內容仍保存於原任務，沒有冒充已驗證 witness。

主模型的 assessment 與意圖 review 使用不同持久快取；模型只有已核對來源可引用，原生仍守住版本、狀態及實際證據。收尾先回傳 host，再核對問題仍有效才交付；新需求先到時不發表過期文檔。完整回顧保留 Markdown／連結，選擇文檔時沿用 deliver_result，後續回合另建。短摘要與全文分開，但尚未在 Codex 暫停期間播放。

| 驗證 | 結果與範圍 |
| --- | --- |
| 新 Python 聚焦 | 協作 review 11 項通過，0.043 秒；workspace 10 項通過，5.326 秒。包含 controller lease、無工具／Memory 核對、分離快取、延後發表、完整回顧／短摘要與來源專案未被改動。`/tmp/maltose-codex-output-python-review-focused.log`、`/tmp/maltose-codex-output-source-focused.log` |
| 初輪原生聚焦 | 26 項、1 skip、無 failure，1.143 秒，`/tmp/maltose-codex-output-initial-native.log`；當時未啟用 installed Codex，不能當全套通過。另一組 28 項有 1 個舊斷言未區分 assessment／原報告，修正為分別核對，`/tmp/maltose-codex-output-initial-shared.log` |
| 首批 SDK／交付聚焦 | 7 項通過、無 skip，10.103 秒，`/tmp/maltose-codex-output-focused.log`。實際子程序執行 unittest，受控主模型；兩回合各開新回顧、Main 持續暫停、過期 review 不開板、同回合晚到證據維持原版本 |
| 初輪完整 Python | 464 項通過、無 skip，41.485 秒，包含 Docker；`/tmp/maltose-codex-output-full-python.log`。後續新增 witness 清單反例後另跑下列全套 |
| 明確可引用證據聚焦 | 8 項通過，0.006 秒，`/tmp/maltose-codex-output-witness-focused.log`。unknown SDK／自述保留供理解順序，但不在可引用清單；模型引用它們時仍拒絕，不做靜默修正 |
| 最新完整 Python | 465 項通過、無 skip，43.357 秒，包含 Docker；`/tmp/maltose-codex-output-witness-full-python.log` |
| 最新原生聚焦 | 17 項通過、無 skip，84.842 秒；`/tmp/maltose-codex-output-witness-live.log`。包含來源版本、修改後舊測試失效、新文檔兩回合、過期問題拒絕、真實 Codex／Main 與 App／runtime／store 重啟 |
| 真實 Codex 與 Main | 上述聚焦中的實際案例 78.079 秒：Codex 修改隔離 calculator.py，獨立 python3 -m unittest test_calculator 真正通過 3 項；當前配置主模型以實際測試與 workspace 差異完成核對。原專案檔案／HEAD／index／status 均與基準相同，Main 仍 paused。沒有真人收音或播放 |
| 收尾未知 ACK 恢復 | 上述聚焦中的實際案例 2.496 秒：原生 journal 保存新文檔後刻意遺失回執，關閉全部程序／store／面板 model，再重建並用既有重試動作恢復。相同問題 ID、面板 ID 與一份聊天；SDK count=1、review-count=1，持續 paused。此為重啟後明確重試，不宣稱所有 issue 都會自動清除 |

中途失敗保留：新恢復測試初版誤用 GlassPanelView.id，編譯失敗，`/tmp/maltose-codex-output-recovery-live.log`。修正識別碼後 14 項有 3 個斷言失敗：聊天 ID 漏了會話前綴，以及真實核對未完成的 2 個斷言，`/tmp/maltose-codex-output-recovery-live-fixed.log`。修正測試 ID 後恢復通過，但真實核對仍有 2 個失敗，`/tmp/maltose-codex-output-recovery-diagnostic.log`；公開 fixture 的私有回應證據確認模型引用了 unknown SDK 執行紀錄，因此被正確拒絕。現在輸入明列 eligibleEvidenceIDs 與排除規則，保留原驗證拒絕，真實重驗與反例通過；沒有把「停在待驗證」當作最終行為。

背景驗證與有界自動承接、全部更新許可、多面板編排、偏好 UI、前景接納前 outbox、完整恢復矩陣、暫停期間短語音與真人／正式 App 驗收仍未完成。本批不宣告 P2 或全目標完成；正式 App 尚未切換，沒有新 commit。

### 完整回歸抓到的順序／引用與舊 fixture 問題

第一輪完整原生 185 項、無 skip，331.414 秒，有 12 個失敗斷言（其中 1 個 unexpected），日誌 `/tmp/maltose-codex-output-final-full-swift.log`。分別是舊面板 fixture 沒接 durable 聊天日誌的 2 個、舊聊天斷言未包含現已明示的「Codex 自述測試仍待核對」的 1 個、真實模型把最終唯讀差異快照誤認成測試後修改的 2 個，以及既有全螢幕啟用案例的 7 個。該次真實 Main→Codex→直接追加→新意圖完整流程通過，67.804 秒，但不代表所有要求都有足夠證據結案。

修正沿用正式的聊天日誌接線，真實面板工具案例等待收尾保存後才驗證，允許共用輸出層依內容新增回顧文檔，同時仍嚴格要求只有一個新 notes、工具真正寫入與原專案未改動。聊天斷言核對原始 Codex report 的正式 displayText 與未驗證標示，沒有移除測試資訊的驗證。

核對側明列 oldest-first 順序、最終快照不是修改事件、來源專案基準的意義，以及已知後續修改後仍有效的 witness；較早要求版本的晚到修改也保留。長證據 ID 只在本次請求轉成無衝突短引用，模型輸出先嚴格驗證，再還原真正 ID。未知／過期 ID 仍拒絕，不模糊比對或靜默刪除；partial 只列有 witness 的 checks，其餘保持具體 remaining。

| 驗證 | 結果 |
| --- | --- |
| 順序／短引用聚焦 | Python 10 項通過，0.006 秒，`/tmp/maltose-codex-output-order-focused.log`；包含長 ID 精確往返、原資料保持、修改前後測試與最終唯讀快照 |
| 受影響原生聚焦 | 4 項通過、無 skip，59.498 秒，`/tmp/maltose-codex-output-order-live.log`；真實共享面板工具、fixture 去重、真實 SDK／Main 核對（39.934 秒）、單一聊天／同 thread／追加要求／交回 Main |
| 對應完整 Python | 467 項通過、無 skip，41.915 秒，包含 Docker，`/tmp/maltose-codex-output-order-full-python.log` |
| 修正後完整原生 | 185 個案例、無 skip，317.707 秒；184 個案例通過，僅原全螢幕案例失敗（7 個失敗斷言），`/tmp/maltose-codex-output-order-full-swift.log`。逐項 Test Case 終態核對為 passed=184、failed=1。真實 SDK／Main 核對 40.924 秒、完整 Main→Codex→直接追加→新意圖 58.485 秒；本批所有非全螢幕案例通過 |

### 本輪全螢幕環境核對

完整回歸仍顯示 awaiting-activation、active=false、key=false。依本機 AppKit SDK 的公開註解，launch／activate 不保證取得啟用狀態；UI-only 測試啟動器補上 macOS 14 cooperative yield／activate(from:) 與回傳診斷，保留所有真正 System Space／AppKit／root／opaque 斷言。聚焦 WorkspaceNativeTests 4 項仍有同一案例的 7 個失敗、無 skip，29.338 秒；其他三項通過，`/tmp/maltose-codex-output-cooperative-fullscreen.log`。啟用請求回傳 allowed=true，但 App 仍未 active，沒有宣稱修復。

其後以唯讀 IORegistry console session 核對，實際讀回 `CGSSessionScreenIsLocked=True`、`kCGSessionLoginDoneKey=True`，只輸出狀態，未輸出登入者資訊。這與本輪啟用失敗一致：需要解鎖後驗證；不能據此推定所有歷史間歇性失敗都已找到同一原因。已請使用者方便時解鎖，其他開發可繼續，不把整個目標標為 blocked，也不跳過案例取得全套通過。

正式 dist App 再次核對仍為 0.7.0／build 15，SHA256 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`；沒有封裝、部署或新 commit。最新來源的完整 Python、原生完整回歸及其全螢幕失敗分開記錄，不能將 184 個通過案例寫成 185 項全通過。最終檢查涵蓋 58 份修改／新增檔案、25 份 Python AST、77 個本機 Markdown 連結；fence／行尾及 git diff --check 通過。

## 背景工具證據、執行引用與整體成果核對

新增 workerEvidenceVersion=1 私有協商，沿用原 worker／TaskStore，不把私人工作資料合併進 Memory 或任意 Main turn。原生在同一交易登記真正 attempt 並核對原 job 來源；本機先保存、取得 ACK 才執行。每次實際重試獨立 ID，ACK 不明但未開始時重送同一 ID；已開始但結果不明仍保留未知狀態。重試前可先同步前次不可變終態，不 ACK 交付、不重跑工作。取消排隊中工作保留其未執行事實；取消已開始工作仍等待原 attempt drain。

context collector 只捕捉本次 worker 的真正工具返回；受支援的完整 FileService／命令／面板／時間回執按原生分類核對，搜尋 worker 的 provider 回應明示 search_results 範圍，不能當已讀全文。原始回報字串沒有 trusted evidence 入口。私人 Memory／KDB 不複製，跨執行緒不混入；預算與非法內容保留不完整標記。終態、證據與通知在 SQLite 同一交易；新表 additive，既有通知不回填虛構證據。

原生 pythonResult 依實際 attempt 保存來源、工具證據及原回報；當全部執行返回才條件式核對。同 owner／task／要求／計畫版本中已 ACK 的完整成果會納入語意核對，最後一個 worker 不必重複先前已交付的回答。未 ACK、其他 owner／task／版本不納入；超限不任意截斷，保持未完成核對。模型判斷仍受原生當前版本、失敗及 witness gate 限制。核對文字保存失敗則不接受通知，重送讀取已保存 assessment。

背景口頭內容依 host 接納的狀態；完整原始 worker 回報保留。已核對成功時去除單純來自 runtime 的泛用待核對限制；未完成核對時不播報 worker 的「全部測試通過」自述。這是政策／假 speaker 驗證，不是真人播放或聽感。

| 驗證 | 結果與範圍 |
| --- | --- |
| 原工作關聯 Python 基準 | 8 項通過，0.049 秒，`/tmp/maltose-worker-evidence-initial-python.log`；既有 task 管理 13 項通過，0.681 秒，`/tmp/maltose-worker-evidence-task-regression.log` |
| 新背景證據聚焦 | 初版 6 項通過，0.068 秒，`/tmp/maltose-worker-evidence-focused.log`；後續加入 owner／版本聚合、重試、取消與語音後最終 11 項通過，0.169 秒，`/tmp/maltose-worker-evidence-speech-focused.log` |
| 實際聚合核對 | 3 項通過、無 skip，13.905 秒，`/tmp/maltose-worker-evidence-aggregate-native.log`。包含相依執行、原始成功不足以結案、丟失 assessment ACK 後同 ID 恢復，以及真實配置 Main＋真正 FileService（4.537 秒） |
| 執行引用／領域聚焦 | 14 項通過、無 skip，13.704 秒，`/tmp/maltose-worker-evidence-reconcile-native.log`。原生 attempt 原子接納／重送／並行拒絕、舊失敗保持、追加要求不升格舊執行，以及全部背景正例 |
| 最後原生正反例 | 18 項通過、無 skip，19.537 秒，`/tmp/maltose-worker-evidence-final-focused-native.log`。實際主模型核對兩份已交付來源 4.797 秒；檔案自稱測試通過但沒有真正測試回執的反例 6.061 秒，保持 partial 與具體 remaining，不重跑 worker |
| 完整 Python | 478 項通過、無 skip，39.950 秒，包含 Docker，`/tmp/maltose-worker-evidence-full-python.log` |
| 完整原生 | 189 個案例全部通過、無 skip，304.721 秒，`/tmp/maltose-worker-evidence-full-swift.log`。GUI、已登入 Codex、配置 Main 與 Docker opt-in 全啟用；逐項終態 passed=189、failed=0，原 System Space 全螢幕與跨螢幕／內容保存案例也通過 |

中途失敗保留：初版原生 11 項有 3 個失敗（1 unexpected），舊 fixture 仍以 job 數量代替真正 attempt，且等待 outcome==3 漏掉獨立 assessment，`/tmp/maltose-worker-evidence-initial-native.log`。補原生案例後 3 項有 4 個失敗（1 unexpected），包括舊 state 斷言、短 fixture 內容本來只需聊天而非文檔，以及真實主模型因只看見最後一份完整回報而拒絕結案，`/tmp/maltose-worker-evidence-actual-native.log`。前兩者修正 fixture；第三者實際補聚合已 ACK 成果，沒有移除完成判斷或重做原任務。

Python 聚合測試最初未設定 fixture owner，7 項有 1 error，`/tmp/maltose-worker-evidence-aggregate-python.log`；重試測試新增 pending guard 後仍期待舊 RuntimeError，10 項有 1 error，`/tmp/maltose-worker-evidence-retry-focused.log`。更正 fixture／精確斷言後 11 項通過。程式沒有放寬 owner 或 guard 以取得通過。

目前沒有把「自動核對」當作「有界自動接續已完成」。完成後主動綜整與下一步、失敗承接、需求分類、排程來源、已開始後崩潰的 reconciliation、前景接納前 outbox、全部更新許可、暫停中短語音、偏好 UI、真人驗收及正式封裝仍有必要工作；整體目標維持 active／in_progress。

本輪重新唯讀查詢 console session 時，未再讀到先前的 locked=true 標記；不僅依此推定 UI 可用，而是以上述完整原生的實際 AppKit 全螢幕結果為準。先前鎖定期間的失敗與歷史間歇性問題保留，不能宣稱本批修改了產品全螢幕邏輯或完成真人手勢／正式 App 啟動驗收。

最後核對正式 App 仍為 0.7.0／build 15、執行檔 SHA256 仍是 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`；沒有新 commit、封裝或部署。61 份修改／新增檔案、28 份 Python AST、77 個本機 Markdown 連結及 fence／行尾檢查通過，git diff --check 通過。

## 2026-11-02 背景有界接續與主動收尾

本批沿用已有 TaskBrain／ToolRegistry、TaskManager、VoiceAgent 主循環與原生單 writer，新增 continuationVersion=1 協商與可恢復的 product_continuations 交付佇列。主模型收到原任務、當前要求、已 ACK 的同 owner 完整成果、原生核對與真正 remaining；內部接續不偽造人員輸入、不改變 Memory 身分或授權。已核對完成時無工具綜整；仍有可授權補做的工作時使用既有工具；真正缺少決策／授權或達八次上限才提問。

每次實際工具前後與真正面板寫入前皆核對新輸入、要求／計畫版本、執行權與停止。正文和獨立 assessment 使用相同接續來源守門；Codex 到達時不先顯示過期結案再撤回。已發生讀取／寫入保留真實事實，未派發的工具不執行，Main 保持既有暫停。

生成結果與不可變工具觀察先存 SQLite，再呼叫原生交付。未知 ACK 只重送相同結果；generated 重啟恢復交付，不重做模型或工具。running work 沒有結果時保留 uncertain；只讀 finalize 可安全重新生成。恢復不補播舊語音，假 speaker／播放政策與真人聽感仍分開。

| 驗證 | 結果與直接證據 |
| --- | --- |
| Python 接續合約／恢復 | 8 項通過，0.029 秒，`/tmp/maltose-continuation-decision-python.log`。同輸入來源、禁止個人寫入、無工具 finalize／clarify、原文降級、SQLite 真正關閉重開、owner 與 trigger ACK、queued input 阻止派發 |
| 背景接續正反例 | 8 項通過、無 skip，38.883 秒，`/tmp/maltose-continuation-failure-native.log`。真實工具補讀、worker 實際失敗承接、上限／具體問題、@codex 打斷、發表前拒絕過期成果、遺失 ACK 不重做模型 |
| 第一輪完整 Python | 486 項通過、無 skip，46.484 秒，含 Docker，`/tmp/maltose-continuation-full-python.log` |
| 第一輪完整原生 | 197 項通過、無 skip，330.328 秒，`/tmp/maltose-continuation-full-swift.log`。GUI、已登入 Codex、配置 Main、Docker opt-in 全啟用，全螢幕通過；最後 assessment 守門與兩個恢復／競態案例尚未納入此輪 |
| 最後恢復／競態聚焦 | 4 項通過、無 skip，34.098 秒，`/tmp/maltose-continuation-recovery-native-fixed.log`。包含真正配置 Main 接續（21.705 秒）、遺失 ACK、實際 runtime 崩潰／store 重建、assessment 保存前新輸入 |

真正主模型接續由模型選擇 FileService 讀取缺少的第三份來源，而非只做無工具評審；最後來源集合包含 step1／step2／step3，原需求只有一份，結果可核對 17＋34＋51＝102。模型可在有界範圍內分多回合讀取與核對，不以固定一次呼叫冒充完整正例。

崩潰測試只 SIGKILL 自己的 fixture runtime PID，時點為原生已保存正文但尚未回 ACK。關閉並重建 runtime、CodexTaskStore、聊天 journal 與面板後，保留相同產品任務、continuation ID、panel ID 與一份聊天；worker count=2、補讀 count=1、接續模型 count=2。身分恢復由受控 fixture 提供，沒有真人收音／聲紋證據。

過期 assessment 測試讓正文在有效版本先保存，之後新 @codex 要求才到達：正文保留、過期核對文字拒絕，已發生讀取與 succeeded execution 保留，continuation 中斷且 Main paused。不能把「保留早先有效正文」誤寫為新要求後仍容許舊結案。

中途失敗保留：初次讀取 publicationID 的測試欄位不存在而編譯失敗，`/tmp/maltose-continuation-actual-native.log`。實際模型讀取 get_task_workflow 後丟失 continuation ID，工具成功卻無法核對，`/tmp/maltose-continuation-actual-fixed-native.log`；已修正 adapter 保留同 task／input／版本的 continuation ID，沒有放寬 witness gate。`/tmp/maltose-continuation-scoped-native.log` 因 worker fixture 缺少真正 collaboration service 造成交接超時，補既有服務。`/tmp/maltose-continuation-handoff-fixed-native.log` 則抓到將缺少可讀來源誤當需要人員輸入，已區分可自行補證據與真正新決策，保留全部原工具批准邊界。

另外兩輪新增 host 測試因修改不可變 request 欄位編譯失敗，改為重建請求，`/tmp/maltose-continuation-final-focused-native.log`、`/tmp/maltose-continuation-autonomy-native.log`。最後恢復案例初次因 optional count 與 Int 比較編譯失敗，補 nil fallback 後四項全通過，`/tmp/maltose-continuation-recovery-native.log`、`/tmp/maltose-continuation-recovery-native-fixed.log`。所有失敗均保留，不改報成功。

本批仍未涵蓋一般前景承接、需求延續／修改／新任務分類、排程來源、running work uncertain 的完整核對／恢復入口、前景接納前 outbox、全部面板更新許可、多面板編排、暫停中的安全短語音、偏好 UI、真人聽感／手勢與正式 App 交付。P2／ADR 仍為進行中／proposed，沒有新 commit、封裝或部署。

最新完整 Python 486 項通過、無 skip，48.671 秒，包含 Docker，`/tmp/maltose-continuation-recovery-full-python.log`。最後 assessment 發表守門及恢復案例對應的完整原生結果另列下項，不能借用第一輪 197 項作為最終來源的全部證據。

正式 dist App 再次讀回仍是 0.7.0／build 15，執行檔 SHA256 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`，HEAD 仍為 `11d67c2` 加未提交修改。本輪更新計畫入口的接續批次與需求分類規則，保留 P0–P5 未完成邊界，沒有部署或新 commit。

### 當前來源的完整原生回歸與全螢幕限制

`/tmp/maltose-continuation-recovery-full-swift.log`：199 個案例、無 skip，368.231 秒；逐項終態為 passed=198、failed=1。唯一失敗為既有 testAutomaticNativeFullscreenUsesSystemSpace，7 個斷言；接續、實際主模型／Codex、worker 失敗承接、生成結果 SIGKILL／重建與新輸入拒絕過期 assessment 均通過。不能寫成 199 項全通過。

全螢幕直接診斷仍為 awaiting-activation、active=false、running=true、key=false、native=false，fixture cooperative activation allowed=true。唯讀 IORegistry 僅讀回 kCGSessionLoginDoneKey=True，未讀到 locked=true 旗標；缺少旗標不能證明已解鎖，也不能將本輪失敗直接歸因螢幕鎖定。沙箱內初次 ioreg 被拒絕，使用相同唯讀命令在允許環境重讀，僅輸出鎖定／登入旗標，未輸出個人內容。本批沒有改動產品全螢幕邏輯，不為取得成功移除或放寬測試。

針對未解的桌面啟用條件再跑 WorkspaceNativeTests，4 個案例中 3 個通過，原全螢幕案例仍是相同 7 個斷言失敗，30.437 秒、無 skip，`/tmp/maltose-continuation-recovery-fullscreen-recheck.log`。沒有因無證據的環境推測反覆重跑全套，後續需查核真實桌面啟用條件；此限制不阻止獨立的前景承接／面板規則開發。

最後靜態檢查：65 份修改／新增檔案、30 份 Python AST、9 份 Markdown／79 個本機連結，fence／行尾及 git diff --check 通過。下一批先補一般前景承接與需求分類，再完成 Codex 短語音、全部面板更新許可及多面板編排；完整恢復、真人驗收、全螢幕與正式交付仍按計畫追蹤。整體執行目標保持 active，未結案。

## 2026-11-02 人員輸入範圍分類、新 Codex 目標與完整計畫交付

本批核對到一般 Main 新訊息原先自動追加未完成任務，會讓獨立問答改變舊任務的完成條件。新增 inputScopeVersion=1 私有協商；同一 TaskBrain 工具循環的 set_task_scope 僅分類已保存的人員輸入。continueTask 追加原始人員文字並升要求版本；newTask 建立獨立目標；standalone 不寫產品任務。讀取舊任務不再取得其成果引用，新協定下未分類也不能透過 setPlan／pythonPlan 繞過。協商前不提供新工具，舊 read／setPlan 流程保留相容行為。

原生核對當前人員輸入、任務／版本與既有綁定，分類不可變，forceNew 不搬移已承諾來源，保存計畫不解除 held。建立新任務只綁自己的原始輸入，不再掃入後面的未分類訊息。新輸入不必改變舊要求版本，就能使舊接續的工具與發表失效；內部接續沒有 set_task_scope。

產品目標切換後，直接 @codex 不再繼承歷史 Codex thread／worktree／delegation。原生先核對舊回合沒有 active／pending／uncertain 操作，再準備新隔離工作目錄與 SDK thread；舊產品任務、Codex 記錄與成果保留。此路由案例使用實際本機程序／隔離目錄與受控 SDK，真實已登入 Codex 的既有回歸另列完整測試；不將受控 SDK 說成實際開發。

真正配置主模型的新計畫案例保留舊任務逐欄不變，使用 newTask 與三步 set_task_plan，最終以結果 ID 核對完整計畫文檔與面板。沒有建立 Codex／Python 開發工作，隔離來源專案仍只有原始 fixture.txt 與 .git；Memory 身分仍未知。這是實際主模型選工具與結果交付，不是真人收音／聽感。

| 驗證 | 結果與直接證據 |
| --- | --- |
| 首輪領域與既有規劃 | 18 項通過、無 skip，3.967 秒，`/tmp/maltose-input-scope-native-focused.log` |
| 分類／實際模型第一輪 | 21 項通過、無 skip，26.254 秒，`/tmp/maltose-input-scope-live-native.log`；真正主模型的新計畫案例 20.157 秒 |
| 最後 Python 聚焦 | 原生產品邊界、接續與呈現共 41 項通過，0.219 秒，`/tmp/maltose-input-scope-document-python-focused.log`；新增協商、來源注入與讀取不綁定的反例 |
| 計畫正文／接續聚焦 | 22 項通過、無 skip，26.795 秒，`/tmp/maltose-input-scope-document-native-focused.log`；含真實模型完整文檔、standalone、新任務、過期人員來源、同版本中斷與 generated 崩潰恢復 |
| 新 Codex 目標路由 | 20 項通過、無 skip，22.879 秒，`/tmp/maltose-input-scope-codex-routing-native.log`；歷史任務保持、新目標使用另一個 SDK thread 與 worktree、Main 仍 paused，並回歸真實主模型規劃 |
| 最新完整 Python | 489 項通過、無 skip，43.389 秒，包含 Docker，`/tmp/maltose-input-scope-full-python.log` |

中途失敗保留：`/tmp/maltose-input-scope-final-native-focused.log` 的 22 項有 1 個失敗斷言，測試誤以最後一則聊天代替有 ID 的成果，實際最後一則為獨立 assessment；改為核對結果 ID 對應的完整文檔與新面板。

`/tmp/maltose-input-scope-delivery-native-focused.log` 的 22 項有 2 個失敗斷言，揭露真正模型建立空 document 後用 notes_set_text 寫入，遭正確拒絕後又將全文縮成錯誤簡述。原生筆記工具沒有放寬到可寫文檔；已明確說明 document／notes 能力差異，結構化最終答案的 full_text 必須保留完整計畫並選 visual=document，由既有結果 publisher 建立文檔。呈現失敗也不能把全文換成簡述。保留所有原生面板工具供模型選擇，沒有透過移除工具或降低全文驗收取得成功。

此批沒有完成一般前景部分成果／失敗的持久接續：下一步仍須先保存前景生成結果、原始身分／輸入與工具回執，再恢復交付並判斷可續做範圍；獨立問答之後如何安全回到原授權工作亦需補驗。全部面板更新許可、多面板編排、Codex 暫停短語音、未知執行核對、偏好 UI、真人驗收、全螢幕與正式交付仍未完成。整體目標保持 active，沒有 commit 或部署。

舊協定與當前路由補驗 4 項通過、無 skip，22.781 秒，`/tmp/maltose-input-scope-compatibility-native.log`。以實際 runtime 在 initialize 忽略新欄位、不回傳 inputScopeVersion，確認 host 保留 v0；runtime 不提供 set_task_scope，透過原 read／setPlan 流程仍將真正 follow-up 接到同一產品任務，沒有新增分類欄位或另一份任務。其餘三項涵蓋真實主模型、過期原輸入與新 Codex 目標。

本輪靜態核對 66 份修改／新增檔案、30 份 Python AST、9 份 Markdown／80 個本機連結，fence／行尾及 git diff --check 通過。正式 dist App 仍是 build 15，執行檔 SHA256 保持 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`。

### 完整回歸發現：分類之前也必須使舊核對失效

第一輪完整原生 208 項、無 skip，365.860 秒，12 個失敗斷言，`/tmp/maltose-input-scope-full-swift.log`。分為既有全螢幕啟用案例 7 個，以及新要求在實際核對模型執行期間到達的案例 5 個。後者不是單純舊 fixture：新訊息尚未分類時要求版本仍為 1，舊 assessment 曾因只檢查版本而被接納並結案。

修正讓 Main／Python report 的 assessmentContext、真正 assessResult 提交，以及接續 Context／Start／工具／發表共同核對最新非 deferred 人員輸入。新訊息即使尚未分類、不追加原任務，也會使舊核對失效；已完成的工具觀察／原回報保持。競態 fixture 的新 Main 回合真正呼叫 set_task_scope 延續並追加 r2，而非預先將未分類訊息寫進舊需求；多一次分類模型回合，原檔案仍只讀一次、原核對模型仍只跑一次。最終相關聚焦與完整回歸另列，不以本輪 208 項當作通過。

最新人員來源修正後的原生聚焦 24 項通過、無 skip，33.645 秒，`/tmp/maltose-input-scope-latest-source-native.log`。包含真正新訊息在評審期間到達、延續分類後 r2、原讀取／評審不重跑、真實主模型三步計畫、背景聚合、舊協定、新 Codex 目標、同版本新輸入使待發表接續失效及領域保存／恢復。最終完整原生回歸另列，不用聚焦結果替代全部驗收。

### 最新完整原生回歸與實際 Codex 回報邊界

最新完整原生 208 個案例、無 skip，506.096 秒，`/tmp/maltose-input-scope-final-full-swift.log`：逐項 passed=207、failed=1。修正後的追加要求競態、全部新輸入分類／原生來源、真實主模型計畫、背景核對／接續、新 Codex 目標與其餘回歸均通過。本輪原生 System Space 全螢幕通過（5.745 秒），保留前一輪與歷史失敗，不宣稱本批修復其啟用條件。

唯一失敗為實際 Codex 背景終端清理案例，2 個失敗斷言（其中 1 unexpected）：SDK 已完成啟動並回傳 PID／session，但 typed report 同時回報 kind=completed 與非空 remaining，把主機的後續存活／清理驗收列為自己尚未完成工作。控制器因此依原規則保持 codexDirect／Main paused，未發出完成問題；180 秒等待逾時。檢視隔離 fixture 記錄確認該矛盾回報，沒有憑環境推測或放寬 completed＋remaining 的守門。

釐清測試的人員要求：Codex 只負責啟動與回報 PID／session，主機後續驗收為獨立範圍；啟動成功時 remaining=[]，失敗仍須如實回報；PID 檔只含數字以避免無關跳脫問題。存活、SDK 背景程序、交回時清理、Main 暫停／恢復與不自動批准等原斷言全部保留。這是 fixture 要求修正，沒有修改產品收尾規則。亦將真實模型計畫案例補上僅新增一份成果文檔、沒有額外空文檔的直接集合斷言。這兩項測試修改後以實際聚焦補驗，完整 208 項的前一版本失敗仍保留，不混寫成當前全套皆通過。

實際補驗 3 項通過、無 skip，46.760 秒，`/tmp/maltose-input-scope-final-live-acceptance.log`：真正 Codex 背景程序啟動／存活／SDK 追蹤／交回清理 27.659 秒；真正主模型三步計畫、完整內容與僅新增一份結果文檔 17.893 秒；新要求期間的舊核對拒絕 1.207 秒。沒有自動批准互動，也沒有刪除背景存活或清理斷言。

最新來源的 setPlan／pythonPlan 亦在保存計畫／準備新派發前核對當前人員輸入，舊來源不因分類已完成就能在新訊息到達後繼續建立工作。相關領域、過期原輸入、實際相依 workers、分類 follow-up、舊 runtime 與核對競態聚焦 20 項通過、無 skip，6.580 秒，`/tmp/maltose-input-scope-plan-source-native.log`。原執行結果／證據保存與這個新工作 admission 檢查分開；不以改寫原 attempt 來源冒充新要求。

### 最終當前來源回歸

`/tmp/maltose-input-scope-source-full-swift.log`：完整原生 208 項全部通過、無 skip，355.693 秒；逐項終態 passed=208、failed=0。GUI、已登入 Codex、配置 Main 與 Docker opt-in 全啟用。這輪包含最後的計畫／派發來源守門、背景測試範圍修正，以及完整計畫僅新增一份文檔的斷言。實際 Codex 背景終端 23.689 秒通過；原生 System Space 全螢幕 5.788 秒通過。前兩輪的 12 個與 2 個失敗仍保留，不能從日誌移除或用新成功改寫歷史。

對應完整 Python 489 項通過、無 skip，43.389 秒，包含 Docker，`/tmp/maltose-input-scope-full-python.log`；最後的追加修改僅原生守門／測試與文件，Python 來源維持該輪版本。最後 git diff --check、66 份來源／文件、30 份 Python AST、9 份 Markdown／80 個本機連結及 fence／行尾檢查通過。正式 App 仍為 0.7.0／build 15、原執行檔 SHA256 保持，沒有新 commit／封裝／部署。

本輪全套通過是當前來源的回歸證據，不能替代一般前景持久承接、全部面板許可、多面板編排、真人語音／手勢或正式交付的必要實作／驗收。後續先依詳細計畫的「一般前景成果的持久承接」批次完成來源、保存與交付，再接續 P2–P5；整體目標維持 active／in_progress。

## 2026-11-02 build 16 獨立試用包

依使用者要求先提供可試用版本，輸出 `dist/trials/build16/Maltose.app`（0.7.0／build 16）；正式 `dist/Maltose.app` 仍是 build 15、執行檔 SHA256 保持。打包腳本新增 `MALTOSE_PACKAGE_BUILD` 以標記獨立試用版本，預設維持 15。

一般前景成果持久交付目前只有部分來源、協定及 SQLite/native 記錄接線，`ForegroundResultService` 與 VoiceAgent callback 尚未實作完成，不能啟用。本次將原生 `foregroundResultsEnabled` 預設設為 false，協商版本為 0，沿用原已完成的交付路徑；加入預設關閉與握手版本的啟動回歸斷言。未完成程式保留供後續接續，本包不宣稱支援前景斷線恢復。既有背景接續、輸入範圍分類、任務核對、完整文檔及簡短語音流程納入。

此版完整 Python 489 項通過、無 skip，43.306 秒（含 Docker），日誌 `/tmp/maltose-build16-python.log`。原生聚焦 18 項通過、無 skip，29.658 秒，涵蓋 runtime 啟動／聊天／關閉、成果文檔與真正主模型的新目標規劃（20.596 秒），日誌 `/tmp/maltose-build16-native.log`。本次沒有重跑完整原生 208 項，前批證據不改記成此版全套。

Release 編譯 47.12 秒通過；簽章、135 份 runtime 檔與來源逐檔一致、獨立目錄匯入及私密資料檢查通過。包本身以隔離 UI-only/windowed 啟動，建立 2 個視窗並自行退出，沒有初始化正式 Agent 或使用麥克風；不等同真人語音驗收或正式資料下的完整 Agent 啟動驗收。直接結果見 [build 16 檢查資料](task-presentation-build16-results.json)。

試用前須先退出舊版，避免同時開啟同一正式資料的 writer。沒有替換正式包、啟動正式 Agent 或新增 commit，整體 P0–P5 與前景持久承接仍未完成。

## 2026-11-02 build 16 試用回饋與 build 17

### 實際問題與修正

人員確認短語音有效，但半年民調未主動畫圖，追問後僅交付 Mermaid 文字，並反覆說「仍有待確認事項」。唯讀核對該次 runtime 紀錄：最終輸出只支援自動文檔，且 SpeechPolicy 只要 partial 或存在 limitations 就無條件附加該句；Main／worker 又會把核對狀態換成模糊口號。另外，Main 的 web_search 與 worker 的 search_web 名稱／回傳形狀不同，前景搜尋回執沒有進共同來源紀錄，會讓查詢因缺少來源證據持續待核對。沒有將這些政治資料／正式個人對話複製進測試或文件，也沒有為當時搜尋數字背書。

AnswerResult schema 1 增加可選、有界且不可變的 chart，透過 resultChartVersion=1 協商；舊格式仍可讀。模型在同一個最終結果中主動提出日期數據圖表，不增加工具回合，不以 Mermaid 取代原生圖表。沿用既有圖表 View／Model，建立新的圖表與完整文檔，圖表上顯示來源／方法限制，資料點保留備註；確定的繪圖數值與來源另由程式附入全文表格。不同調查方法分線、缺值保持 null，不插值、不補零。資料不足時須明說缺什麼，不虛構完整的半年資料集。

圖表與文檔共用不可變發表內容，但具獨立穩定 panel ID、套用狀態與關閉紀錄；保存意圖後才建立並 ACK。重送不新增副本、不重設目前使用者視角／線條選擇；重啟恢復未關閉圖表，已關閉的不重開；不寫既有圖表、不搶焦點。最後將圖表套用／關閉改成獨立 result_chart_applied／result_chart_closed 事件，讓 build 15／16 的 reader 忽略新事件，避免誤把配套文檔標記關閉。新 chart 合約拒絕既有 panelID；明確更新舊圖才使用已存在的工具入口。全部直接 Main／Codex 工具的更新許可仍是後續 P3 工作，不能以此宣稱已全部強制。

語音不再無條件追加「仍有待確認事項」，全文小節改為「資料與結果限制」。核對 partial 時保留主要發現並使用具體 remaining 原因，不把內部狀態口號取代答案，也不把資料缺口說成需要人員確認；needs_input 才說明具體待決定問題。原始內容／完整限制保留；核對拒絕成功時，口頭不再保留「全部完成」式自述。

前景 web_search 在真正 ToolRegistry 回傳邊界以原輸入／版本保存完整有界來源，與 worker 共用 search_results 封裝；保留實際工具名稱，不複製 Memory／KDB 私有回傳。原生只接納明確的來源摘要回執，不接受截斷或假稱 full_page 的格式；搜尋摘要只能證明查詢及返回連結／摘要，不能證明讀取原始頁面或完整問卷。

### 驗證與中途失敗

| 驗證 | 結果與證據 |
| --- | --- |
| 新圖表／語音初次 Python | 26 項通過，0.055 秒，`/tmp/maltose-chart-python-focused.log` |
| 原生圖表持久交付 | 9 項通過、無 skip，5.913 秒，`/tmp/maltose-chart-native-focused.log`；含缺值／來源備註、原面板與焦點、重送視角、保存後恢復、獨立關閉、衝突不寫日誌 |
| 實際模型自主選圖 | 修正 fixture 後 10 項通過，19.029 秒，`/tmp/maltose-chart-live-native-fixed.log`；真正模型案例 13.007 秒 |
| 第一輪完整 Python | 494 項中 493 通過、1 失敗，45.226 秒，`/tmp/maltose-chart-full-python.log`；原因與修正如下 |
| 同步修正後完整 Python | 494 項通過、無 skip，47.931 秒，`/tmp/maltose-chart-final-python.log` |
| 圖表整合的完整原生 | 212 項通過、無 skip，389.121 秒，GUI／Main／Codex／Docker 全啟用，`/tmp/maltose-chart-full-native.log`；原生 System Space 全螢幕 5.706 秒通過。此輪在最後的新日誌事件及搜尋回執修正之前，不改記成最後 214 項全套 |
| 最後相容／搜尋／真實模型聚焦 | 15 項通過、無 skip，25.033 秒，`/tmp/maltose-chart-final-native-focused.log`；新日誌事件、來源分類及實際模型正反例均在此輪 |
| 最終完整 Python（含搜尋接線） | 495 項通過、無 skip，50.235 秒，含 Docker，`/tmp/maltose-chart-search-full-python.log` |
| 最後新增／更新規則與格式補驗 | 27 項通過，0.070 秒，`/tmp/maltose-chart-final-presentation.log`；最後僅補結果提示與禁止 chart 指定舊 panelID 的反例，未重跑全部 Python |

真實配置主模型的半年資料驗收使用明確虛構的閱讀偏好，不提「畫圖」。模型主動產出原生新圖表與新文檔，A 電話／B 網路各分甲、乙四條系列，逐列核對 6 個日期、精確數值、對應方法、缺值與來源備註，原任務及原面板保留。最終聚焦再驗 12.128 秒通過；不是腳本指定最終 chart 的受控模型，也不是對原政治民調的真實來源查核。

最後真正評審模型的搜尋正反例 7.371 秒通過：受控工具返回相同的公開格式虛構搜尋摘要；找連結並註明僅摘要可結案；自述已讀完整原始問卷、樣本數與抽樣方法時保持 partial，明列缺少原始資料，不把它說成人員需確認。實際 registry 查詢只跑一次，原工作模型 3 回合、獨立評審 1 回合，沒有為補證據重跑任務。

中途失敗保留：第一次實際模型驗收 `/tmp/maltose-chart-live-native.log`，10 項中 1 個案例失敗（2 個斷言，其中 1 unexpected），96.916 秒。該 planning fixture 的第一回合刻意使用受控模型，只有後續回合才接真實 provider；新測試誤把首回合當真正模型，因此無 chart 等待逾時。修正先完成既有受控前置回合，再送獨立問答給實際 provider，原圖表／數字斷言沒有刪除，並追加逐欄方法／候選項對應檢查。

完整 Python 唯一失敗是既有 admission 測試在新工作尚未被執行緒取走前就呼叫 shutdown，依產品原語義會取消 queued futures，造成預期的觀察列表為空。改以事件等待新 worker 真正進入後再關閉，保留「host ACK 前不可派發」、新 store 連線下仍未 admission、原 workflow 不可變與成功終態等原斷言；未修改 shutdown 或放寬 admission。原生編譯另有測試未使用 deliverResult 回傳值的 warning，不影響上述成功結果。

### build 17 試用包與完成邊界

輸出 `dist/trials/build17/Maltose.app`，0.7.0／build 17。Release 編譯 44.55 秒，最後重新封裝納入最新提示；嚴格簽章、135 份 runtime 檔逐檔與來源一致、獨立目錄匯入、私密設定／憑證檢查均通過。包本身的隔離 UI-only/windowed 啟動建立 2 個視窗並自行退出，沒有啟動正式 Agent／使用麥克風。直接結果見 [build 17 檢查資料](task-presentation-build17-results.json)。

試用包執行檔 SHA256 `7c5b4d6cbf4efdc9de3a385af499fb2877ec4dcd887ee9aa9a24adca7bdfe301`；正式 build 15 的原雜湊仍是 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`，build 16 試用包保留。沒有自動重啟人員正在使用的正式 Agent、替換正式 App 或新增 commit。開新包前先退出舊版。

一般前景成果持久交付仍未完成並保持 foregroundResultVersion=0。這次是自主原生圖表及具體收尾提示的第一條路徑；全部面板更新許可、多面板編排、其餘前景／不確定執行恢復、暫停語音與真人聽感／手勢仍待依計畫完成。沒有將整體目標標記完成。

## 2026-11-02 一般前景成果保存、來源與 ACK 恢復

本批承接 build 17 後的計畫：新增真正前景 outbox 及 VoiceAgent 保存／交付 callback，補齊先前已存在但停用的原生 metadata／SQLite 接線。新來源已啟用 foregroundResultVersion=1；正式 build 15 與獨立 build 17 均未重新封裝／替換，仍維持原 SHA256。本批不是一般前景部分成果自動續做或整體 P0–P5 的完成。

### 現在可核對的行為

完整 AnswerResult、圖表、原工具回執、原 input／conversation／producer runtime／要求與計畫版本、原始人員來源在 final publication 前保存於真實 foreground_results；不新增假 worker、通知或 Memory owner。原生 foregroundPrepare 保留原執行的事實，再於真正 journal／panel writer 核對文字／圖表、不變來源、當前人員輸入／執行權及 stop／held／cancelled。來源真正 superseded 才停止交付；啟動或暫時暫停時保持 pending，五秒後重試同一份結果。

全文與必要核對各有穩定發表 ID，讀回實際 journal 與面板套用／關閉回執後才確認；重送／重啟沿用同份結果與原訊息 ID、不重做工具或任務、不重複開板。只讀核對提案先存 SQLite 再提交原生，ACK 遺失時重送已保存提案或原生接受結果，不重跑評審。已失效的核對也不能重貼為當前結果。

真正已保存的全文成為 answer_delivery artifact，可支援人員只要求的完整計畫／報告／可視交付；其內部自述的實作、測試、讀過原頁等仍需獨立證據。保留 192 KiB 核對預算，超限不截斷冒充完成。實際模型已對純計畫完成、檔案／答案自稱測試通過而無測試回執的正反例作判斷。

同一交易也可把 dispatching／uncertain 的原輸入標為 accepted，生成結果是其已真正 admission 的證據；後到的 submit_text 回應失敗不推翻已確認 admission。沒有生成結果的未知工作不因此自動重跑。交付後只送最終文字替換，不再送會暫時重複附加全文的 delta。語音先 claim 再交原播放流程，claim 不等於實際聽見；恢復／稍後重送不補播，也不使原已識別來源提升重啟中未知 speaker 的 Memory 權限。

前景與背景工作、丟 ACK、既有有界綜整一起啟用亦已聚焦驗證。最後一條背景接續的模糊確認語音改用已存在的 with_assessment helper，保留主要發現與具體缺口。

### 聚焦證據及中途失敗

- 原有呈現相容：Python 27 項通過，0.074 秒，`/tmp/maltose-foreground-existing-python.log`；原生 13 項通過、無 skip，5.869 秒，`/tmp/maltose-foreground-existing-native.log`。
- 真實 SQLite 的前景保存／重開、無假 worker、來源／對話隔離、丟 ACK、評審先保存與 final／語音順序：最後 8 項通過，0.080 秒，`/tmp/maltose-foreground-final-python-focused.log`。包含未知身分恢復已識別來源、暫時暫停不丟棄，以及版本／conversation 協商反例。
- 新來源／真正評審／新輸入 writer 競態：3 項通過、無 skip，50.549 秒，`/tmp/maltose-foreground-native-fixed.log`。實際配置模型的純計畫／實作自述正反例 41.300 秒；body 與 assessment writer 兩處各在寫入前接到新輸入，舊寫入未進 journal，已發生事實保留。
- 實際自主圖表改走前景保存，以及 SIGKILL 在 UI 寫入前／後兩處，整個原生 store／runtime／journal／manager 重建：2 項通過、無 skip，17.990 秒，`/tmp/maltose-foreground-recovery-native.log`。原任務模型計數維持 3，主執行只有 1 個，原 producer 不改成新 session；訊息／成果各 1 份，無補播，SQLite 沒有假個人任務或通知。
- 最後協商／預設啟用與交叉路徑聚焦：18 項通過、無 skip，97.603 秒，`/tmp/maltose-foreground-final-focused.log`。包含真正 pause／held／stop、不重開舊答案，foreground＋worker＋有界補讀綜整及 lost ACK，真實模型規劃與實作反例。
- 真正原生 pipe 的人員 user_message 與 submit_text ACK 同時遺失：3 項通過、無 skip，6.870 秒，`/tmp/maltose-foreground-admission-native.log`。測試以保存結果確認 admission，再故意回傳失敗 ACK；原輸入保持 accepted、無 issue、工作 3 回合與評審 1 回合，不重派任務。其餘兩項重驗正文與 pause／held／stop writer。

第一次原生前景聚焦 `/tmp/maltose-foreground-native-focused.log`：3 個案例失敗、6 個斷言（其中 3 unexpected），37.132 秒。生成內容與 native prepare／UI 寫入已成功，測試共用 helper 卻未接實際 journal 讀回，foregroundDelivered 正確拒絕確認，原 outbox 保持 pending。最初自動編輯又把讀回 closure 加到另一個相似 helper；定位後只接到真正 assessmentPanels helper，保留所有 ACK 與完成斷言，修正後上述 3 項通過。正式 App 的相同 callback 在本批之前已存在，未假裝這是產品已丟失資料。

`/tmp/maltose-foreground-control-native.log`：3 項中的 1 個失敗斷言，24.506 秒；pause 本來就會新增控制狀態日誌，測試誤把 pause 前整份 journal 與 writer 被拒絕後相比。改在控制狀態更新後、真正 writer 呼叫前取快照，拒絕前後位元不變；沒有移除 pause／held／stop 或保存內容的斷言。背景交叉與 SIGKILL 在該輪已通過；後續 18 項與 3 項聚焦再次驗證所有最後修改。

### 完成邊界

新前景來源、保存、實際發表、交付證據、評審保存／ACK 及生成成果重啟恢復已接線。完整回歸結果另列在下方；不把聚焦當成全套。仍須把前景 partial／failed 的安全續做接到真正前景 trigger／conversation scope，不能借用目前 worker-only 佇列的 FK 或已識別 owner；獨立問答後回到原任務、running 未知狀態核對、排程來源、暫停期間短語音、所有面板入口更新許可、多面板編排、偏好 UI、真人語音／手勢及正式交付仍未完成。沒有新 commit 或 App 封裝／部署，整體目標維持 active。

### 最後當前來源的完整回歸

Python **503 項全部通過、無 skip**，47.775 秒，含 Docker，`/tmp/maltose-foreground-full-python.log`。原生 **221 項全部通過、無 skip**，446.692 秒，逐案例終態 passed=221／failed=0／skipped=0，`/tmp/maltose-foreground-full-native.log`；GUI、實際 Main／Codex 與 Docker 全啟用。此輪包含最後的來源過期／暫停分流、前景預設啟用、圖表新路徑、交叉背景綜整、輸入 ACK 喪失的 admission 保全與不重複附加全文的修正；不是僅重跑 v0 舊流程。

[本批驗證資料](foreground-result-delivery-results.json) 保留能力版本、完整結果、真實崩潰與完成邊界。原生實際模型純計畫／實作自述反例、SIGKILL 兩個位置與 admission ACK 遺失均在本輪通過；先前 6 個與 1 個失敗斷言仍保留。最後來源、JSON、Markdown 連結及 git diff --check 通過。正式 App build 15 與獨立 build 17 的執行檔雜湊均與原紀錄相同；本批沒有封裝、部署或新 commit。前景部分成果的通用安全續做等剩餘項仍維持未完成，沒有宣告整體目標完成。


## 2026-11-02 一般前景部分成果／失敗的有界接續

### 修改與可驗證邊界

新增獨立 foregroundContinuationVersion=1 能力（新產品預設啟用），需要前景持久交付與原 continuation 協定。foreground_continuations 外鍵連到實際已送達 foreground_results，子成果需同對話、原人員輸入、任務與版本，且父成果確實 ACK。沿用既有 ProductContinuationService／TaskBrain／VoiceAgent 主循環與原生 ProductTask 單一 writer；不建立假 worker、通知、人員輸入或已識別 Memory 身分。

一般前景 partial／已知 read_file 失敗可依原授權補做並綜整完整已送達成果；純計畫已交付且核對完成即停止。需要人員選擇時交付具體問題，最多八次 work 後進入一次無工具 clarify，不無限補做。真正 FileService 回執與全文交付仍分開核對；已知來源不存在回執不含全文，不充當 sourceRead 證據。直接 API、許可拒絕及寫入／未知例外未被轉成自動成功／重試。

前景來源在工具與 writer 邊界核對最新人員輸入、@codex、要求／計畫版本、執行權及停止狀態。完整結果與實際 observations 先保存；真正原生 ACK 後才安排下一步。SIGKILL 恢復區分尚未進入工作的 admitting、只恢復交付的 generated，以及不能自動重做的 running／uncertain。原生 scope 沿用 interrupted 狀態並新增可選 recoveryState，實際 execution 狀態為 uncertain；這不是完整人工 reconciliation 或降版改寫驗收。重啟不補播舊答案、不提升身分。

### 聚焦及中途失敗

- 最後 Python 前景保存＋接續聚焦：16 項通過，0.113 秒，`/tmp/maltose-foreground-cont-python-final-focused.log`。新增 malformed assessment context 保持待交付／不 claim 語音，恢復只重送原文；其餘包含來源外鍵、不可變全文、父 ACK、未知 running 持久保存、協商反例、無假 owner、已知讀取失敗與許可邊界。
- 既有背景接續重驗：8 項通過，0.039 秒，`/tmp/maltose-foreground-cont-legacy-durable-python.log`。順帶修正舊 worker running→uncertain 的 SQLite 更新缺少 commit，重開資料庫驗證狀態未回退。
- 第一輪原生 4 案例，3 通過、1 案例失敗（2 個失敗斷言，其中 1 unexpected），53.009 秒，`/tmp/maltose-foreground-cont-native-focused.log`。真實主模型接續、未知／已識別語音、純計畫／具體問題已通過；已知 read_file 找不到檔案卻中斷整個前景回合，無原成果可接續。保留隔離 runtime 日誌定位真實 FileNotFoundError，修正為已知失敗回執後，該案例含正常 partial 與 failed 兩路通過，8.798 秒，`/tmp/maltose-foreground-cont-failure-fixed.log`。
- 恢復 fixture 首次編譯失敗：將 async 呼叫直接放進同步 XCTest autoclosure，見 `/tmp/maltose-foreground-cont-recovery-native.log`；改為先 await 取得回覆再斷言，未刪除驗證。
- 最後恢復／中止聚焦 4 案例全部通過、無 skip，36.743 秒，`/tmp/maltose-foreground-cont-control-native-final.log`。包括 admitting、generated、原生已寫入但 ACK 前三個 SIGKILL 點並完整重建 store／runtime；真正 running 保持未知；八次 work＋一次具體問題；新訊息與 @codex 在缺少來源工具派發前阻止舊工作。模型／讀取計數跨重啟累計，不能以重設計數掩蓋重跑。

語音來源由受控 fixture 輸入，未使用真人麥克風或聲紋，不宣稱已完成真人收音／聽感驗收。配置真實主模型的案例實際選 FileService 工具，只補讀缺少來源並綜整。原調查數字及正式私人資料未搬入測試。

### 當前完整驗證

完整 Python：**511 項通過、0 失敗、無 skip**，48.455 秒，`/tmp/maltose-foreground-cont-full-python.log`。完整原生：**229 項全部通過、0 失敗、無 skip**，508.489 秒，`/tmp/maltose-foreground-cont-full-native.log`；GUI／配置真實 Main／真實 Codex／Docker 全啟用，包含原生 System Space 全螢幕及跨螢幕。原始摘要見 [本批檢查資料](foreground-continuation-results.json)。

正式 build 15 與試用 build 17 保持原執行檔雜湊，未封裝、部署或 commit。AST 225 份 Python 來源／測試、現有驗證 JSON、已改計畫本機連結及 git diff --check 通過。仍有獨立問答後承接、未知執行核對入口、排程來源、Codex 暫停短語音、全部面板更新許可、多面板編排、偏好 UI、容量錯誤回饋、真人驗收及正式交付；整體目標維持進行中。


## 2026-11-02 獨立問答交付後的原前景任務承接

### 修改與實際邊界

新增獨立 taskResumptionVersion=1，需 foregroundContinuationVersion=1，預設啟用。真正人員輸入被分類為 standalone 時，原生保存當時原任務／要求／計畫版本的不可變 interlude；該問答不加入原要求。原生 ForegroundPublication 保存原 answerKind，答案真正交付後，resumeContext 依當前任務、版本、來源可存取性及執行權決定是否可回到原授權。

新接續保留原 input／task／版本／foreground root 與父成果 FK，另以 resumeAfterID 引用送達的獨立答案。原生接納、每項工具 checkpoint、結果／assessment writer、SQLite outbox 皆保留該來源。新輸入／@codex、held／cancelled、版本改變、needs_input／newTask、未 ACK 或未知／中斷 work 都不因問答回答完而恢復。原八次 work 上限不重設，內部事件不成為新的人員要求或 Memory owner；完整原成果仍用於綜整。

已生成結果可在實際 SIGKILL 及整個原生 store／runtime 重建後只恢復交付，不重做模型與工具。這是已送達前景來源的第一條接線；問答期間返回、尚未交付的 worker 成果仍需沿真實 owner／attempt 接回，不把假通知塞進 foreground FK，不提升未知 speaker。

### 聚焦與中途失敗

- Python 最後前景保存／接續聚焦 **19 項通過**，0.131 秒，`/tmp/maltose-resumption-python-final-focused.log`。包括答案 ACK 前不排接續、原來源／新答案雙引用、錯誤來源拒絕、格式錯誤不承接、生成後重啟不重做與獨立協商反例。
- 真正桌面 stdio／原生 journal：最終 **6 案例全部通過、無 skip**，57.249 秒，`/tmp/maltose-resumption-native-final-focused.log`。包含受控正常問答後接續、配置真實主模型選缺少來源工具、八種原生來源／狀態情境，以及原有三個 SIGKILL 恢復點、未知 running 與新 resumed generated 結果崩潰重建。取消另以 helper 的 cancelled 任務值反例核對，未冒充完整人工取消流程驗收。
- 多個缺口的串接：**1 案例通過、無 skip**，2.475 秒，`/tmp/maltose-resumption-chain-native-fixed.log`。原要求三份資料，先讀第一份、回答獨立問題，再分兩個新接續讀第二／第三份；三份來源各有真實 FileService 回執，兩個接續保留同 resumeAfterID，原要求／版本不變。

第一輪恢復 fixture 編譯失敗：在 nonthrowing 的原生 panel callback 用 try XCTUnwrap；改為 guard pid 與明確失敗斷言，見 `/tmp/maltose-resumption-native-admission.log`。隨後 4 案例中有 1 個測試斷言失敗，34.519 秒，`/tmp/maltose-resumption-native-admission-fixed.log`：新 @codex 是真正追加要求，測試卻錯誤預期要求數不變。修正預期為保留原要求並追加該 Codex 訊息；獨立問題仍不得加入。實際執行／恢復與真實模型在該輪已通過，最終 6 案例全部重驗。

多步 fixture 第一次 1 案例失敗（2 個失敗斷言，其中 1 unexpected），61.390 秒，`/tmp/maltose-resumption-chain-native.log`。受控模型錯把「第二份尚未讀取」中的字眼當作已取得第二份，重複選第三份而達有界上限；改為核對 fixture 完整來源的特定內容，保留三項真正讀取證據與兩個接續斷言後通過。未修改產品判斷使該錯誤回覆能假裝完成。

### 當前完整驗證

完整 Python：**514 項通過、0 失敗、無 skip**，50.668 秒，`/tmp/maltose-resumption-full-python.log`。修正後固定來源的完整原生結果見本節末尾；第一輪與最終結果均保留，不能宣稱全套通過。

AST 225 份 Python 來源／測試、既有驗證 JSON、本機計畫連結及 git diff --check 通過。正式 build 15 與試用 build 17 雜湊保持不變；未封裝、部署或 commit。語音來源仍是受控輸入，沒有真人收音／聽感證據。仍有背景成果跨問答交付、未知執行核對／明確重試、排程來源、Codex 暫停短語音、容量回饋、全部面板許可、其餘自主呈現／偏好、真人驗收與正式交付，整體目標保持進行中。


### 完整回歸揭露的條件抄寫與過窄測試假設

第一輪完整原生 **234 案例，232 通過、2 案例失敗（2 個失敗斷言）、無 skip**，543.689 秒，`/tmp/maltose-resumption-full-native.log`。一項為新真實 resumption 案例：實際用兩個接續完成且兩份來源各讀一次，測試卻強制只可有一個接續；改為真實模型在既有八次界限內、原需求不變、所有來源證據與不重讀限制仍成立，受控案例保留確切數目。另一項是既有真實純計畫案例，原始 JSON 顯示 completed，但 checks 的第一個 criterion 少了人員原要求末尾「。」，嚴格核對正確拒絕，產品維持 awaitingEvidence。

修正不是放寬原條件：核對 payload 提供 request-local criterionReferences，保留完整 context.criteria；模型引用短編號，程式只以確切索引回填原文，再走原 validate_assessment 與原生核對。不存在標點容錯、模糊比對、刪要求或猜測證據。未知／重複／缺少編號、改寫文字及與真實條件字串的編號碰撞都有反例。評審 Python 聚焦 **12 項通過**，0.011 秒，`/tmp/maltose-resumption-review-refs-python.log`；更新後完整 Python **515 項通過、無 skip**，44.672 秒，`/tmp/maltose-resumption-full-python-final.log`。

最後另在 store 保存入口鎖住原 answerKind，並加入真正 publication 改寫反例；wire 重送仍保留原值，舊可選欄位未升級為假完成。前述第一輪原生為修正前執行，不能當作最後來源全套結果；原生先補最後守門與兩項真實模型案例聚焦，再進行當前固定來源的完整回歸。


最後原生守門／存儲與兩項真實模型聚焦 **25 案例通過、無 skip**，56.242 秒，`/tmp/maltose-resumption-final-guards-native.log`。固定來源快照共 283 份 production／test／package／test-runner 檔案，SHA256 `7c5326ce1feb4d945076067a3e6cceb28f11acc38c3bc42dcc65179f685594bb`；當前完整原生重跑期間不再改動來源。前景承接尚不涵蓋原正文已送達但核對／ACK 被新問題取代、原工作未保存生成結果的情況；這些與背景跨問答交付仍屬後續工作，不能拿已完成的 ACK 路徑代替全部恢復。


### 最後固定來源結果與下一優先

最後完整 Python **515 項通過、0 失敗、無 skip**，44.672 秒；固定來源完整原生 **234 案例中 233 通過、1 案例失敗（2 個失敗斷言，其中 1 unexpected）、無 skip**，616.730 秒，`/tmp/maltose-resumption-full-native-final.log`。GUI／真實 Main／Codex／Docker 全啟用。新的五項問答後承接案例、既有真實純計畫正反例、來源守門、SIGKILL／重建、全螢幕及跨螢幕均通過；不能寫成整套通過。

唯一失敗為 testConfiguredMainAutonomouslyChartsProvidedHalfYearSurveyWithSeparateMethodsAndSources：模型返回格式正確且已交付的文字與表格，visual=auto，卻省略 chart。隔離原始回覆保留在 `.cache/main-live/maltose-session-3EEF416B-A03F-4ABD-8F1E-A869CA6D5868/config/scope-model-responses.jsonl`，沒有圖表可供原生套用，90 秒等待失敗；不是數值載入／渲染錯誤。原問題確實仍會偶發，下一批優先以持久、無工具的呈現判斷及真實來源欄位／分組核對補齊，不能只重跑到出圖就宣稱修好。

[本批原始摘要](independent-answer-resumption-results.json) 記錄固定來源雜湊、全套／聚焦、失敗及未完成事項。正式／試用包未變，沒有 commit 或部署；目標仍 active。後續仍須補前景交付被問答取代及背景跨問答回收、未知操作核對、排程來源、暫停回顧短語音、全部面板規則、其他自主呈現與真人／正式 App 驗收。


## 2026-11-02 主回答省略圖表時的持久呈現規劃

### 修改與實際範圍

visualPlanningVersion=1 獨立協商需要前景持久交付及原生圖表協定，新來源預設啟用。完整原答案、原人員／版本／回執先保存，再對合適來源表格做一次有界、無工具呈現判斷。foreground_presentations 外鍵指向真正 foreground_results，context 與封存 decision 不可改寫；沒有新增 worker、通知、人員輸入、Memory owner 或第二套產品任務真相。

模型只選 table／column ID、全部必要分組、標題與限制；數值、日期、null 與來源列註記由程式構造。保留機構／方法分系列，禁止省略必要分組、估算缺值、以零補值或平均衝突。支援 ISO 日期／月份的 CSV、TSV、Markdown、百分比與科學記號；混合日期精度、單位不明混用、超額／格式破損或有未解析後續觀察的來源保持文字。只使用真實人員資料或共同 ledger 的完整 read_file 回執，不能把模型敘述、搜尋摘要、Memory 或 KDB 偽裝成原資料。原主模型已有 chart 的相容路徑保持，這批是漏圖後的來源表格補圖，尚不涵蓋全部資料形狀、引擎與面板種類。

原生在呈現模型前核對新輸入、版本、任務、停止／held／cancelled 及執行權。暫時不具執行權時原答案保持 pending，不以未封存圖表發表；意圖封存後才走原 foregroundPrepare／writer／journal 的不可變雜湊與 ACK。新輸入取消舊呈現時仍需走原回報入口保存已發生 Main 事實，不能直接丟掉共同任務回報。所有新圖／文檔預設新增，同 ID 重送只恢復同一份交付，沒有取得舊面板的更新許可。

### 聚焦證據

- 最後 Python 規劃／來源／SQL 聚焦 10 項通過，`/tmp/maltose-visual-canonical-python.log`。包含原答案先保存、純呈現崩潰、封存後 ACK 遺失不重選、偽造欄位／分組／數值、跨對話／不可變、來源不足、預算及新輸入／暫停；完整資料／比例／日期不被正規化為未提供的數據。
- 最後原生 6 案例全部通過、無 skip，68.138 秒，`/tmp/maltose-visual-canonical-native.log`。配置真實主模型包括原自主圖表、強制主回覆省略 chart 仍建立新原生圖表、明確只用文字不開圖；逐月／系列核對所有來源數字、null、方法分組、來源註記及新增面板數。另一案驗證前景／背景／未知 ACK 交叉流程仍完成。
- 同輪真正 SIGKILL 在無工具模型中、意圖封存後尚未原生接納、圖／文檔寫入後 ACK 前三點；整個 native store／runtime／panel manager 重建。原工作模型計數保持；只有未封存的呈現選擇多一次，已封存的不再呼叫，原 producer 不改成新 delivery session，圖／文檔與訊息各一份，沒有補播。
- 新人員輸入在呈現模型前到達：舊圖不發表、不呼叫呈現模型；原 Main outcome 寫入原產品任務，新目標有獨立要求／任務。原工作事實沒有因取消視圖而遺失。

語音測試為受控輸入／事件，沒有真人收音與聽感證據。所有調查資料均明確虛構，不替原政治調查的來源或數值背書。

### 中途失敗與修正

最初 Python 10 項有 5 個失敗斷言、1 error，`/tmp/maltose-visual-python-focused.log`。fixture 將 model.complete 設為布林而非 callable，程式正確降級文字、沒有進入假模型；修正 fixture 後通過，沒有放寬欄位／來源檢查。之後也補強暫停時保持已保存原文且不以舊變數覆蓋後來的有效圖表正文。

首次原生恢復 2 案例中的 1 案失敗、7 個失敗斷言、無 unexpected，34.475 秒，`/tmp/maltose-visual-recovery-native.log`。fixture 漏 import time，預定停在模型中的 hook 未真正停住；又誤用 publication ID 而非原 message ID 尋找聊天。修正 hook／斷言後，三個真實崩潰點通過；未刪除原工作／模型／訊息去重檢查。明確文字反例第一次有 2 個失敗斷言（1 unexpected），10.992 秒，`/tmp/maltose-visual-text-only-native.log`：沒有圖表已成立，fixture 卻強制一定有新 document；改為允許聊天或新 document，但仍禁止圖表與其他額外面板後通過。

第一輪完整原生 **237 案例中 236 通過、1 案失敗（2 個斷言，其中 1 unexpected）、無 skip**，561.914 秒，`/tmp/maltose-visual-full-native.log`。交叉 fixture 等待 transient outcomes.count==1；Main 與獨立 assessment 已有兩條時就會錯過。改為等待真正 Main 回報、原生交付與需要的核對事實，不改變最終完成／工具／ACK 條件。`/tmp/maltose-visual-stable-startup.json` 真正原生狀態為 mainReports=1、assessments=1、outcomes=2，尚未釋放後續 worker；修正後交叉案例與補圖／恢復 4 項通過，55.669 秒。

其後完整原生 **237 項通過、無 skip**，560.293 秒，`/tmp/maltose-visual-full-native-final.log`。這輪在最後來源事實守門與新增反例之前啟動，不能冒充最後固定來源證據。最後守門修正已通過上方 6 案例與完整 Python **525 項通過、無 skip**，43.659 秒，`/tmp/maltose-visual-full-python-final.log`；當前固定來源的完整原生結果見下方最終結論。

### 最後固定來源與交付狀態

固定來源共 285 份 production／tests／package／test-runner 檔案，SHA256 `05a2e80887faa2b168e39eca8faade1b4c67d0e5aaf372289ae087d2b7f1ffeb`，完整原生確認中不再修改程式。AST 227 份 Python、既有驗證 JSON、已改計畫本機連結及 git diff --check 通過；正式 build 15 與試用 build 17 的執行檔雜湊保持不變，未封裝、部署或 commit。

整體仍缺前景交付／背景回收跨問答的其餘情境、未知操作核對／明確 retry、排程來源、Codex 暫停短語音、所有面板更新許可、其他自主輸出／偏好、真人及正式 App 驗收。此批不宣告 P0–P5 或整體目標完成。


最後當前固定來源完整原生 **238 案例全部通過、0 失敗、無 skip**，568.030 秒，`/tmp/maltose-visual-canonical-full-native.log`；完整 Python **525 項通過、無 skip**，43.659 秒。GUI／真正配置 Main／真正 Codex／Docker 全啟用，包含全部補圖／明確文字、原工作事實、新輸入、崩潰／重建與全螢幕／跨螢幕回歸。來源雜湊在最後全套期間保持一致，227 份 Python AST、JSON／Markdown 本機連結及 git diff --check 通過；[本批原始摘要](durable-visual-planning-results.json) 保存直接結果與中途失敗。

正式 build 15／試用 build 17 雜湊不變，沒有封裝、部署或新 commit。這次完成漏圖後的有界原資料表格呈現路徑，不宣稱所有來源形狀／引擎／面板、真人語音或整體 P0–P5 完成；目標保持進行中。

## 中文年月來源與原生月份座標（2026-11-02）

原始 CSV／TSV／Markdown 日期欄新增明確四位年份的中文年月／年月日及年在前的斜線格式。呈現模型仍只選欄位；程式由保存的來源值建立正規化軸標籤，原始日期字串及來源列完整留在 context 與點備註。不推測缺少年份、不把月份轉為調查日、不接受模糊月日、日期區間或混合精度。日期別名先歸一核對，衝突不平均。原生月份軸以 UTC 曆月座標保留時間間距，資料列／標籤不補造。

| 檢查 | 直接結果 |
| --- | --- |
| Python 聚焦 | 14 項通過，0.147 秒，包含新增中文半年、排序與別名、非法／模糊日期、同一圖斷線重送 |
| Python 完整 | 529 項通過、無 skip，42.954 秒，Docker 啟用；`/tmp/maltose-calendar-full-python.log` |
| 實際主模型＋原生呈現聚焦 | 11 項通過、無 skip，17.955 秒；`/tmp/maltose-calendar-combined-focused-native.log`。強制主回覆省略 chart，呈現模型以原中文月份資料自主補四系列六月份圖；原數值、方法、來源、月精度及新建圖／文檔逐項核對。另含一月／六月的 151 日座標間距、原標籤／備註與無新增觀察 |
| 中途失敗 | 初次新增實際主模型案例有 1 個失敗斷言，15.967 秒；`/tmp/maltose-calendar-focused-native.log`。舊 helper 把全部來源固定當成每月一號，實際月資料已是正確 YYYY-MM；修正 helper 依來源精度核對後，單案 11.776 秒通過，再跑上列 11 項，不放寬來源數字／分組／新建／去重條件 |
| 完整原生 | **240 項全部通過、無 skip**，577.725 秒；GUI／實際 Main／Codex／Docker 全啟用。`/tmp/maltose-calendar-full-native.log`；五份本批程式／測試檔的全套前後雜湊相同，227 份 Python AST、JSON 與 git diff --check 通過；[本批原始摘要](calendar-source-presentation-results.json) |

正式 build 15 與試用 build 17 執行檔仍保持先前雜湊；沒有封裝、部署或 commit。直接工具的全部更新許可與完整網頁／非表格資料的自主呈現仍待實作，不能把本批來源格式修正當成整體 P0–P5 完成。


## Main／Codex 直接面板操作守門（2026-11-02）

來源合約新增 panelPolicyVersion=1，現行產品預設啟用，模型工具仍為原來 36 個。Main 的 source 由 context-local invocation、原人員 input 與入場時 control epoch 產生；Codex 由原生已驗證 connection／task／turn／paused lease／dispatch input 產生。原生重讀真正人員紀錄、最新要求與執行權；模型參數不能自行宣稱 update 或提供權限 source，私有成果 publisher 保留原 writer 守門。

所有公開 mutation 在既有 WorkspaceAgentInterface model 與檔案 transfer 之前進入 NativePanelPolicy。新建面板可在同 invocation 初次填入內容／內部視圖；焦點、關閉、移動或儲存仍需對應明確人員要求。舊面板的無工具意圖判斷必須附原指令中的操作與目標片語，原生核對 stable targets、實際來源與 revision。陌生動詞再經獨立無工具分類，能接受補充／潤飾等自然語言，不能把純讀取當成改寫。模型無法自行輸出 semanticActionVerified，主機程式僅在該次動作核對成功後附加。

人員輸入接納時即保存選取、來源窗口與 model revision，防止首工具之前的編輯被忽略。鍵盤輸入直接使用其 composer 窗口，避免 WindowServer 焦點通知晚到而誤用另一個窗口；已關閉的來源窗口不能轉用其他窗口。指令後改選／編輯、評估期間變動、關閉、新指令、交接或 runtime 重啟均會停止過期操作。範圍內已知由本 Agent 完成的排列可延續，後來人員調整的排列仍受保護。

既有面板的更新 claim 在真正寫入前透過原 conversation store 的單 writer 交易保存；重開後不可刪除、改綁或重用為另一個 invocation 的永久許可。權限 cache 以完整命令與參數雜湊區分，不能將一般開檔／顯示線條的許可套用到另一組參數。捨棄 dirty 流程圖另需人員原文片語；FileService root／CAS 與 export／write／saved 分流保持原邊界。chart 資料更新保留可沿用的 zoom／pan／系列可見性／填色；流程圖資料更新保留可沿用視圖，失敗時不做假恢復。

原生模擬逐項覆蓋全部公開 mutation 的拒絕，以及同次建立填入、人員首工具前／評估期間編輯、ABA revision、deictic 改選、無來源、偽造原文、人工 JSON、關閉、重啟快照、dirty 捨棄、不同參數 cache 與先新增再排列。另有實際 source callbacks／主模型與真正 Codex 的證據；[本批直接結果](panel-operation-policy-results.json) 保存日誌、來源快照、範圍與中途失敗。

| 檢查 | 直接結果 |
| --- | --- |
| 完整 Python（最後固定來源） | **540 項通過、無 skip**，47.532 秒；Docker 啟用。`/tmp/maltose-panel-policy-canonical-full-python.log` |
| 原生共同新入口＋真實 Codex／Main 聚焦 | 8 項通過，35.853 秒；`/tmp/maltose-panel-policy-actual-focused.log`。自然語言十個案例的後續版本及 composer 來源另在下列聚焦與最終全套核對 |
| 自然語言／composer 來源 | 7 項通過，24.253 秒；`/tmp/maltose-panel-policy-composer-source-focused.log`。含真實配置模型的新增／否定／引號／明確更新／單純讀取／顯示／歧義／選取與補充結論；資料值與視圖逐項核對 |
| dirty／參數／同次排列邊界 | 9 項通過，3.977 秒；`/tmp/maltose-panel-policy-dirty-final-focused.log`。最後補上已關閉 composer 的反例後，以最終全套重新驗證 |
| 中途完整原生 | 248 項通過，613.868 秒；`/tmp/maltose-panel-policy-full-native.log`。後續補強期間來源有變動，不能冒充最後固定來源結果 |
| 最後固定來源完整原生 | **251 項全部通過、無 skip**，580.298 秒；GUI／實際 Main／Codex／Docker 全啟用。`/tmp/maltose-panel-policy-canonical-full-native.log`；291 份程式／測試／runner 的全套前後雜湊一致，229 份 Python AST、驗證 JSON、本機連結與 git diff --check 通過 |

### 中途失敗及處理

第一次原生 4 案例中的人工 JSON fixture 缺少 schemaVersion，2 個斷言失敗；修正 fixture 後保留原解碼要求。Codex 舊 fixture 的啟動委派未保存真實人員 input，嚴格新來源檢查拒絕；現在先記錄其原 voice input／ID 再委派，未把模型委派當成人員許可。

第一輪實際模型曾把「整理新的研究結果」判為允許覆寫 notes，理由卻說應另開面板；這是本批真正發現的錯誤，後續以來源操作／目標片語、原生核對與陌生動作獨立分類修正，不放寬成接受模型 allow。顯示／放大初次被模型誤解成鍵盤 focus，現已明確提供既有原生命令語意。原歧義 fixture 一張圖其實有唯一精確名稱，後續改為兩張同名圖以測真正歧義，仍嚴格拒絕指向別張的命令。

多窗口來源中，模型已正確選到原選取 chart，但原生讀到其他 screen 的焦點；composer 現直接供給其窗口，不再以稍後 OS key-window 推測。最後 dirty 測試發現已拒絕的操作也恢復相同 zoom／pan，造成假 revision 變化，已修成成功後才恢復；保留兩次不同 discard flag 都經核對的斷言。新增 Python fixture 有過括號語法錯誤，修正後才執行上列最後來源全套。

這批仍非完整 P3／P0–P5 驗收。其餘面板的自然語言正向與跨窗口組合、持續更新許可、known-failed／unknown 副作用核對與原授權接續生命週期、其他呈現／偏好及真人／最終 App 驗收仍需完成。正式 build 15／試用 build 17 未封裝替換，沒有新 commit 或部署。

## 2026-11-02 舊面板回執與原任務的無變更失敗接續

此批在 `panelOperationVersion=1` 協商下使用原生 conversation store 記錄既有面板操作的 prepared／terminal response／接收 ACK。Main source 綁原任務要求與計畫；Codex source 使用真正 dispatch execution 版本。實際 held／cancelled／replan 會在 writer 拒絕，不能以目前版本洗過舊 turn。bridge 移除私有 ACK token 後才把回覆交模型，ACK 丟失只補 ACK，已知成功不重送修改。

原生 completed 只代表 UI 操作已成功，不替代原產品任務核對。歷史與實際讀回分開；人員修改、writer 重建或不完整觀察的瀏覽器／聊天／形象狀態不宣稱仍符合舊狀態。真正已改動後才失敗會保存 uncertain，回覆 outcome_unknown／operationID；prepared／uncertain 不 ACK、不自動重試。只延續同原任務／版本／runtime、已收到的 failedNoChange（或尚未開始任何 UI 的 v1 claim）到已接納 work continuation／新 Codex execution，且原快照與人員修改 guard 仍有效。

聚焦最終來源：10 項原生通過、無 skip，13.544 秒；`/tmp/maltose-panel-operation-canonical-focused-native-final.log`。包括真實 Main／Codex 接線的三種任務狀態、寫入後失敗、ACK 丟失及私有 token、重啟後歷史與現狀分離、不可變 journal 與所有 target claim、未協商相容性。真實前景接續管線以受控模型跑初次無效 CSV→無改動畫面→ACK→同一原任務續做有效 CSV→讀回核對→任務完成，不新增人員 input／要求或假 worker。這不是實際提供者自主修復的單獨驗收。

中途結果如實保留：`/tmp/maltose-panel-lifecycle-task-states-native.log` 因 fixture 嘗試修改不可變 plan.steps 而編譯失敗，改為重建計畫；後續 2 項狀態接線通過。`/tmp/maltose-panel-operation-focused-native.log` 因 fixture 直接比較不具 Equatable 的 CSVLineChartData 編譯失敗，改為逐項核對原欄位／日期／數字；後續 5／9 項及上列最後 10 項聚焦通過。沒有放寬來源、資料或重試守門來讓測試通過。

完整最後來源的 Python／原生回歸正在執行，尚不能以聚焦結果宣稱全套通過。來源已封存於 `/tmp/maltose-panel-operation-canonical-source.json`，293 份程式／測試／runner；後續只更新文件／結果，結束時再次逐檔核對。這批沒有封裝、替換 App、提交或操作正式任務資料。

### 完整回歸發現：面板授權判斷誤做資料可用性判斷

第一輪固定來源的完整原生回歸中，實際提供者拒絕「把我目前選取的這張折線圖更新為新資料，保留縮放和已隱藏的線條」。原生快照在來源 screen 確有唯一 selected chart，其他同類圖表未選取；模型卻以「沒有在指令內提供 CSV」與名稱不能唯一匹配為理由 deny，造成正向更新失敗。此失敗保留於 `/tmp/maltose-panel-operation-canonical-full-native.log`；實際 provider 決定與人員快照保留在隔離 fixture `.cache/main-live/maltose-session-FA64FA1E-628D-4135-AAC0-4B2D0A12BF27/config/`。原內容在拒絕時未被改動。之後測試中的手動新 scope 再評估曾 allow，故造成預期拒絕的連帶斷言失敗，不能以後一次 allow 宣稱第一次已成功。

修正方向是明確區分授權／指向與資料可用性：原生另提供按 kind 與來源 screen 計算的當時選取／焦點事實，並明示唯一 deictic 指向優先於同類圖表的其他名稱；這些事實不授權任何動作。實際 action／target 原文、人員來源、歧義、否定／引用、revision、版本及 writer gate 仍保留；資料仍由真實工具及成果證據核對，不能因人員指令沒附 CSV 而把已授權更新誤判成未授權。最後來源與回歸在修正後另記，不冒充原失敗來源已通過。

第一輪完整回歸最後為 261 案例／260 通過／1 案例失敗（5 個斷言、0 unexpected）、無 skip，637.917 秒；原圖表自主呈現的四個實際提供者案例均通過。修正後聚焦 19 項通過、無 skip，30.154 秒（`/tmp/maltose-panel-operation-intent-focused-native-final.log`）。新增快照單元 fixture 首次讀到 OS active screen 而不是輸入窗口，5 個斷言失敗；改用實際 submitText(from:) 接納來源後通過，原模型十個案例在該次與最後聚焦均通過，沒有跳過負例或放寬 writer。

最後來源改用 `/tmp/maltose-panel-operation-final-source.json`（293 份程式／測試／runner，SHA256 `b929cd370b999abd83e227ffb62094a3e4612728776477300819fc5a4aeeb37f`，sorted compact JSON manifest），完整 Python／原生分別寫入 `/tmp/maltose-panel-operation-final-full-python.log` 與 `/tmp/maltose-panel-operation-final-full-native.log`；完成前不宣稱全套通過。原來源 manifest 另保留於 `/tmp/maltose-panel-operation-first-full-source.json`。

### 第二輪完整來源的 fixture 問題與最後重驗

第二輪完整原生 262 案例中，261 通過、1 個新增 deictic 快照單元案例失敗（4 個斷言、0 unexpected），無 skip，657.023 秒；日誌 `/tmp/maltose-panel-operation-final-full-native.log`。實際提供者原十個自然語言案例、圖表與其餘產品案例均通過。新增 fixture 先由 connect() 在預設 OS screen 保存 human 快照，再試圖由 submitText(from:) 改綁同 ID；產品的不可重綁 guard 正確保留第一次快照，因此全套的窗口順序暴露 fixture 錯誤，不能將其當作產品允許改寫快照的理由。

修正只改 NativePanelPolicyTests：connect 可選擇不先捕捉輸入，第一次快照直接從真正 composer 接納；之後改選與同 ID 再捕捉仍不得重寫原指向。17 項面板／回執聚焦通過、無 skip，7.362 秒，`/tmp/maltose-panel-operation-composer-fixture-focused-final.log`。修正過程另有一次 helper 簽名替換未命中而編譯失敗（`/tmp/maltose-panel-operation-composer-fixture-focused.log`），補正明確參數後才跑上述聚焦。

第二輪後只有上述 Swift fixture 變更，Python 與產品程式逐檔雜湊未變，故完整 Python 544 項／45.865 秒仍對應相同 Python 來源，不為純 Swift fixture 重跑 Python。新來源 manifest 仍存 `/tmp/maltose-panel-operation-final-source.json`，293 份、SHA256 `b85b4c9ff760d03e8252d8642969da9bf98646f791162e0c95ce68d16d9c8472`；第二輪 manifest 另存 `/tmp/maltose-panel-operation-pointing-source.json`。最後完整原生寫入 `/tmp/maltose-panel-operation-verified-full-native.log`，結束前不宣稱全套通過。原一／二輪失敗完整保留於 [直接資料](panel-operation-lifecycle-results.json)。

### 冷啟動恢復與內部 work 請求（最後補強）

第三輪來源 `b85b4c9ff760d03e8252d8642969da9bf98646f791162e0c95ce68d16d9c8472` 完整原生 262 案例／261 通過／1 個實際 Main 接續案例逾時（2 個失敗斷言、其中 1 unexpected）、無 skip，777.189 秒。`/tmp/maltose-panel-operation-verified-full-native.log` 及隔離 fixture `.cache/main-live/maltose-session-EE6557DD-A17A-47CD-8846-B66D4835E631/` 保存真實結果：八次 work 只重述 second.txt 未取得，沒有呼叫可用讀取工具，最後進入有界 clarify。不能靠再跑到模型選工具來冒充已修正。

接續的模型 context 先前以最後一則 assistant 資料訊息傳入；現在使用明確的內部 API input data envelope，system 同時要求 work 先處理可讀來源的實際缺口，不把先前「尚未讀取」報告當成存取拒絕。這是模型呼叫資料的 role，不是產品層的新 human input：source／trustedAsInstruction=false、原 input／要求／計畫版本、工具及身分 guard 保留，沒有 append 人員 journal、聊天歷史、Memory 或假 worker。單元實際工具循環驗證原身分／_session_messages 不變；原生實際配置 Main 現在只補讀第二份來源並綜整，仍須全套驗證，不把單次實測當作無條件穩定。

另外靜態審查發現原 journal「重開」測試只重開同一 CodexTaskStore 物件，未覆蓋全新物件的冷啟動。補測真正的新物件後，3 個案例有 2 個 unexpected failure，`/tmp/maltose-panel-operation-fresh-store-reproduction.log`：已保存 terminal row 被當作全新寫入，錯誤要求 phase=prepared，可能阻擋 App 讀回合法紀錄。現在 open 明確以 restoringSnapshot 驗證既有完整 snapshot；只有新的 live transaction 仍必須先插入 prepared，且終態、ACK、來源與 claim 不可改寫。歷史 retry claim 依完整已保存 operations 驗證，不跳過過去 no-change proof。全新物件正向恢復已成功／失敗／prepared／uncertain，ACK 原回執後仍拒絕移除／倒退歷史；偽造「完成後再用原修改許可」的 snapshot 仍拒絕。

最後聚焦原生 **20 項通過、無 skip**，22.730 秒，`/tmp/maltose-panel-operation-recovery-focused-native.log`；含真正 Main 接續、CSV 原任務修復、8 個原 store 案例及 10 個操作 journal 案例。Python 接續 8 項通過，0.052 秒，`/tmp/maltose-panel-operation-internal-request-focused-python.log`。最後來源 293 份、SHA256 `61880589429a567f6c748726b8067b9945f27abfe2b356c0765bfe0656fec316`，manifest `/tmp/maltose-panel-operation-final-source.json`；相較第三輪只有 CodexTaskStore、TaskBrain 內部請求及兩份測試變更。完整 Python／原生重驗分別寫入 `/tmp/maltose-panel-operation-recovery-full-python.log`、`/tmp/maltose-panel-operation-recovery-full-native.log`，完成前不宣稱最後來源全套通過。

### 唯讀複核與重送去重的驗收分開

第四輪固定來源 `61880589429a567f6c748726b8067b9945f27abfe2b356c0765bfe0656fec316` 完整原生 265 案例／264 通過／1 個斷言失敗、無 unexpected／skip，675.610 秒；`/tmp/maltose-panel-operation-recovery-full-native.log`。新增冷啟動與原先未取得來源的 Main 案例均通過。唯一失敗是獨立問答後的實際 Main 合法多讀一次 first.txt，來源讀取總數為 3、fixture 卻固定要求 2；完整真實回執保留於 `.cache/main-live/maltose-session-563E8444-76BC-4A03-AEA2-07186E0B330E/tasks.json`。此為新接納 work scope 的唯讀複核，不是崩潰／ACK 恢復重放修改，沒有改動來源，最終完整證據與任務完成均正確。

原人員只要求讀兩份來源與綜整，沒有要求只讀一次；不應以固定模型工具路徑作為產品需求。兩個實際模型案例改為核對 observed／passed FileService receipt 的完整必要來源集合、原檔逐字不變、同一產品任務／版本／原人員輸入、真正完成證據與交付內容。受控原工作、SIGKILL／generated／ACK 重送仍維持確切執行次數與副作用不重放的原斷言。未放寬身份、原範圍、held／cancelled、未知副作用或完成證據門檻，也沒有修改產品程式來配合測試。

最後四項實際／受控接續聚焦通過、無 skip，30.630 秒，`/tmp/maltose-panel-operation-read-proof-focused-native.log`。其後只改 AgentSessionCoordinatorTests，產品與 Python 來源逐檔相同；完整 Python 544 項／45.912 秒仍對應當前相同 Python 來源。最後 manifest `/tmp/maltose-panel-operation-final-source.json`，293 份、SHA256 `0c2e2cfc791ca78d789d9c58ec9b009cdbad33b2560968d15d1fde30f8157708`；第四輪 manifest 另存 `/tmp/maltose-panel-operation-recovery-source.json`。當前完整原生寫入 `/tmp/maltose-panel-operation-closing-full-native.log`；完成前不以聚焦或上一輪 264 通過冒稱全套通過。

### 本批最後結果（不宣稱完整原生全綠）

| 檢查 | 最後直接結果 |
| --- | --- |
| 完整 Python | **544 項通過、無 skip**，45.912 秒；`/tmp/maltose-panel-operation-recovery-full-python.log` |
| 最後完整原生 | **265 案例／264 通過／1 個全螢幕啟用案例失敗（7 個斷言、0 unexpected）、無 skip**，696.767 秒；GUI／實際 Main／Codex／Docker 全啟用，`/tmp/maltose-panel-operation-closing-full-native.log` |
| 同來源全螢幕補驗 | **1 項通過**、無 skip，4.714 秒；沒有改程式或放寬 AppKit native fullscreen 斷言，`/tmp/maltose-panel-operation-fullscreen-activation-check.log` |

最後完整回歸唯一失敗是 WorkspaceNativeTests.testAutomaticNativeFullscreenUsesSystemSpace：診斷 active=false／key=false／native=false、awaiting-activation；其後唯讀裝置檢查 IOConsoleLocked=false，同來源單獨補驗取得真正 AppKit fullscreen 並通過。尚未確定整套時的啟用不穩定根因，不能把補驗冒充整套全綠。其餘 264 案例包括本批任務／回執／冷啟動／實際模型接續與圖表均通過。

全套與補驗前後 **293** 份程式／測試／runner 逐檔雜湊一致，SHA256 `0c2e2cfc791ca78d789d9c58ec9b009cdbad33b2560968d15d1fde30f8157708`；229 份 Python AST、驗證 JSON、相關 Markdown／本機連結及 git diff --check 通過。正式 build 15、試用 build 17 執行檔保持原雜湊，沒有封裝、替換 App、部署或新 commit；測試使用隔離資料。最後可核對摘要見 [直接結果](panel-operation-lifecycle-results.json)，所有前輪失敗與判斷均保留。

下一步先補公開研究完整原文與可靠數據對應，接入既有持久圖表規劃；搜尋摘要不冒充完整調查表。另仍需處理一般未知操作的人工核對／明確重試、新面板與外部儲存階段回執、跨問答背景成果／其餘面板與持續更新許可、全螢幕穩定性及真人語音／最終 App 驗收。整體目標保持進行中。


## 2026-11-02 公開原文讀取與自主半年圖表

本批補的是研究來源到呈現的缺口，沿用現有工具、持久呈現規劃與原生圖表，不重做 UI。`publicWebSourceVersion=1` 依賴 workflow／foreground result v1，Main 自有 `read_web_page` 提供無登入公開 HTTP(S) 靜態文字、同一 sourceID 的不可變分頁及完整原表格。原 URL／最終 URL／取得時間／原回應與文字／表格 SHA256 隨實際工具觀察保存；有界容量不足、PDF、動態 JS、合併／未閉合表格明確回報，不以片段冒充完整研究。資料不進 Memory／KDB，不建立假 owner；快照限定實際 input，模型參數不能改綁。

網路逐跳驗公開 DNS 地址並固定連到已核對 IP，TLS 檢查原主機；不讀代理、Cookie 或登入資訊。新增測試驗私人／特殊地址、混合 DNS、重新導向、錯誤長度、逾時、快照過期／跨來源、完整表格與雜湊失真。實際 production transport 另讀 `https://www.python.org/about/` 成功，41,265 原始 bytes、三頁文字、零表格，valid_receipt=true；這只驗 DNS／TLS／來源格式，不能冒稱讀完所有頁或驗證民調。

三條原生整合都使用真正 stdio runtime／native writer／既有面板：實際主模型自行讀表出圖；受控 primary 刻意漏圖後由真正呈現模型補圖；真實產品任務依讀取及交付回執完成核對。測試表格為本機虛構資料，使用 test-only transport 將指定 public fixture 地址映射到隔離 HTTP server，產品沒有允許私人位址的模型參數。六個月份、A／B 方法、四月缺值與來源備註都留在圖中，原圖逐值不變。無產品任務問答不因此建立假任務。新 sourceRead 證據區分整份回應已下載、文字頁已讀、完整表格已讀，不把出版者主張當成獨立真實性證明。

### 固定來源與中途失敗

最初聚焦 14 項 Python／0.635 秒通過，`/tmp/maltose-public-source-scope-focused-python.log`；新原生三整合加兩 receipt 案例 5 項通過、24.499 秒，`/tmp/maltose-public-source-canonical-focused-native.log`。早期 HTTP/1.0 最後 chunk 後 socket 已關閉而再次設定 timeout，已以 response.isclosed 守門修正；超時的 SocketTimeout／watchdog race 另做明確 TimeoutError 分類。受控答案曾缺趨勢敘述；修正 fixture 為 A +3／B 可觀察值 +4，仍不推論四月；評審曾把 chartApplied 誤當覆寫舊圖，產品新增真正 publication_owned_panels_only／實際新成果 ID 回執，未放寬完成門檻。

第一輪來源 297 檔／231 Python AST，manifest `/tmp/maltose-public-source-final-source.json`，SHA256 `8a175e8b93bfc59867f118dc95c3413135e7f32ac8e708d93fc0cff3641fe962`。完整 Python **558 項通過、無 skip**，46.566 秒，`/tmp/maltose-public-source-final-full-python.log`；完整原生 **270 案例／269 通過／1 失敗案例（2 個失敗、1 unexpected）、無 skip**，792.916 秒，`/tmp/maltose-public-source-final-full-native.log`。這輪舊全螢幕啟用案例通過，唯一失敗是新真實 Main 自行讀來源案例：模型未呼叫 read_web_page，從 `.invalid` 拼字推斷無法讀取，直接要求提供原文，未取得表格或圖。保存模型回覆位於 `.cache/main-live/maltose-session-28DC96CB-328E-4F10-8918-9BEFB1058B8A/config/public-source-real-responses.jsonl`；不能說是圖表 writer 已成功。

修正只改 TaskBrain 串流／非串流的共同來源讀取指示：已授權公開來源先嘗試可用讀取工具，再以真實回執說明不可讀，不憑域名或上下文缺少原文認定失敗、不無故要求人員再次確認。保留 `.invalid` fixture、所有 production 地址／身分／任務／版本守門及模型自主工具選擇。修正後聚焦原生 **5 項通過、無 skip**，28.893 秒，`/tmp/maltose-public-source-read-attempt-focused-native.log`。

最後來源 manifest `/tmp/maltose-public-source-read-attempt-source.json`，297 檔／231 Python AST，SHA256 `05297026f359879a9d6118121dd8ad05bb8184f2f43df95f9e02d63d82eab151`；與第一輪只有 `runtime/maltose/agent/taskbrain.py` 不同。最後完整 Python **558 項通過、無 skip**，47.098 秒，`/tmp/maltose-public-source-read-attempt-full-python.log`。原生 `/tmp/maltose-public-source-read-attempt-full-native.log` 重驗中，完成前不宣稱全綠。原始數據與最後結果見 [直接摘要](public-web-source-results.json)。

正式 build 15 與試用 build 17 App 執行檔 SHA256 分別仍為 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`、`7c5b4d6cbf4efdc9de3a385af499fb2877ec4dcd887ee9aa9a24adca7bdfe301`。本批沒有封裝／部署／commit 或正式使用者資料修改。未知操作人工核對、插入問答期間背景承接、持續更新許可、其他呈現、真人語音及正式切換仍待完成，整體目標保持 active。


### 收尾證據引用的實際模型失敗與修正

第二輪固定來源完整原生 **270 案例／269 通過／1 個失敗案例（2 failures，1 unexpected）、無 skip**，791.526 秒，`/tmp/maltose-public-source-read-attempt-full-native.log`。公開來源三整合與舊全螢幕測試通過；唯一失敗是 `testConfiguredMainModelActuallyAssessesBackgroundFileServiceEvidence`，背景成果已有兩份完整 read_file 回執，但模型回傳第一個 witness ID 時混入第二個的後綴。精確驗證拒絕該 key 並保留原成果，未將不存在的證據當成完成。

直接資料在 `.cache/main-live/maltose-session-947F89A5-1A80-496E-AECC-B56CA10510FF/`：tasks.json 保留實際 `tool:5b3aea8cdae24566ba0a3b668620bb0a` 及 `tool:9bbd4c3d79314966a09a3e274174abac`；`config/worker-assessment-response.json` 記錄模型把首 key 寫成 `tool:5b3aea8cdae24566a09a3e274174abac`。這不是缺少來源或人員決定，不該增加人員待確認事項。

沿既有 evidence 短引用機制，把門檻從大於 64 改為大於 32 字元，覆蓋這類 tool UUID。模型只引用當次提供的短 key；collision-free 產生與原證據允許清單維持，先驗證再精確還原原始 key，沒有 fuzzy matching 或自動原諒錯字。新增回歸保留原 context、兩份原 key 的回轉、與既有短 key 碰撞，以及抄錯、直接偷用未提供長 key、未知 alias 的拒絕。Python 核對＋公開來源聚焦 **27 項通過、無 skip**，0.641 秒，`/tmp/maltose-public-source-short-witness-focused-python.log`。第一次測試命令誤把絕對檔案路徑當模組名稱，未載入測試；改用實際 module path 後取得上述結果。最後原生聚焦及全套仍在核對，以後續直接結果為準。


短引用修正後，原背景評審與全部新公開來源案例／receipt 的原生聚焦 **6 項通過、無 skip**，27.963 秒，`/tmp/maltose-public-source-short-witness-focused-native.log`。最後固定來源 297 檔／231 Python AST，SHA256 `4c88d8437a32516db5a015d81eab6af194517988fc5540bf6435bdd837dffb1a`，manifest `/tmp/maltose-public-source-short-witness-source.json`。最後整套於 `/tmp/maltose-public-source-short-witness-full-python.log`／`/tmp/maltose-public-source-short-witness-full-native.log` 執行；[直接摘要](public-web-source-results.json) 持續保存各輪，較早的 Python 或原生結果不冒充這份最終來源。


### 有界修整無效核對回覆

第三輪固定來源 `4c88d8437a32516db5a015d81eab6af194517988fc5540bf6435bdd837dffb1a`：完整 Python **559 項通過、無 skip**，47.832 秒；完整原生 **270 案例／269 通過／1 個真實 Codex 收尾案例失敗（2 assertions、0 unexpected）、無 skip**，693.446 秒。直接結果為 `/tmp/maltose-public-source-short-witness-full-python.log`、`/tmp/maltose-public-source-short-witness-full-native.log`。公開來源圖表、背景短引用及全螢幕案例均通過。

失敗不是測試未執行或證據已過期：`.cache/main-live/maltose-session-F3E8FCF9-9381-4884-85D9-95CA6D9B4362/assessment-responses.jsonl` 顯示模型已引用正確 e4／e7 並判完成，但第二個 check 的欄位錯寫為 `e4videnceIDs`。原 guard 正確拒絕額外欄位，完整 tests／workspace 證據仍在 tasks.json。另一次較新的多回合案例也有合法 partial；它是不同案例，不可混作本次原因。

新增最多一次、禁用工具的核對回覆修整：仍提供完全相同的原始 context／允許證據／要求版本與完整結果；上一份無效回覆與 validationError 只作不受信任資料。重新完整評審後仍走相同 allowlist／schema／native 來源守門，不直接改拼字、不替模型選證據、不修改 ProductTask 或重新執行原工作。再次無效、超出預算或 provider 失敗保持具體 partial；AutonomyPaused 原樣向外傳遞，沒有新的人員 input、worker、身分或授權。

Python 核對／來源聚焦 **28 項通過**，0.660 秒，`/tmp/maltose-public-source-assessment-repair-focused-python.log`；涵蓋錯欄位、錯 witness、第二次仍無效、同一不可變來源與 retry 期間暫停。加入修整後既有原生聚焦 **7 項通過**，63.205 秒，`/tmp/maltose-public-source-assessment-repair-focused-native.log`，含真實 Codex 收尾。再新增強制首次回覆錯欄位的真正 stdio／原生任務案例，驗證真正配置評審的第二次回覆修復、只讀一次來源、一筆人員 input 與同一 ProductTask。最後聚焦／固定來源完整回歸以後續結果及 [直接摘要](public-web-source-results.json) 為準。


新增強制錯格式的第一次聚焦共 8 案例／6 通過／2 失敗案例（4 failures／2 unexpected），192.072 秒，`/tmp/maltose-public-source-final-repair-focused-native.log`。第一個案例的第二次評審已修成有效 partial，因其認為負面限制還缺證據；fixture 卻強迫格式修整後必須 completed，這會混淆格式有效與任務已完成。已改該專用測試要求有效、帶實際證據的 assessment，允許正確保留 partial；仍檢查同一 ProductTask／單一人員 input、來源恰讀一次、評審恰兩次、原圖未改及未建立 worker。產品完成條件與其他 planned 案例的 completed 斷言沒有放寬。

另一個真實 Main 案例在 `.invalid` 網址上再次只回覆尚需讀取、沒有呼叫工具；保存於 `.cache/main-live/maltose-session-2DAF5818-981F-436D-996B-60F54BC83080/config/public-source-real-responses.jsonl`。公開來源 fixture 改用文件示例域名 `http://example.org/survey`，仍由隔離 transport 精確映射到本機測試 HTTP、明示虛構資料，產品 DNS／私網守門不變。這避免用特殊不可解析域名測試公開來源時混入模型先驗；不能因此宣稱一般模型永遠不會過早回覆 partial。正式研究中這類過早停止仍須沿一般任務承接繼續驗收，不以換 fixture 冒稱已完全解決模型自主性。


第二次新增反例聚焦共 8 案例／7 通過／1 失敗（2 failures／1 unexpected），122.755 秒，`/tmp/maltose-public-source-final-repair-canonical-focused-native.log`；實際 Main 在 example.org synthetic mapping 上讀取／出圖通過。唯一失敗來自 fault injector 先索引 checks[0]，但第一次有效 partial 的 checks 可為空，於 fixture 拋 IndexError 而未把回覆交給產品解析。已改破壞頂層 checks 名稱，不依賴判斷結果或列表長度；第二次提供者回覆另存，再比對原生保存的 summary／status／explanation，確認不是 fallback，允許真實 valid partial 保留。仍要求來源一次、人員一次、同一任務、評審兩次、原圖逐值不變；產品 validation 沒有調整。這批最後相同 Python 來源完整 **560 項通過、無 skip**，46.384 秒，`/tmp/maltose-public-source-final-repair-full-python.log`；其後只有原生測試 fixture 更改，最終來源快照與原生全套另記。


修正後最後原生聚焦 **8 項通過、無 skip**，79.810 秒，`/tmp/maltose-public-source-repair-proof-focused-native.log`，含強制格式錯誤、實際主模型讀表／圖表及實際 Codex 收尾。最後固定來源 297 檔／231 Python AST，SHA256 `785fe28ac424614f192c0ec766f35b2981f34283ec9cf5067d4d88c55d5f2e5b`，manifest `/tmp/maltose-public-source-final-repair-source.json`；與完整 Python 560 項執行時只有原生測試 fixture 不同，全部 Python 來源逐檔一致。原生完整 271 案例啟動於 `/tmp/maltose-public-source-final-repair-full-native.log`；完成前不宣稱此來源全綠。最終結果及逐輪失敗保留於 [直接摘要](public-web-source-results.json)。


## 本批最後結果：公開來源與核對修整

最後固定來源 SHA256 `785fe28ac424614f192c0ec766f35b2981f34283ec9cf5067d4d88c55d5f2e5b`，297 檔；完整回歸後逐檔一致。完整 Python **560 項通過、無 skip**，46.384 秒，`/tmp/maltose-public-source-final-repair-full-python.log`；完整原生 **271 項全部通過、無 skip**，684.834 秒，`/tmp/maltose-public-source-final-repair-full-native.log`。GUI、真正 Main、真正 Codex、Docker 全啟用，含新公開來源／圖表／格式修復、原失敗背景／Codex 收尾、全螢幕與既有桌面回歸。來源 AST 231 份、驗證 JSON 18 份、五份相關 Markdown／本機連結與 git diff --check 通過。

成果：公開靜態 HTTP(S) 原文與完整原表格進入既有來源 ledger／持久呈現規劃；半年圖保留真實月份、不同方法及 null，預設新面板；簡單無產品任務問答沿實際 input 收集公開來源，不建立假 owner。評審區分原回應下載、文字頁／表格已讀與獨立查證，publication 回執指出真正新成果面板範圍。證據長 key 用 collision-free 短引用，無效核對回覆至多一次工具禁用重評；沒有直接修錯字、猜證據或重做原工作。強制格式修復案例核對原生接納實際第二次回覆，允許有效 partial 保持原判斷，仍要求兩次評審、一次來源、一筆原人員輸入／產品任務及原圖不變。

上述完整結果對應最後來源，不抹掉前面三輪完整失敗及新增 fixture 的兩輪失敗。[直接摘要](public-web-source-results.json) 保留各輪數字、原因與路徑。靜態表格能力不含 PDF／動態 JavaScript／登入頁／超限或合併表格、多表自動研究；示例域名的隔離資料測試不等於真實民調查核。一般模型仍可能提前回覆 partial，原工作流承接及剩餘 P2–P5 仍須補驗，整體目標保持 active。

正式 build 15 `dist/Maltose.app` 執行檔 SHA256 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`，試用 build 17 `dist/trials/build17/Maltose.app` 執行檔 SHA256 `7c5b4d6cbf4efdc9de3a385af499fb2877ec4dcd887ee9aa9a24adca7bdfe301`，與本批前相同。沒有封裝、部署、新 commit 或正式使用者資料修改。


## 2026-11-02 背景原成果跨獨立問答

新增 workerResultVersion=1，在既有 taskResumption／workerEvidence／resultDelivery 上協商。WorkerResultPublication 保存真實 task／worker／attempt／原 input／版本／body hash，交付 runtime／resumeAfterID 另驗當前已送達獨立答案。原生 writer 在 journal／新面板寫入前核對；runtime 在 admission 前不先寫背景聊天草稿。TaskStore 原 owner 與 active principal 分開，current native UI 只取得已綁定產品任務的實際成果範圍；模型 Memory／KDB／個人任務權限不變。

實際工作結果先留在原 TaskStore／attempt；進入成果路徑時先保存 native 終態事實與 prepared metadata，再交付。已有 pending body 不提前結案或開啟綜整。較舊 body 晚到時，原生仍拒絕對舊 outcome 結束新成果；runtime 用獨立持久 followup，指向真正最新 outcome 與原 worker notification FK，原 body／producer／input 不換綁。新的 standalone answer 只授原版本接續，不新增人員要求、owner 或 worker。

中途失敗完整保留於 [本批直接摘要](worker-interlude-results.json)：fixture 插入腳本 helper signature 不符、Python 新測試 dict 語法、held/cancel helper 名稱三項均屬測試組裝錯誤。真正接線失敗依序是 writer 原未驗 worker prefix（3 案例／1 失敗／4 assertions，24.064 秒）、pending body 被綜整超車（3 案例／1 失敗／3 assertions，18.412 秒）、較舊 body 在較新 outcome 後不能直接評審（3 案例／1 失敗／2 failures／1 unexpected，41.381 秒）。沒有放寬 native latest-outcome、完成門檻、身分或 ACK 檢查，而是補真正 writer、pending 交付守門與持久 followup。

最後聚焦 Python **78 項通過、無 skip**，0.542 秒，`/tmp/maltose-worker-interlude-source-focused-python.log`；原生 **6 項通過、無 skip**，70.423 秒，`/tmp/maltose-worker-interlude-source-focused-native.log`，含受控競態及真正配置 Main 在 typed interlude 後補讀 step3.txt、綜整並完成原任務。這個 voice owner 是受控 fixture，不能冒稱實際麥克風聲紋驗收。另原生合約 19 項通過，0.086 秒，`/tmp/maltose-worker-interlude-final-contract-native.log`。

新原生案例核對 worker 恰執行兩次、受控補讀恰一次、原 requirements／人員 inputs 不增、scope.resumeAfterID 指向真正送達的問題答案；current principal 保持 unknown。真實模型可在原授權內唯讀複核，不硬性固定讀取次數；必要來源集合仍須完整。before-write／after-write lost ACK 都有反例，新 input 可拒絕晚到寫入且相同 publication 重送不重複 body。needs_input／new-task 問答和 held／cancelled／replan／stop 來源均不能放行；真正新 CodexTaskStore 物件可冷讀 prepared／delivered metadata。

固定來源 300 檔／233 Python AST，SHA256 `1f4ceecbff1efadb4ee6848482434fa6592e64b3efdd49e8e11ebd5586f1cf55`，manifest `/tmp/maltose-worker-interlude-final-source.json`。最後完整 Python **572 項通過、無 skip**，48.232 秒，`/tmp/maltose-worker-interlude-full-python.log`；完整原生 `/tmp/maltose-worker-interlude-full-native.log` 進行中，完成前不宣稱本來源全綠。

尚未完成：一般新 runtime 的 unknown-principal 私有成果 scope bootstrap、插問前已生成但未交付的 continuation 跨問答恢復、未知副作用人工核對與其餘 P2–P5。已有結果／來源仍保留，不因缺少新授權自動重做。正式 App build 15／試用 build 17 未替換，無 commit／封裝／部署或正式使用者資料寫入。


### 舊版 generated 恢復的相容性修正

第一輪固定來源 `1f4ceecbff1efadb4ee6848482434fa6592e64b3efdd49e8e11ebd5586f1cf55` 完整原生 **276 案例／275 通過／1 個失敗案例（2 failures、1 unexpected）、無 skip**，800.262 秒，`/tmp/maltose-worker-interlude-full-native.log`。唯一失敗是原有 `testGeneratedContinuationSurvivesActualRuntimeCrashAndNativeStoreRestartWithoutRepeatingWork`。舊來源以 workerResult v0 生成成果，重啟 Supervisor 的新能力啟用後，新的 followup 將舊版已接受通知重新建 prepared metadata；舊版恢復 fixture 未提供 v1 body readback，metadata 因而一直未送達，阻止原 generated 成果完成核對。已有結果仍保存、沒有重新執行 worker，但原先可恢復的案例被擋住，屬實際相容性回歸。

原生 scoped grant 現含真正已登記的 managedResults；只有這些 notification 參加新 post-ACK followup。舊版 accepted 通知保持原 owner／FK 以供原 continuation 恢復，不自動登記為新版 publication。沒有放寬新的 body readback、來源 hash、pending 交付或最新 outcome 守門。實際 SIGKILL／新 store 案例納入修正後聚焦，原 exact worker／讀檔／模型計數保持。

另外補上 worker assessment ACK 遺失：較早已 ACK 的通知觸發 followup，但最新 native-delivered root 還未被 runtime ACK。新候選從已確認來源與該 root 的真正完整 prepared result 組成，不只帶較早的半份來源；仍使用原 root 的 notification FK，ACK 前 execution 不能開始。新 Python 反例驗兩個不同真實通知；第一次測試 fixture 對第二個同 owner 的 task 誤選首通知，已改按 task ID 選其真正通知並明確要求 ID 不同。新原生案例直接遺失 worker assessment writer 的 ACK，最後綜整保留 17／34／51／102，原 worker 恰兩次、受控補讀一次、同一 original input／要求及 standalone answer。

修正後聚焦 Python **80 項通過**，0.668 秒，`/tmp/maltose-worker-interlude-legacy-canonical-focused-python.log`；原生 **8 項通過、無 skip**，77.373 秒，`/tmp/maltose-worker-interlude-legacy-focused-native.log`，含上述舊 SIGKILL、worker assessment ACK、typed interlude／writer 拒絕、真正 Main 與共存回歸。

最後固定來源 300 檔／233 AST，SHA256 `fe491313b5f4f6e9d7eefd0e4e35c1404795a4ce1579e6dce3e790cd39128161`，manifest `/tmp/maltose-worker-interlude-compatibility-source.json`。最後完整 Python／原生分別在 `/tmp/maltose-worker-interlude-compatibility-full-python.log`、`/tmp/maltose-worker-interlude-compatibility-full-native.log` 重驗；原較早全套不能冒充此最後來源。[直接摘要](worker-interlude-results.json) 保留各輪來源／結果及修正。


## 本批最後結果：背景成果跨插問與版本相容性

最後來源 `fe491313b5f4f6e9d7eefd0e4e35c1404795a4ce1579e6dce3e790cd39128161`，300 檔，完整回歸後逐檔未變。完整 Python **574 項通過、無 skip**，51.063 秒，`/tmp/maltose-worker-interlude-compatibility-full-python.log`；完整原生 **277 案例／276 通過／1 個失敗案例（2 failures、1 unexpected）、無 skip**，833.966 秒，`/tmp/maltose-worker-interlude-compatibility-full-native.log`。GUI、真正 Main、真正 Codex 與 Docker 全啟用。新背景路徑與舊版 generated SIGKILL 恢復、worker body／assessment ACK、所有新來源守門、全螢幕均通過，沒有宣稱整套全綠。

唯一失敗是既有研究案例 `testConfiguredPublicSourcePlannerPreservesReadProofAndOriginalProductTask`：配置評審回傳有效 partial，認為缺少「Agent 未改原有面板」的獨立證據。完整網頁表格與圖表／文字交付已完成；回覆保存於 `.cache/main-live/maltose-session-22279BD0-2330-4CFD-B567-34BA5A247951/config/public-source-real-responses.jsonl`。publication-owned 範圍只能證明結果 writer 自己的面板，不足以單獨證明所有 Agent 入口沒改舊板。下一批需沿原生 panel policy／input snapshot／claim／operation journal 提供精確獨立證據，不能直接忽略此條件、改判成功或把人員／動態內容變化誤說成 Agent 修改。

完整實際 Main 跨插問案例另讀回 `.cache/main-live/maltose-session-CA25F72F-0038-4653-A0D9-8E9F428A3197/` 的真正 scope：current principal 為 unknown／unknown，原 inputSource=voice，但 deliverySource=native；同一原 input `fixture-voice-input`，實際獨立答案 ID 為 resumeAfterID；兩份已送達來源、原 worker 恰兩次、第三來源補讀一次。這是受控 voice 身分 fixture 上的真正模型／stdio／native 過程，沒有真人聲紋或聽感驗收聲明。

233 份 Python AST、19 份驗證 JSON、五份 canonical Markdown／本機連結與 git diff --check 通過。正式 build 15／試用 build 17 執行檔 SHA256 仍分別是 `96f9147477677df65ec638de3b906275faba24c9f39aa7934b700525ce207d0f`／`7c5b4d6cbf4efdc9de3a385af499fb2877ec4dcd887ee9aa9a24adca7bdfe301`；沒有封裝、部署、commit 或正式資料修改。[直接摘要](worker-interlude-results.json) 保留第一輪真正相容性失敗、修正與最後未完成案例。整體 P0–P5 及目標保持 active。


## 2026-11-02 原生受控面板操作邊界（驗證中）

針對上一輪研究任務核對的真實失敗，新增原生 `native_panel_action_boundary`：沿原 input snapshot、已協商 policy／operation v1 與持久 claim／operation ledger 查核，Main prepare 時與其 execution／outcome 同一交易保存。精確範圍為同原生實例、同 input／runtime 至 prepare 的受控 Agent 面板入口；沒有 claim／operation 才能證明未接納舊板操作，不能把人員／動態內容變動視為 Agent 修改，也不能覆蓋檔案、其他輸入或後續執行。成果 writer 仍由獨立 publication-owned `answer_delivery` 核對。

缺 snapshot、runtime 已換、guard 未協商／未接，保持 unknown；同 publication 重播讀封存證據，舊 report 沒有證據不事後認證。新增測試覆蓋實際新板初填、人員編輯、已接納但失敗的舊板動作、operation-only 反例、缺 snapshot／新 runtime／停用 guard、封存重播與 fresh store 冷讀。初次測試 accessor 編譯失敗已修正，保留 `/tmp/maltose-panel-boundary-focused-native.log`，沒有把失敗當作測試通過。

聚焦 Python 69 項通過，0.811 秒，`/tmp/maltose-panel-boundary-focused-python.log`；原生 16 項通過，31.864 秒，`/tmp/maltose-panel-boundary-focused-native-v2.log`；最後三項封存／失效補驗通過，1.628 秒，`/tmp/maltose-panel-boundary-sealed-focused-native.log`。實際配置評審於 `.cache/main-live/maltose-session-E32BF24D-AA1D-4528-955C-7D4ADBFCE413/config/public-source-real-responses.jsonl` 引用 source read／native boundary／actual delivery 三份證據，判 completed 並明示不同證據各自範圍。原完整半年表、A／B 方法、缺值、月份精度、來源與未外部查核限制均保留；不把虛構 fixture 冒充真實民調查核。

最後固定來源 300 檔／233 AST，SHA256 `fa4b9c5380357c549918e6e764c608a51780b60621995d91b05944086497ed77`，manifest `/tmp/maltose-panel-boundary-source.json`；完整 Python 574 項通過、48.824 秒，原生全套尚在執行。最後結果／來源一致性／剩餘限制見 [直接摘要](panel-boundary-evidence-results.json)。P0–P5 與目標仍 active；此批不新增 App 封裝、部署或 commit。


本批最後來源 `fa4b9c5380357c549918e6e764c608a51780b60621995d91b05944086497ed77`：完整 Python **574 項通過、無 skip**，48.824 秒；完整原生 **280 項全部通過、無 skip**，842.325 秒，GUI／真正配置 Main／真正 Codex／Docker 全啟用。原失敗研究收尾、Main 讀公開表自主出圖、刻意漏圖後補圖、原有圖不變、三項新原生操作邊界／封存反例、背景跨插問、SIGKILL／新 store 恢復、Codex 交接與全螢幕均通過。全套期間 300 份來源逐檔一致；233 Python AST、20 驗證 JSON、五份 canonical Markdown／本機連結與 diff 檢查同步記錄於 [直接摘要](panel-boundary-evidence-results.json)。

這批解決受控 Main 研究收尾的原生面板操作證據缺口，不代表所有模型／來源都能自動完成研究，也不代表原 P0–P5 全部完成。下一步仍是一般新 runtime 的 unknown scope bootstrap、插問前已生成但未交付 continuation 的安全承接、未知副作用的明確讀回／人工核對，以及原計畫其他呈現／語音與真人驗收。正式 build 15／試用 build 17 執行檔保持原值；沒有 commit、封裝、部署或正式資料修改，整體維持 in_progress／目標 active。


## 2026-11-02 新 runtime 的未識別成果 bootstrap（驗證中）

上一批完整 Python 574／原生 280 全綠之後，沿原 P2 未完成的 cold scope 續作。新增獨立 `workerRestoreVersion=1`（依賴 workerResult v1）的私有 read bootstrap，App 從當前對話、最新真實 accepted input、active ProductTask、版本、執行權及實際 worker／attempt 產生既有成果範圍。request 不能指定 input／owner，runtime 不寫入 active speaker、active input 或人員歷史；新 TaskBrain 無 active input 且未識別才使用此入口，有真實 input 仍走 workerPending。沒有正向 scope cache，writer／ACK／接續沿原守門每次重驗。

實際 SIGKILL／全新 store、manager、coordinator、TaskBrain 驗證：第二份 worker 已準備但未進 native writer；continuation 已寫畫面但 ACK 前退出。恢復同 publication／同原任務，沒有新增人員輸入或重跑 worker。真正配置 Main 的 cold pending-body 案例也通過，`.cache/main-live/maltose-session-D93BE241-86C6-44D9-840A-B5D0E5B3102E/config` 讀回 actual user=default、status=unknown、inputID=null；default 只是 nominal MemoryStore 名稱，實際 recall 拒絕。內部接續保留原 inputSource=voice，但 deliverySource=native；原 worker 恰兩次、step3 補讀一次，沒有真人麥克風／聽感驗收聲明。

Python 聚焦 30 項通過，11.163 秒，`/tmp/maltose-cold-scope-focused-python-v2.log`。原生七項通過，51.578 秒，`/tmp/maltose-cold-scope-focused-native-v2.log`，含真正 Main、兩條新 cold path、舊 v0 SIGKILL、未回答／needs_input／新任務及 held／cancelled／replan／stop。另三項 bootstrap current session／指定 input 拒絕、Codex recipient、queued 新輸入、未協商 v0 及 writer lost ACK 通過，19.153 秒，`/tmp/maltose-cold-scope-guard-focused-native.log`。最初 Python negotiation fixture 缺 foreground conversationID，被原驗證正確拒絕，已補 fixture；失敗保留 `/tmp/maltose-cold-scope-focused-python.log`，沒有放寬產品驗證。

最後固定來源 300 檔／233 Python AST，SHA256 `641f2d9d5f03e9242ac28267a84bb23d593540830c5bcb3e5a20a38486647527`，manifest `/tmp/maltose-cold-scope-source.json`。完整 Python **577 項通過、無 skip**，50.796 秒；完整原生仍在 `/tmp/maltose-cold-scope-full-native.log` 執行，最後結果以 [直接摘要](cold-worker-scope-results.json) 為準。

這批沒有新增可持續重用的授權、模型工具或 speaker override，也不重試未知 running work。已生成 continuation 跨插問還需 immutable producer 與可更新 delivery scope 分離，其他 P2–P5 與真人／正式 App 驗收保留；整體目標 active，沒有 commit、封裝、部署或正式資料修改。


## 2026-11-02 build 18 交付與範圍收斂

依使用者最新要求先打包試用版，再收斂優化。已將新增 cold bootstrap／cold-ready 的九份程式／測試及文件保存至 `.cache/deferred/cold-worker-scope-20261102/`，逐檔 SHA256 驗證可恢復；它們不包含於 build 18，原 cold-ready 失敗沒有被改判通過。這次沒有 reset 其他工作、丟棄原試驗或為進階恢復繼續擴大本輪。

交付 `dist/trials/build18/Maltose.app`（0.7.0／build 18）。所有產品程式逐檔回到先前完整 Python 574／原生 280 通過的基線；300 份來源中 299 份逐字一致，唯一不同為恢復原案例的 Swift 整合測試檔，107 個原 coordinator 測試案例完整保留。沒有將先前基線結果冒充此次重新執行全套：本次核心 Python **69 項通過**，0.806 秒；原生 **28 項通過**，50.107 秒，含真正主模型的自主半年新圖、實際公開表格、刻意漏圖後補圖、原生操作邊界／封存、新結果面板及原 legacy SIGKILL。來源快照 `/tmp/maltose-build18-source.json`，SHA256 `885c4b2e8de737705c6728004648b929ffedf39f4af3354a50810b4671628144`。

Release 編譯 **55.92 秒**。包內 **140 份 runtime 檔**與目前產品來源一致，嚴格簽章、私密設定／憑證值掃描及獨立目錄匯入通過。新 workerRestore 能力在執行檔及包內 runtime 中均不存在。該包以隔離 UI-only/windowed 啟動，實際建立 **1 個視窗**並正常退出；沒有建立使用者 runtime 資料、啟動正式 Agent 或使用麥克風。使用者已切換顯示器，因此本次僅記實際 windowed 結果，不把它當作雙螢幕／真人語音驗收。

正式 build 15 與試用 build 17 執行檔 SHA256 保持原值，沒有自動替換或啟動人員正在使用的 App，沒有新增 commit。最新工作範圍優先自主圖表、具體缺口提示與簡短語音，接下來以實際試用中的阻斷問題為優先；進階恢復、其他自主面板、未知操作核對、持續更新許可與真人／正式切換保留為獨立後續工作，不再作為本輪試用包前置。完整包／來源／測試與限制見 [build 18 直接資料](task-presentation-build18-results.json)。
