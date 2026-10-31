# Awareness demo

1. 執行 two-agents/demo.py，點選並以圖表右上角框選工具拖曳區間。
2. Investment 的 ui.context.get 可取得 chart-synthetic 與 chart.time_range；Maltose 預設不可見。
3. ui.context.resolve_reference("this chart") 只會回傳有 evidence 與 freshness 的候選；歧義需使用者釐清。
4. 在 Host 的「跨代理分享」選擇 market-demo → agent.maltose。預設僅 summary；詳細 selection / viewport / document 必須分別勾選。
5. 獨立視窗後回附工作區，選取與 zoom 保留。撤銷分享會立即終止舊訂閱。
6. 重啟 Host：文件、layout、grant 與明確 zoom 偏好保留；focus、selection 不保留；stream 標記 stale，資料來源須重新註冊。
