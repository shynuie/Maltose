# UI 架構

目前的 App 是純原生 UI 原型，不接 Agent 或 Host。主要元件分工如下：

1. `WorkspaceWindowManager` 管理每個螢幕的全螢幕窗口、面板歸屬與跨窗口拖放。
2. `WorkspaceRootView` 維護每個窗口的面板排列，提供全局、主面板與側欄模式，以及固定的上下狀態區。
3. `WorkspaceLayout` 保存排列狀態並計算 16:9 網格、初始欄數、縮放和側欄觸發。
4. `GlassPanelView` 提供統一 Glass 外框、選取高光、拖曳／雙擊操作與 Content 容器。
5. `WorkspacePanel` 提供可替換的原生示意內容；其狀態只在記憶體中。

完整互動與待校正項目見 [Glass 工作空間計劃](../../plans/glass-workspace.md)。
