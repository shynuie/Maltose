# Agent 自動接入與雙向互動計畫

狀態：done；2026-10-29。

## 範圍與完成定義
原 M0–M6 是 Host/SDK 能力，不代表 MyAgent 已接入。既有 M4 P0 Awareness 不重做；本階段必須讓真實 MyAgent 使用既有 context，並讓原生 UI 看見真實 runtime 狀態。

## 增量
- [x] I0：對照兩專案既有事件／工具／設定入口，保留 MyAgent 未提交的 execution 變更。
- [x] I1：OS 分配 port、每 instance 的本機 discovery descriptor、過期/錯誤項目排除、認證與配對申請/批准/拒絕/期限。
- [x] I2：MUP runtime status/event schemas、具 session/run/sequence 的狀態快照、心跳/離線、原生狀態與串流面板；不以 LLM 生成狀態或假進度。
- [x] I3：固定 bootstrap 介面、版本/雜湊驗證的預建 wheel 派送、獨立 uv 環境與長駐 stdio worker、動態工具代理、重連與安裝失敗復原。
- [x] I4：MyAgent CLI/config/CapabilityAdapter 接線、EventHub 狀態上行、UI text/action 下行、每回合讀授權新鮮 context 給 TaskBrain；脫離 Web UI 開關。
- [x] I5：真實 Host + sidecar + MyAgent 假模型整合，驗證圖表框選→語意問題→context、推論/工具/播報狀態、斷線/配對撤銷、多代理隔離、套件篡改/相容性、port 占用。
- [x] I6：重新封裝、操作文件、測試證據與限制；不宣稱未執行的語音/真實模型/使用者批准路徑通過。

## 原則
- 安裝的是預先建置、固定版本且驗證過的工具套件；UI 文件不包含可執行程式。
- bootstrap 一次接上 Agent 的 runtime/tool registry；不讓模型自行改寫專案或拼接安裝指令。
- 工具程序以獨立 uv 環境及 stdio 管道運作，不能污染 MyAgent 的 ML/voice 依賴。
- 每個 agent 有自己的配對／session／授權；發現不等於授權；UI 取消信任立即拒絕後續請求。
- 自動配對的正式使用者批准只在原生 UI 完成；測試只批准隔離測試服務。
- 思考/推論狀態依真實 runtime 階段；模型服務不提供的內部推理不捏造；語音與生成可同時 active。

## 實作與驗證紀錄

- I0：已讀取 MyAgent workflow／feature plan，對照 EventHub、TaskBrain、CapabilityAdapter、VoiceAgent 與 CLI/config；原本四個 command-execution 變更保留。
- I1：動態 port、私有 descriptor 與 stable host-id、claim proof／原生批准、拒絕／單次領取／既有 principal 防覆寫；Swift 真正 listener 測試通過。
- I2：event-specific runtime schema、run/sequence/session 隔離、15 秒逾時、原生狀態及對話輸入面板。模型與播報事件有實際觀測測試。
- I3：固定 publisher 公鑰、ECDSA 簽章與 wheel 雜湊、無依賴預建 wheel、離線獨立 uv 環境、stdio worker；套件篡改／相容性／安裝失敗保留先前環境測試通過。
- I4：實際修改 MyAgent；opt-in `--maltose`／TOML，動態工具登錄，真實執行事件，原生文字回既有佇列，每回合自動取得授權 context；保留原本說話者政策。
- I5：原生 Host → 簽章 wheel → 真正 uv 安裝 → MyAgent 假模型整合通過；另已通過真實 ECharts canvas 框選 → context → MyAgent TaskBrain 的整條 GUI 測試。Host 換埠自動重連、撤銷停止、多代理隔離均通過。
- I6：0.4.0 build 5 已封裝、重新開啟並確認可探索；資源／簽章／Keychain smoke 通過。最終 Swift 38、Vitest 22、pytest 37 通過；MyAgent 新增 8 項通過，完整回歸原有 3 項失敗另附 HEAD 重現。詳見 [驗證報告](../docs/verification/agent-integration-report.md)。

## 保留的驗收項目

真實麥克風、實際遠端／本機模型服務與使用者正式批准的日常操作，仍需真人環境驗收。MyAgent 原有三個測試失敗已在未修改 HEAD 的隔離副本重現，不以削弱身分政策的方式繞過；詳見驗證報告。其他 Agent framework 需一次接上 registry／runtime adapter，不能宣稱安裝套件就能修改任意框架。
