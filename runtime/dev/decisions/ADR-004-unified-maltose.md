# ADR 004：主 Agent 納入 Maltose

狀態：accepted；2026-11-01。

主 Agent 原始碼遷入 `runtime/maltose/`，公開套件和命令為 Maltose；依賴、說話者身分、Memory 與 KDB 邊界維持不變。原 MyAgent 倉庫歷史與未提交修改均保留，私有資料不加入新版本控制。

完整決策與回復方式見 [產品 ADR 005](../../../docs/decisions/005-unified-maltose-runtime.md)，執行狀態見 [整合 feature plan](../features/maltose_unification_dev_plan.md)。
