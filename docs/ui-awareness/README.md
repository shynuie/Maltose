# Agent UI Awareness（P0）

snapshot 具 principal-scoped context_revision、captured_at、Host active state、授權後 focus 與 surfaces。表面包含 document_revision、selected_node_ids、semantic selection、viewport x_domain、layout screen_id、可描述的 visible_nodes 與最近語意 interaction。include 與 read scopes 雙重限制輸出。

Host focus 從 AppKit key window / first responder 取得；chart focus 與 interval selection 分開，縮放不會覆寫已選區間。Renderer 即時處理 ECharts zoom，120ms debounce 後回報 viewport；視窗移動/resize 150ms debounce。未串流 raw mouse coordinates 或 keystrokes。

`visible_nodes` 是可見 surface 內可呈現的非敏感文件節點，不等於逐像素遮擋/捲動可視區分析。chart viewport 提供實際 x_domain；未實作一般 DOM intersection/scroll 語意蒐集。

解析優先順序：explicit node > native focus + semantic focused node > active selection > recent interaction > exact title / visible candidates。相同最高分回 ambiguous；沒有新鮮候選回 requires_clarification。Host 不推斷自然語言含意。

context.focus_changed / selection_changed / viewport_changed / surface_visibility_changed / surface_moved / surface_detached / surface_attached / user_override_changed / stale / permission_changed 皆為協定事件；zoom override 另發出不含內容的 user_override_changed，詳細 viewport 仍依 viewport scope 過濾。

重連順序：authenticate → 新 session → 重新 subscribe(since_context_revision) → get 完整 snapshot → event sequence 去重/缺口偵測。權限變更時 SDK 清除 context cache；Host 取消 grantee 的舊訂閱。本機使用者需根據新 scope 重新建立訂閱。

context 的 `stale` 與資料的 `data_stale` 分離：前者依綁定 renderer 的最後存活回報判定，沒有新操作時仍保留原本的 interaction 時間與 context_revision；舊 epoch 不得刷新；後者只在 data scope 下提供，依節點引用 stream 是否存在且連線判定。stream 斷線、unregister 或 Host 重啟都不能宣稱資料仍新鮮。

MyAgent 每回合接收授權情境與人類身分邊界，見 [接入流程](../agent-integration.md) 與 [ADR 002](../decisions/002-agent-bootstrap-runtime.md)。
