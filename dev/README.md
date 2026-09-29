# Development Documentation

這個目錄是 MyAgent 的開發規劃、架構決策與進度紀錄的集中入口。

## 文件入口

- [Major Plan](major_plan.md)：全專案 roadmap、優先級與 feature 狀態。
- [KDB Feature Plan](features/kdb_dev_plan.md)：Document Knowledge Base 的詳細規格與進度。
- [Development Agents](agents/README.md)：只服務於開發流程的 Agent 定義與角色規則。
- [Feature Plan Template](templates/feature_plan.md)：新增大型 feature 時使用。
- [Progress Update Template](templates/progress_update.md)：記錄一次開發進度時使用。
- [ADR Template](templates/adr.md)：記錄不可逆或影響範圍較大的架構決策。

## Runtime data layout

```text
data/
├── knowledge/   # metadata、vectors、durable indexing queue
├── memory/      # Memory JSON/LanceDB state
├── speaker/     # enrolled speaker profiles
└── tasks/       # task and schedule state
```

Background KDB logs are written to `data/logs/knowledge.log` by `./start`;
the foreground Agent log remains in the terminal.

Model files belong under `models/`; user source documents belong under
`documents/`; neither belongs under `dev/`.

## 使用規則

1. `major_plan.md` 只放全局摘要、優先級與各 feature 的連結，不放實作細節。
2. 每個大型 feature 使用 `features/<feature>_dev_plan.md` 作為唯一詳細計畫。
3. 架構或責任邊界的決策寫在 `decisions/`，並從相關 feature plan 連結過去。
4. 每次完成一段工作，同步更新 feature plan 的 checkbox、驗證結果與下一步。
5. 狀態統一使用 `planned`、`in_progress`、`blocked`、`done`、`deferred`。
6. Markdown 是 source of truth；HTML 只在未來需要文件網站時由工具產生，不直接手動維護。

## 命名規則

- Feature plan：`features/<feature>_dev_plan.md`
- ADR：`decisions/ADR-<number>-<short-name>.md`
- Progress：`progress/YYYY-MM.md`
- Template：`templates/<document-type>.md`
