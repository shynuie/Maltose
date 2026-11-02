# Development Agents

這裡放只服務於開發流程的 Agent 定義、prompt、review checklist 與角色規則。

這些檔案不屬於 `myagent/agent/` production runtime，也不應被產品程式碼
import。需要新增開發角色時，使用清楚的用途命名，例如：

- `kdb-maintainer.md`
- `architecture-reviewer.md`
- `test-engineer.md`
- `release-manager.md`

每個 development agent 檔案應說明：

1. 角色目標。
2. 可讀取與可修改的範圍。
3. 必須遵守的 repository rules。
4. 驗證與交付格式。

全局規則仍以根目錄的 `AGENTS.md` 為準。
