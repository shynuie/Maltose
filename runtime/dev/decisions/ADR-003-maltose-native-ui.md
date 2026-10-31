# ADR 003：Maltose 原生 UI 以獨立工具程序接入

狀態：accepted；2026-10-29。

MyAgent 以 opt-in `--maltose`／TOML 啟用原生 UI，沿用現有 EventHub、CapabilityAdapter、TaskBrain 與 submit_text，不依賴 Web UI 開關。bootstrap 僅用標準函式庫與固定 publisher 公鑰，從使用者私有 discovery 目錄找到動態 port；正式配對必須經原生使用者批准。

簽章／manifest／wheel 雜湊通過後，才由 uv 離線安裝預建 toolkit 到獨立環境；不修改 MyAgent 模型／語音依賴。stdio worker 負責認證、MUP、訂閱與輸入，registry 由受信框架 adapter 登錄固定工具。模型不接觸憑證或安裝命令；UI 文件不能提供任意程式。

真實模型／工具／播報執行入口產生狀態；推論與播報可同時 active，不捏造模型內部推理。每回合自動取得原生 focus／selection／viewport，視為不可信資料並套原本說話者身分政策。Agent token 不代表人類身分已驗證，未知使用者不能讀私人情境。

憑證在 Host 端使用 Keychain；Agent 端目前使用 0600 私有快取檔。uv 提供依賴隔離，並非 OS 沙箱。此整合不授權任意 UI action 執行命令或批准 filesystem/execution 操作。

詳細協定、信任邊界與簽章 key 生命週期來源：`/Users/Marvin/Workspace/Maltose_UI/docs/decisions/002-agent-bootstrap-runtime.md`。實作計畫與驗證：[feature](../features/maltose_ui_dev_plan.md)。
