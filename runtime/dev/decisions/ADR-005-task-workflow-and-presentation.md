# ADR 005：產品任務紀錄與統一資訊輸出

## 2026-11-02 最新面板權限決定（優先於歷史規則）

依使用者「面板給 Agent 最大自由度，除本地文件增刪改外跳過授權」的新指示，Main 與 Codex 共用常設的面板讀取／操作權限。建立、聚焦、選取、切換、移動、關閉及面板內內容修改不再檢查逐次人員授權、聲紋或二次意圖模型；新成果預設新增只是呈現偏好，Agent 可依需要重用既有面板，並遵守人員明確要求保留的內容。這取代下方歷史紀錄的「只有明確更新才可操作舊面板」硬性限制。

本地檔案建立、覆寫、刪除仍依原 FileService／檔案權限機制；流程圖匯出仍保留既有匯出同意與檔案版本核對。面板內容編輯不等於修改磁碟原檔。真正的任務暫停、取消、過期來源與 Main／Codex 執行權交接仍有效；操作回執保存、讀回及去重繼續處理傳輸結果不確定，均不增加人員授權步驟。Memory／KDB 身分不因面板權限而改變。

此次只修正實際阻斷的面板授權問題，進階恢復／呈現維持 deferred。聚焦原生 20 項、完整 Python 574 項／原生 275 項全部通過，無 skip。build 19 已封裝至 `dist/trials/build19/Maltose.app`；簽章、140 份 runtime 來源一致性、隔離匯入及 UI-only 雙窗口啟動／正常退出通過，未啟動 Agent 或使用麥克風；正式 build 15 與試用 17／18 保持原樣。詳細 [本批驗證結果](../../../docs/verification/panel-autonomy-build19-results.json)。真人語音驗收與正式切換仍未完成，未提交本批修改。


狀態：`proposed`。日期：2026-11-02。已部分落地結果／語音、新文檔持久交付、共用任務關聯、三方自動核對、Codex 新文檔收尾及背景有界接續；一般前景成果保存／交付與輸入分類已接；部分成果安全續做、完整恢復、暫停期間短語音播放、全部面板規則及整體驗收尚未完成。

需求與驗收以 [feature plan](../features/task_workflow_and_presentation_dev_plan.md) 為準，執行入口見 [計畫入口](../../../plans/task-workflow-and-presentation.md)。既有產品程序邊界仍依 [產品 ADR 005](../../../docs/decisions/005-unified-maltose-runtime.md)；兩份 ADR 位於不同文件命名範圍。

## 背景

現有一般工作與 Codex 協作已具備各自的持久狀態；產品需求、追加要求、完成證據與交付需要共同關聯。原 VoiceAgent 將文字回答串流切句後送入 TTS，完整內容與口頭摘要尚未分流。使用者另明確要求成果面板預設新增，只有要求更新時才能修改既有面板。

## 提議決策

1. 產品任務紀錄沿用原生協調／store 的單一 writer 邊界，關聯 Python 工作與 Codex 執行引用。個人 TaskStore、Codex thread 與 UI 各自保留既有責任，不維護可互相競爭的產品任務副本。
2. 將任務結果、呈現規劃與實際交付分開。主模型提出有來源的結果與呈現建議，程式核對要求版本、證據、許可與狀態；執行完成不由播放或面板狀態反向決定。
3. 完整文字與語音摘要使用分開的內容合約，沿用既有 TTS 播放／打斷。一般回答不增加強制二次模型呼叫；長內容保留於聊天與面板，語音以語意摘要為主。
4. 每一份新的成果發表預設建立新面板；同發表串流／重送可填入其綁定的新面板。使用者明確更新意圖才授權指定既有 panel ID 與操作，所有 Agent 寫入入口共用檢查。
5. 結果、面板、聊天與語音各有穩定交付識別及獨立收據。呈現失敗只恢復交付，不重做原工作；舊要求版本、取消及重啟不能復活過期寫入、語音或自主工作。
6. 保留既有面板模型、FileService、身分／Memory／KDB 與 Codex 交接限制；使用者確認新意圖前不恢復暫停中的舊計畫。

## 取捨與落地

增加版本與交付紀錄，但可避免重複開窗、呈現失敗重做工作、整篇朗讀與任務過早完成。原生產品 store 的中立化須提供相容遷移及回復；CLI／Web UI 使用相容 adapter。先交付文字／短語音，再補任務銜接與更多面板編排，依 feature plan 的 P0–P5 驗證後更新本 ADR 狀態。

## 第一條接線備註（2026-11-01）

Python `AnswerResult` 是最終回答的內容子合約，不是產品任務已完成的證據。`schemaVersion=1` 保存全文、標題、語音摘要、結果分類、視覺偏好及限制；kind 不接受 completed。原生 `publish_document` 不暴露為模型通用工具，使用 runtime 產生的 publication ID 建立新面板，同執行期內核對內容摘要與關閉狀態。持久 task／outcome／presentation、全部入口的更新許可與跨重啟去重仍依 P2–P4 實作。

後續接線已加入 presentation v1 協商、全文增量解碼、設定檔語音偏好、單次詳讀／靜音與輸入世代取消。原聊天事件協定保留，同 message ID 的 assistant_start 可清除工具回合草稿，assistant_end 核對完整結果；只有已驗證最終結果可新增成果面板。TTSRequest 的可選取消事件在建立播放器的鎖內核對，關閉取消前仍未建立程序的競態窗口。

口頭摘要若符合格式與預算，不增加模型呼叫。不合格時最多進行一次工具禁用的內容修整；完整文字及面板先交付，修整只處理既有摘要／限制，不重跑原任務，不改變 result ID 或全文。修整仍失敗時明示無法可靠精簡、保留完整文字，不能任意截取開頭當作語意摘要。真實模型及條件分支證據見 [驗證紀錄](../../../docs/verification/task-presentation-integration-report.md)。

### 背景交付的儲存責任

Python 的個人 TaskStore 仍擁有 worker 與原始回報，在同一 SQLite 交易新增 v1 通知 outbox；這不是另一份 ProductTask 真相。穩定通知 ID 關聯準備好的 AnswerResult，原生已保存全文的回執才使通知 accepted。播放採先 claim、再嘗試的保守語意：崩潰可能造成一次未播放，但不能因重啟自動補播過期答案；可手動要求詳讀，不能將 claim 說成已聽見。

原生既有 conversation journal 擁有呈現意圖與回執，不決定任務是否完成。v1 result_delivery 保存全文／聊天 ID／發表 ID／對話；result_panel_applied 與 result_closed 分別記錄內容套用與使用者關閉。固定衍生面板 ID 讓崩潰後恢復同一新成果；同發表內容或訊息來源衝突拒絕，關閉紀錄禁止重開。Main／Codex 直接工具的更新許可尚未因此取得或放寬。

原生與 runtime 間另協商 resultDeliveryVersion=1，不能對舊 App 發送不認得的內部命令。正常文字串流與最後 durable upsert 使用同一聊天訊息 ID、共同 conversation ID。前景回答在 App 接納之前的 durable outbox 與中立產品任務仍未完成，整體 ADR 維持 proposed。

狀態提示不能替代口頭摘要：摘要本身為空時，僅加「尚待確認」或「未成功」不能視為已摘要實際結果。需要修整時，以完整有界原文保留末尾重要限制；provider 拒絕時採明確文字降級，不任意截取來源前段。

### 共用任務的第一條實際接線

原生 CodexTaskStore 的 schema 3 沿用單 writer，增加獨立 v1 ProductTask；不是讓 Codex 擁有 Main 任務。Python 保留自己的 SQLite 工作／權限，只保存 host 接納的 task／execution／input／要求與計畫版本引用。schema 1／2 第一次新寫入前保存原始私有備份，原生模型與兩份資料庫不互相競爭修改同一產品狀態。

workflowVersion=1 是私有原生傳輸協商；模型只取得有界 read／setPlan 工具，不可指定來源輸入、runtime session 或可信完成證據。語音來源先由實際 VoiceAgent turn 保存；未識別的不同回合不視為同 owner。原生 UI 權限與 Memory 身分仍分離。Codex 每回合收到限定委派的狀態投影，不附整份 Main 計畫、個人 worker 內容或其他子任務。

背景派發須先取得 host 執行關聯回執並落地 SQLite，同一交易開啟持久 dispatch_ready；全部派發路徑都核對該條件，既有依賴的完成不能繞過等待中的確認。未知回執保持 held，不重送原工作；observer 只用於當次 plan。成果回報原子保存執行狀態、證據及 outcome，去重衝突整筆拒絕。worker 成功、SDK 工具觀察與模型自述分別記錄，不能直接滿足完成條件；要求版本與已存在的失敗必須核對。

第一條接線當時，自動 evidence 蒐集／語意核對、接續與完整恢復仍待實作；host verify API 的狀態測試只證明守門規則，不能當成自動完成工作流已接通。後續前景核對進度見下節，ADR 保持 proposed。

### 前景 Main 的觀察與語意核對

後續已在真正工具返回邊界捕捉本次 Main 的觀察，以原要求／計畫版本落地；非本次執行緒不能繼承該來源。收錄明確支援的 FileService／命令／面板／時間回執，Memory、KDB、個人 TaskStore 與全工作區感知的工具內容不複製進共同紀錄。觀察完整性不足／超限保留標記，不將截斷內容當完整證據。來源讀回與實際測試回執分型保存；已知同成果的後續修改使較早讀回失效。來源中的自述不升級為實際測試證據。

Main 成果先保存，再做有條件的一次無工具核對。模型只提出 criteria 到已有 witness 的語意對應；host 仍擁有版本、執行、未解失敗及結案守門。新 assessment 與原回報分開，保存後重送讀取原判斷，不重做工作；新要求或成果改變不能套用舊核對。核對結果有自己的聊天發表 ID，不覆寫原成果。語音與詳讀均保留未核對狀態。

delivery_origin 是 runtime-only 的內容來源，不接受模型設定。背景回報只有原 worker 的顯式引用才能寫入對應產品任務；沒有引用的相容排程通知不借用最近 Main 來源。背景／Codex 的可信驗證與有界接續仍待補齊；整體 ADR 維持 proposed。

### Codex 觀察來源與暫停期間的收尾

Codex SDK 的 item/started 先保存執行引用、要求／計畫版本及實際命令；item/completed 或晚到的 thread snapshot 只能關聯該原始來源，不能按目前最新要求重貼版本。沒有 started 的歷史項目保留 unknown，不自行升格為已驗證。可辨識的單一測試命令、完整輸出、終態、exit code 與指定 worktree 必須一致；複合 shell 命令不能只依最後一個 exit 0 成為測試證據。已知後續 fileChange 使同工作區較早的測試證據失效。

原生協調層取得實際差異與來源專案的唯讀基準核對後，透過控制器 lease 呼叫一次無工具的產品成果核對。此操作不進入 Main 的一般工具／Memory／歷史循環，也不解除暫停。結果仍受原生 store 的要求版本、執行狀態、實際 witness 與未解失敗約束。產品 assessment 與下一步意圖 review 使用不同持久快取，不互相混淆或因交付重送重做開發工作。

核對輸入明列由舊到新的觀察順序及仍可引用的 witness；最終差異讀回是唯讀快照，不是另一個修改事件。已知失效的來源不列入可引用清單，較早要求版本的晚到修改也須保留在順序中。過長儲存 ID 可投影成當次請求內唯一的短引用，通過嚴格驗證後才還原原始 ID；不改寫持久證據，也不模糊比對或修正模型猜錯的 ID。

意圖 review 以全文、可選短語音及呈現建議回到 host，避免先發事件再過濾舊問題。host 在真正發表前重新核對當前任務、回合、問題 ID、停止與新增要求，然後沿用 deliver_result 與既有 journal；保存後才確認收尾交付。相同問題重試延續同一份新面板，後續新回合另建。語音摘要的生成不等於已播放；暫停期間安全播放與實際聽感仍需另行完成及驗證。

### 背景執行引用、工具證據與聚合核對

workerEvidenceVersion=1 為獨立的私有能力協商，舊 client 不收到新的 pythonAttempt 操作。TaskStore additive 的 task_attempts 保存準備、接納、真正進入執行、終態及不可變來源；每次實際重試有新 execution ID。派發引用與真正 attempt 在原生同一交易切換，避免中間狀態誤判完成。ACK 不明而尚未進入執行時可在明確重試時重送同一 ID；已進入但狀態不明的工作不自動重做。新要求不把舊工作重貼為最新版本。

TaskManager 在實際 worker 呼叫期間設定專用 context collector；受支援工具返回時複製有界資料，Main／別的執行緒／私人 Memory／KDB 不混入。搜尋 worker 保留實際 provider 回應與 search_results 範圍，不把 snippet 當全文讀取。worker 的字串回報不能自行提供 trusted observations。完成狀態、工具觀察與通知同一 SQLite 交易保存，原生再依當次 attempt 核對來源，只有成功狀態不能結案。

核對涵蓋本次回報及同 owner、task、要求／計畫版本中已確認送達的完整成果，避免最後一個 worker 因沒有重複先前回報而被誤判缺件。前次已完成 attempt 的事實可在明確重試前先同步；它不 ACK 文字交付、不呼叫模型、不重跑工作。最終 assessment 仍經原生獨立 gate，核對文字保存後才接受通知；未知交付只重送同一結果。語音收尾採 host 接納的狀態，保留原始 worker 全文。

此決策尚未涵蓋背景完成後的有界自動接續、所有崩潰點的 reconciliation 與排程建立來源；不以安全停在 awaitingEvidence 取代這些必要工作。P2 與 ADR 整體維持進行中／proposed。

### 有界內部接續與呈現交付

新增 continuationVersion=1 私有協商，產品預設啟用，未協商 client 保留既有流程。TaskStore 的 product_continuations 保存來源通知、owner、要求／計畫版本、trigger outcome、接續模式、模型結果與工具觀察；不是新增人員輸入或另一份任務真相。原通知已確認交付後才可取出接續，Codex 持有執行權、held／cancelled、其他 owner、新要求或計畫變更時不得執行。

原生同一 writer 保存 ProductContinuation。verified completed 走 finalize，模型不可用工具且不把已完成工作重開成 running；明確需要人員決定或達接續上限時走 clarify。其餘工作只進入原請求已授權的有界工具循環，保留全部現有身份、檔案、命令與批准邊界。缺少可自行讀回的來源不等於缺少使用者資訊；主模型可以先用既有授權讀取工具補齊，真的需要選擇或新許可才提問。最多八次接續後保留剩餘事項並提出決策，不偽稱完成。

工具 dispatch 前後核對原生來源與本機輸入 generation。只讀 get_task_workflow 不得丟失 continuation ID，否則後續真實觀察會錯掛 Main，無法完成核對。新輸入／切換 Codex 時保留已發生操作並記錄中斷，不恢復舊工作。真正發表前，共用面板 writer 再核對當前來源；接續正文與其 assessment 文字同受此守門，不先寫日誌再過濾過期成果。

生成結果先保存，再交付。未知 ACK 只重送原 ID／原內容；generated 跨重啟只恢復交付，不重做工具或模型。未開始的 admission 可同 ID 重送；已開始且未保存結果的 work 保持 uncertain，不自動重跑。只讀 finalize 可安全重新生成，但仍遵守同一 ID、最新來源與新面板去重。語音先 claim，恢復不補播舊內容；播放與真人聽見仍是不同驗收。

同一 schema 增加可選 continuation 欄位，相容既有 ProductTask；並不改變原 CodexTaskStore schema 3 的單 writer／備份邊界。仍需完成前景流程的全面承接、需求分類、排程來源、完整 uncertainty reconciliation、全部面板許可、暫停中語音與正式驗收，整體 ADR 維持 proposed。

### 已保存人員輸入的範圍分類

inputScopeVersion=1 私有協商新增 set_task_scope；不新增分類 Agent 或每回合強制的第二次模型呼叫。Main 模型在原工具循環依真正人員需求提出 continueTask／newTask／standalone，runtime 填入實際 input ID、host 任務與要求版本，原生單 writer 保存且不可改寫。模型不能提供 runtime 身分或另一份人員訊息。外部回報與頁面內容不增加授權。

新 Main 輸入不再自動追加到未完成任務。讀取可檢視已授權的舊任務，但 inputBound=false 時不繼承其成果引用；新協定下 setPlan／pythonPlan 也不能繞過未分類檢查。continueTask 追加原始文字並升要求版本；newTask 清楚切換目標，後續計畫只綁該原始輸入；standalone 留在聊天、不更動舊完成條件。既有綁定來源不能被 forceNew 或分類搬移，held 不會因保存計畫解除。未協商的舊 client 不收到新工具並保留原 read／setPlan 語意。

接續來源同時檢查最新非 deferred 的真實人員輸入，不能只靠要求版本不變繼續發表。內部接續不提供分類工具，避免將內部事件重解釋為新的使用者意圖。這只完成來源分類；前景生成前後的持久交付／重啟與一般部分成果接續仍須補齊，ADR 保持 proposed。

新產品目標的 @codex 需使用新的開發 thread 與隔離 worktree，不能因 conversation 仍保留歷史 activeTaskID 而重用舊任務。只在原回合沒有 active／pending／uncertain 操作時切換，保留歷史 record。最終計畫／報告文檔使用完整結果合約的 full_text 與 visual=document，由 publisher 發表；建立空 document 再嘗試 notes_set_text 並不是受支援的交付方式，工具失敗也不能省略已生成的正文。

分類之前的版本仍可能與舊要求相同，因此不能只以要求／計畫版本檢查晚到核對。Main／Python report 的核對 context、assessResult 真正提交與內部接續皆需核對最新已接納人員來源；新輸入到達即拒絕舊結案，但不抹掉已發生工具與原報告。後續分類才決定追加版本、另建目標或保留獨立問答。

## build 16 試用回饋的圖表接線

最終結果可帶可選的結構化 chart，並透過獨立 resultChartVersion 能力協商。沿用同一 publication journal／ACK、既有原生圖表，不以模型連續 create_panel／chart_load_csv 作為最終輸出層，避免受工具輪數與重送重複建立影響。圖表與配套文檔具有獨立穩定 ID 與 tombstone，關閉圖表使用新事件，使舊版忽略圖表生命週期而保留文檔。來源、缺值與方法差異在圖表及全文保留，圖表交付不等於來源真實性或整個任務完成。前景持久交付服務未完成前維持停用，ADR 仍為 proposed。

## 一般前景成果的交付來源

前景成果以真實 conversation／input scope 進入同一 TaskStore 的獨立 outbox，不虛構 worker 通知或 Memory owner。原生保存原 producer／版本，當前 delivery runtime 只負責重新交付。真正 writer 前檢查來源、圖表內容、執行權及最新人員輸入；暫時暫停與 source superseded 分開。完整答案及必要評審各有不可變 ID／ACK，先保存評審再提交，重啟只重送；不補播、不恢復舊 speaker 身分。

answer_delivery 證據含真正已保存的完整文字與面板套用回執，可滿足純規劃／寫作交付；其文中自述不能充當已實作、測試或已讀外部原頁的證據。一般前景部分成果續做還需真正前景 trigger 與不依賴假 worker owner 的 admission，ADR 保持 proposed。


## 一般前景接續的真實來源

foregroundContinuationVersion=1 在前景交付與既有 continuation 協定之上獨立協商。只有真正已送達的 foreground result／子成果可觸發下一步；原生檢查原 conversation、人員輸入、任務、版本與執行權，SQLite outbox 外鍵保存同一來源。鍵盤／未知語音不需要假 worker 或已識別 Memory owner，產品任務仍只有原生單 writer。

完整答案與工具回執先保存，原生 ACK 後才安排下一步。已核對純計畫完成／真正 needs_input 停止；原授權內可補做則走既有 TaskBrain 工具循環，八次後只提出具體問題。內部接續不增加新的人員輸入或許可。已知 read_file 來源形狀錯誤可回傳失敗回執給模型修正，但不構成成功讀取證據；許可與未知寫入錯誤不因此重試。

重啟區分 durable admitting（尚未進入工作）、generated（只重送結果）及 running（未知操作，不重做）。原生仍用舊 reader 可識別的 interrupted scope state，新增可選 recoveryState=uncertain，實際 execution 保持 uncertain；這不等於已驗證舊版本可改寫所有新增欄位。獨立問答後承接、人工 reconciliation、容量回饋、暫停中語音、全部面板許可與正式驗收未完成，ADR 保持 proposed。


## 插入獨立問題後的前景銜接

新增獨立 taskResumptionVersion=1。已保存人員輸入的 standalone 分類保存當時原任務版本；真正答案交付後，原生才以相同任務／版本與來源許可決定是否可接續。原始要求不追加該問題，內部接續不偽造新的人員輸入、Memory owner 或新許可。

resumeAfterID 為已送達獨立答案的 publication ID，與原 foreground／input／task／version 並存。原生單 writer、SQLite 真正來源 FK、每個 checkpoint 及結果／assessment writer 都保留該引用；重送／重啟不重算工作，新的輸入或狀態使舊引用失效。持久 interlude 與 scope 來源不可改寫。八次 work 上限沿用同任務版本，不因問答重設。

尚未 ACK、needs_input、newTask、held／cancelled、版本不符、不可存取來源或未知工作都不因獨立答案而恢復；已保存生成成果只恢復交付。這是已送達前景成果的第一條接線，worker 在問答期間返回／尚未送達的情況仍需其真實 owner／attempt 來源，ADR 維持 proposed。


唯讀評審的 criterionReferences 與既有短證據引用相同，僅為本次核對的確切索引；不替換 host 保存的完整完成條件。模型引用編號後先對回原文再走原 schema／證據／版本 gate，沒有標點正規化、模糊配對或猜測。這避免把單純抄寫失誤誤列成尚未交付，也不把未知評審當成完成。


## 原答案與後續呈現意圖分開封存

visualPlanningVersion=1 是前景持久答案／原生圖表之上的獨立可選協定。先保存原答案，再對原人員表格或完整共同 read_file 回執做無工具呈現選擇；模型只選來源欄位與分組引用，程式拷貝真實數值、日期、缺值及來源列。呈現不增加任務許可，不進入 TaskBrain 工具循環、不取得 Memory 身分，不把搜尋摘要當成完整來源。

foreground_presentations 外鍵連到實際 foreground_results，context 與一次封存的 decision 不可改寫；effective AnswerResult 在原生首次接納前由原答案加已封存圖表組成。首次接納後仍依原出版雜湊與 writer 守門，不以繪圖失敗重做原任務。未選完崩潰只可重做此無工具選擇，已封存只恢復交付。舊協商 v0 不建立新意圖或呼叫新操作，沒有封存的 v1 意圖也不透過舊 host 私自改寫既有 publication。

此批只處理主回答漏圖後的完整來源表格路徑，保留原主模型 chart 相容路徑；其餘引擎、資料形狀、面板更新許可、真人及正式交付仍未完成，ADR 維持 proposed。


新輸入取代呈現時仍需保存已發生的原工作：取消／封存文字降級的呈現決定後，沿既有 foregroundPrepare 寫入 Main 回報及實際工具來源，才結束舊 outbox。這不准許舊視圖發表、不恢復舊工作，也不把舊結果改貼新要求版本。


### 直接工具的修改來源與一次執行範圍

panelPolicyVersion=1 將 Main 的 context-local invocation／control epoch、Codex 的 native controller／lease／connection／task／turn，與原生保存的真實人員 input 關聯。模型參數不含這些權限來源。新面板的初始填入只屬於同一 invocation；既有面板須由無工具主模型依原指令與穩定目標分類，並附原文操作／目標片語，原生於實際 model／檔案 transfer 前再驗來源與 revision。未熟悉用詞使用獨立無工具動作核對，不能靠有限字詞表假裝涵蓋自然語言。

原生在指令接納時擷取指涉與 revision，保護第一次工具呼叫之前的人員編輯。一次更新的不可變 claim 附加於既有 conversation store，採原單 writer 交易；新結果／新執行或重啟不能改綁原 claim。這不替代 FileService、未知副作用的核對、原有 dirty 保護或私有成果 writer。人工 UI／JSON 仍沿原入口，Agent 寫入則全部進共同守門；實測範圍與未完成事項見 feature plan，整體 ADR 維持 proposed。

### 面板操作歷史與接收確認

`panelOperationVersion=1` 在既有單 writer conversation store 追加操作 journal，依序保存 prepared 與不可改寫的 terminal response，再由 runtime 私有 ACK 確認接收；面板完成與 ProductTask 完成分開。舊來源不以 current plan 重新標籤，版本引用來自原生 input／真正 dispatch execution。已發生但未確認的操作先讀回，不因缺少回覆而盲目重做。

原生可以核對「同版本原任務、沒有 UI 改動、回執已送達」的失敗，再沿真正 work continuation／Codex execution 延續一次 claim；歷史成功、prepared／uncertain 或沒有完整觀察的動態狀態不提供此證明。外部檔案儲存、新面板初始發表與通用未知副作用核對仍沿各自邊界後續實作。協商 v0 不使用新 journal／ACK；本 ADR 整體仍 proposed，完整驗收範圍以 feature plan 為準。

操作 journal 的冷啟動必須驗證已保存 snapshot，而非把 terminal row 當成新的 prepared 插入；只有 live commit 使用前一份真實紀錄核對狀態轉移。載入仍核對歷史 claim 的 no-change proof，不把「可讀回」變成重新操作的授權。內部接續可使用模型 API 的 input data 訊息承載已保存 task，不能以 assistant 回覆位置造成只重述舊結論；這不新增產品人員輸入／聊天歷史或權限，真正授權仍是原生保存的原 human scope 與每步 checkpoint。


### 公開原文讀取與表格來源

`publicWebSourceVersion=1` 在既有 workflow／foreground result 能力之上協商，由 Main 的自有唯讀工具取得無登入公開靜態 HTTP(S) 來源。搜尋摘要只定位來源；圖表補全只接受實際工具觀察中完整、雜湊一致的原表格，不能接受模型自行整理的 CSV 或截斷頁面。分頁與選表引用同一個不可變、限時且綁定實際輸入的 sourceID，不把新抓取內容混入舊快照。

網路層固定於已核對的公開 IP，逐跳守門、驗證 TLS，沒有 Cookie、登入、代理或私人網路權限。只處理有界靜態文字／完整表格；PDF、JavaScript 與不支援結構回報具體限制。sourceRead 證據區分已下載回應、已讀文字頁及已讀完整表格，不把出版者主張視為已獨立查證。一般無產品任務問答沿真實 input 保存公開來源，不新增假 owner 或身份；已生成成果的持久恢復仍只做交付。

呈現模型只選已取得表格的欄位／分組，數值、月份與缺值由程式沿原邏輯構造。成果 writer 回報實際 publication 綁定的新面板 ID／範圍，評審不能從 applied 標記推定覆寫舊面板；其他工具寫入仍須另核對。完整研究格式與整體驗收尚未完成，本 ADR 保持 proposed。


完成核對的模型引用是 request-local 顯示名稱，持久證據 key 保持原值。既有 collision-free 短引用擴至 UUID 工具回執（超過 32 字元），減少長 key 複寫錯誤；只在原始 allowlist 驗證成功後精確還原，不猜測或糾正不存在的 evidence ID。模型文字仍不能建立證據、修改原回執或因一份核對失敗而重做已完成工作。


核對回覆格式／引用無效時，最多一次無工具重評原封不動的已保存 context。上一份回覆與錯誤僅作不受信任修整資料，仍需完整通過 schema、證據 allowlist 與原生來源／版本守門。這不是接受錯拼欄位、建立新證據或重新執行原任務；重評再無效、容量不足或 provider 失敗則具體保留 partial，暫停可中止。有效的正常核對不增加模型呼叫。

### 背景成果在獨立問答後的來源

`workerResultVersion=1` 將 worker 執行事實、成果發表與當前交付範圍分開；同一 worker／attempt 與 input／版本／內容 hash 不可變，delivery session／resumeAfterID 只可根據真實已送達獨立答案續授。原生 writer 需在 journal 寫入前檢查，不能只靠 runtime 發送前檢查。已知執行完畢但交付未 ACK 的成果仍阻止提前收尾／綜整；遺失 ACK 重送原 publication，不重做 worker。

當前鍵盤輸入不恢復舊 speaker。原生授予的只是當前產品任務的既有 worker／attempt 成果範圍；runtime 以實際 TaskStore 行的原 owner 存取該成果及其 notification FK，不把 owner 寫入 active user、Memory principal 或模型參數。模型的個人工具權限維持原狀。接續仍需現行 human／要求版本／控制權、原 source outcome、實際送達的獨立答案與有界執行檢查。本 ADR 仍 proposed；完整 scope／故障與真人驗收按 feature plan。


### 原生受控面板入口的負面要求核對

「結果 writer 只套用自有成果板」與「原 Agent 未操作舊板」是不同事實。後者從同一原生實例的真實 input snapshot、已協商 policy／operation v1 及持久 claim／operation ledger 取得。主回答 prepare 時與 execution／outcome 原子封存，重播保留歷史證據，舊回報不能事後補一份無變更認證。這只涵蓋同一 input／runtime 至 prepare 的受控 Agent 入口；不等於所有畫面內容始終不變，也不涵蓋人員操作、動態網頁、檔案或後續執行。缺少範圍就維持 unknown；核對不因結果已顯示而自動判 completed。


### 冷啟動的成果 scope 不等於 speaker 恢復

`workerRestoreVersion=1` 是 workerResult v1 的獨立私有能力。沒有 active input、且 speaker 尚未識別的新 TaskBrain，只能從 native 當前對話與真實最新 accepted input 取得已綁定 ProductTask 的 worker／attempt 引用；不能指定另一個 input／owner，也不能把它寫成新人員輸入。private store 再以實際行取得原成果 owner，每次操作都重驗 current scope；Memory／KDB／個人工具依原身分判斷，nominal default user 不視為已識別。此恢復不構成重做 unknown running work 的許可，舊 voice 的新接續交付採 native 來源，不能因重啟自動補播。


### 2026-11-02 交付優先與 deferred 邊界

依使用者最新指示，本輪先交付 build 18，再收斂至自主圖表、具體核對提示及短語音。新 workerRestore 私有能力與 cold-ready 試驗已隔離，不包含於此包；上節 cold bootstrap 是歷史試驗記錄，不代表本輪已啟用。整體 ADR 保持 proposed，進階恢復另立後續工作，不能為了擴充而無限推遲可試用版本。

## 2026-11-02 任務觀察面板補充

新增共用的行為與任務進度呈現模型，直接投影目前 conversation 的原生 ProductTask store、既有 runtime 事件與已核對來源的 Codex 通知。步驟回報為可選、具要求／計畫版本的顯示 metadata；父子步驟與執行相依分開，不能由顯示進度關閉任務。沿用 store 的單 writer、既有完成核對與任務控制入口。圓環完成轉勾僅反映所屬層級的完成狀態；行為摘要不複製底層工具內容。詳細驗收見 feature plan 當前批次。


### 2026-11-02 工作區展示狀態恢復

工作區開啟集合與佈局由原生 workspace session 保存；成果內容沿用既有 journal，任務狀態沿用 ProductTask store，避免另一個任務 writer。首次為形象、聊天、右下工作日誌，後續恢復上次開啟集合。形象與聊天為固定面板，UI 與 Agent 共用不可關閉規則，這是使用者指定的產品限制，不是逐次授權。進度依未完成任務的初次投影與狀態變更主動開啟，保持人員目前焦點；全局／聚焦／側欄主面板使用內容自己的捲動。詳細驗證見 feature plan 的 build 21 批次。
