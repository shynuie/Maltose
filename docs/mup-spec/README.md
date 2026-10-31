# MUP v0.3

來源：`packages/mup-protocol/*.schema.json`，draft 2020-12。執行 `python3 scripts/generate-schemas.py` 更新來源與 Swift/Python 內嵌副本，再執行 `python3 scripts/generate-ts-schema.py` 更新 TypeScript。

1. WebSocket 只能連 `ws://127.0.0.1:<port>`；原生 app 由 OS 分配空閒 port 並發布私有 discovery 紀錄；只接受 text JSON，1 MiB，拒絕有 Origin 的瀏覽器握手。
2. 除了未認證的 host.discover / host.pair.request / host.pair.poll，第一個有權限 command 是 `host.authenticate {token}`，token 為本機使用者註冊時產生的 256-bit 隨機憑證，Keychain 保存。成功回傳 principal 與 **伺服器產生的新 session_id**；後續 command 使用該 session。
3. 明確協商 `host.capabilities`；protocol 欄位只能 mup/0.3。
4. response 以 request_id 關聯；ok/result 或 ok=false/error={code,message,details}。無效但合法 UUID 的 request_id 也盡可能關聯；不可解析時用零 UUID。
5. 同 session、同 request_id、同副作用重播回傳原結果；相同 ID 不同內容回 duplicate_request。持久副作用的 idempotency_key 跨 session / 重啟有效（最多 2048 最近保留項，容量淘汰）；資料副作用的 idempotency 僅在此 Host 執行期內有效。訂閱在重連時重新建立。
6. ui.render / ui.patch 要 expected_revision；不一致回 revision_conflict，無部分變更。支援 set_props / insert_node / remove_node / move_node；拒絕重複 ID、循環、移除 root、未知 node/action。
7. event 有 event_id、subscription_id、source_agent_id、surface_id、每訂閱遞增 sequence、timestamp、context_revision、minimal changes。缺口與 context.stale 要求 ui.context.get 完整同步。

命令清單：host.authenticate/capabilities；surface.create/list/get/set_visibility/close/detach/attach；ui.render/patch/inspect；events.subscribe/unsubscribe；data.register/publish/unregister；ui.context.get/subscribe/unsubscribe/resolve_reference。

各 payload 的精確可用欄位與型別請見 schema；unknown fields 拒絕。ui.context.get include 可選 focus / selection / viewport / layout / visible_nodes / interaction。since_context_revision 只作同步提示，仍回完整授權快照，避免 delta 合併時保留已撤銷資訊。

配額：32 agents、64 connections、每連線 200 commands/s、每代理 32 surfaces / 32 streams / 16 subscriptions、全 Host 256 surfaces、512 nodes / 512 KiB document、128 queued events / subscription。應用層尚未實作磁碟總量配額。

## Agent 接入擴充（MUP 版本仍是 0.3）

- `host.discover {}`：未認證探查，回 protocol、instance_id、host_id、name、pairing；不回畫面或其他代理資訊。
- `host.pair.request {name, agent_id, claim}`：最少 32 bytes claim；回 pairing_id、verification_code、expires_at。名稱與 ID 為自報資訊，原生使用者核對後批准。
- `host.pair.poll {pairing_id, claim}`：pending / approving / denied / claimed；批准時一次回 token 與 principal。沒有遠端 approve／deny／授權 API。
- `host.toolkit.get {}`：認證後回 manifest、publisher signature 與 wheel_base64；bootstrap 驗證固定公鑰、合約與雜湊後才安裝。
- `agent.runtime.publish {run_id, sequence, event, data}`：認證 principal 決定狀態所有者；同一存活 session/run，sequence 嚴格增加。data 按 event 限制必要欄位，不接受 agent_id。
- `agent.input.poll {}`：僅取出該認證 session 的原生使用者輸入，最多 32 筆；不是跨代理訊息 API。

runtime 事件為 heartbeat、state_changed、model_started/finished/failed、tool_started/finished/failed、speech_started/finished、assistant_start/delta/end、user_message、task_progress、error。狀態每 Agent 最多保存 20 則訊息、每則 16,384 字元；15 秒無心跳視為逾時，斷線清除活動與該 session 未領取輸入。沒有聲稱提供模型內部思考內容。
