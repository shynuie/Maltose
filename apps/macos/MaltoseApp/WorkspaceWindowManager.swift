import AppKit
import SwiftUI

private struct AgentWorkspaceSnapshot {
    let state: WorkspaceLayoutState
    let zoom: CGFloat
    let scrollOffset: CGFloat
}

@MainActor final class WorkspaceWindowManager {
    private(set) var catalog: [WorkspacePanel]
    let automaticallyFullscreen: Bool
    private(set) var transitioningScreenID: String?
    private(set) var fullscreenFailures: Set<String> = []
    private var fullscreenAttempted: Set<String> = []
    private var fullscreenTask: Task<Void, Never>?
    private var coreAnimationTestWindowController: AgentCoreTestWindowController?
    private var userViewTestWindowController: UserViewTestWindowController?
    private var agentInteractionTestTask: Task<Void, Never>?
    private var lastActiveWorkspaceScreenID: String?
    private(set) var windows: [String: NSWindow] = [:]
    private(set) var roots: [String: WorkspaceRootView] = [:]
    private(set) var panels: [String: GlassPanelView] = [:]
    private(set) var assignments: [String: String] = [:]
    private(set) var draggingIDs: [String] = []
    var draggingID: String? { draggingIDs.first }
    private var dragSourceScreenID: String?
    private var originalDragState: WorkspaceLayoutState?
    private var dragCommitted = false
    private var screenObserver: NSObjectProtocol?
    private var resignObserver: NSObjectProtocol?

    init(catalog: [WorkspacePanel] = WorkspacePanel.samples, automaticallyFullscreen: Bool = true) {
        self.catalog = catalog
        self.automaticallyFullscreen = automaticallyFullscreen
        screenObserver = NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.synchronize() }
        }
        resignObserver = NotificationCenter.default.addObserver(forName: NSApplication.didResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                for root in self.roots.values { root.cancelHover(collapse: true) }
            }
        }
    }

    static func screenID(_ screen: NSScreen) -> String {
        "screen-\(screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? "unknown")"
    }

    func synchronize() {
        guard !NSScreen.screens.isEmpty else { return }
        let screens = NSScreen.screens
        let screenIDs = screens.map(Self.screenID)
        let fallback = screenIDs[0]
        let surfaces = catalog
        let allIDs = Set(surfaces.map(\.id))
        for id in Array(panels.keys) where !allIDs.contains(id) {
            panels[id]?.removeFromSuperview()
            panels.removeValue(forKey: id)?.dispose()
            assignments.removeValue(forKey: id)
        }
        for screen in screens {
            let id = Self.screenID(screen)
            if windows[id] == nil {
                let window = WorkspaceWindow(contentRect: screen.frame, styleMask: [.titled, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
                window.title = "Maltose · \(screen.localizedName)"
                window.titleVisibility = .hidden
                window.titlebarAppearsTransparent = true
                window.isMovable = false
                window.isMovableByWindowBackground = false
                window.standardWindowButton(.closeButton)?.isHidden = true
                window.standardWindowButton(.miniaturizeButton)?.isHidden = true
                window.standardWindowButton(.zoomButton)?.isHidden = true
                window.backgroundColor = .clear
                window.isOpaque = false
                window.isReleasedWhenClosed = false
                window.isExcludedFromWindowsMenu = false
                window.acceptsMouseMovedEvents = true
                window.collectionBehavior = NSScreen.screensHaveSeparateSpaces || id == fallback
                    ? [.fullScreenPrimary, .fullScreenDisallowsTiling] : [.fullScreenAuxiliary]
                let root = WorkspaceRootView(screenID: id, manager: self)
                window.contentView = root
                window.delegate = root
                windows[id] = window
                roots[id] = root
                NSApp.addWindowsItem(window, title: window.title, filename: false)
                window.setFrame(screen.frame, display: true)
                window.orderFront(nil)
            } else { restoreWindowFrame(id) }
        }
        for surface in surfaces {
            if assignments[surface.id] == nil { assignments[surface.id] = fallback }
            if !screenIDs.contains(assignments[surface.id] ?? "") { assignments[surface.id] = fallback }
            if panels[surface.id] == nil { panels[surface.id] = GlassPanelView(panel: surface, manager: self) }
            panels[surface.id]?.title = surface.title
            let target = assignments[surface.id].flatMap { windows[$0] }
            if panels[surface.id]?.window !== target { panels[surface.id]?.removeFromSuperview() }
        }
        for id in screenIDs {
            let ids = surfaces.filter { assignments[$0.id] == id }.map(\.id)
            roots[id]?.update(panelIDs: ids)
        }
        for id in Array(windows.keys) where !screenIDs.contains(id) {
            roots.removeValue(forKey: id)?.dispose()
            if let window = windows.removeValue(forKey: id) { NSApp.removeWindowsItem(window); window.orderOut(nil) }
        }
        if automaticallyFullscreen { enterNextFullscreen() }
    }

    func togglePanel(_ id: String) {
        guard catalog.first(where: { $0.id == id })?.supportsFocusedMode != false else { return }
        guard let screen = assignments[id], let root = roots[screen] else { return }
        root.state.toggle(id)
        root.cancelHover(collapse: false)
        root.arrange(animated: true)
        focus(id)
    }
    func selectPanel(_ id: String) {
        guard let screen = assignments[id], let root = roots[screen] else { return }
        root.state.select(id)
        root.arrange(animated: true)
        focus(id)
    }
    func highlightPanel(_ id: String, extending: Bool) {
        guard let screen = assignments[id], let root = roots[screen] else { return }
        root.state.highlight(id, extending: extending)
        root.arrange(animated: true)
        focus(id)
    }
    func focus(_ id: String) {
        if let screen = assignments[id] { windows[screen]?.makeKeyAndOrderFront(nil) }
    }
    func showGrid() {
        guard let root = activeRoot else { return }
        root.state.mode = .grid
        root.cancelHover(collapse: false)
        root.arrange(animated: true)
    }
    var activeRoot: WorkspaceRootView? {
        if let active = roots.values.first(where: { $0.window?.isKeyWindow == true }) {
            lastActiveWorkspaceScreenID = active.screenID
            return active
        }
        if let lastActiveWorkspaceScreenID, let active = roots[lastActiveWorkspaceScreenID] { return active }
        return roots.values.first
    }
    func showWindows() {
        for window in windows.values { window.orderFront(nil) }
        windows.values.first?.makeKeyAndOrderFront(nil)
    }
    func showCoreAnimationTest() {
        if coreAnimationTestWindowController == nil {
            coreAnimationTestWindowController = AgentCoreTestWindowController()
        }
        coreAnimationTestWindowController?.present()
    }

    func noteActiveWorkspace(_ screenID: String) {
        guard roots[screenID] != nil else { return }
        lastActiveWorkspaceScreenID = screenID
    }

    func showUserViewTest() {
        _ = activeRoot
        if userViewTestWindowController == nil {
            userViewTestWindowController = UserViewTestWindowController(
                model: UserViewTestModel { [weak self] in
                    guard let self else { throw UserViewCaptureError.workspaceUnavailable }
                    return try await self.getUserView()
                })
        }
        userViewTestWindowController?.present()
    }

    /// Agent-facing read-only interface for the currently visible workspace UI.
    func getUserView() async throws -> UserViewSnapshot {
        guard !roots.isEmpty else { throw UserViewCaptureError.workspaceUnavailable }
        let activeScreenID = activeRoot?.screenID
        var workspaces: [UserWorkspaceView] = []
        for root in roots.values.sorted(by: { $0.screenID < $1.screenID }) {
            let mode = root.state.mode
            let screen = NSScreen.screens.first { Self.screenID($0) == root.screenID }
            let IDs = root.state.panelIDs
            var panels: [UserPanelView] = []
            var visibleIDs: [String] = []
            var hiddenIDs: [String] = []

            for id in IDs {
                guard let panel = panelsByID(id) else { continue }
                let presentation: String
                let isVisible: Bool
                switch mode {
                case .grid:
                    let frame = panel.convert(panel.bounds, to: root)
                    isVisible = frame.intersects(root.globalViewportFrame)
                    presentation = isVisible ? "globalCell" : "offscreen"
                case .focused:
                    isVisible = id == root.state.primaryID
                    presentation = isVisible ? "mainPanel" : "hidden"
                case .sidebar:
                    isVisible = id == root.state.primaryID
                        || panel.convert(panel.bounds, to: root).intersects(root.sidebar.frame)
                    presentation = id == root.state.primaryID ? "mainPanel" : "sidebarThumbnail"
                }

                if isVisible { visibleIDs.append(id) } else { hiddenIDs.append(id) }
                let details = isVisible ? await panelDetails(panel, presentation: presentation) : [:]
                let kind = catalog.first(where: { $0.id == id })?.kind
                panels.append(UserPanelView(panelID: id,
                                            kind: kind.map(kindName) ?? "unknown",
                                            title: panel.title,
                                            presentation: presentation,
                                            isSelected: root.state.selectedIDs.contains(id),
                                            details: details))
            }

            let grid: [String: UserViewValue]
            if mode == .grid {
                let geometry = root.globalGridGeometry
                grid = [
                    "columns": .number(Double(geometry.columns)),
                    "rows": .number(Double(geometry.rows)),
                    "zoom": .number(Double(root.agentTestGridZoom)),
                    "scrollOffsetY": .number(Double(root.globalScrollOffset))
                ]
            } else { grid = [:] }
            var overlays: [String] = []
            if root.chromeHasTips { overlays.append("使用提示") }
            if root.chromeHasSettings { overlays.append("空間設定") }
            if root.panelIDsAreEmpty { overlays.append("空工作區提示") }

            workspaces.append(UserWorkspaceView(screenID: root.screenID,
                                                screenName: screen?.localizedName ?? root.screenID,
                                                mode: modeName(mode),
                                                isActive: root.screenID == activeScreenID,
                                                primaryPanelID: root.state.primaryID,
                                                selectedPanelIDs: root.state.selectedIDs.sorted(),
                                                visiblePanelIDs: visibleIDs,
                                                offscreenPanelIDs: hiddenIDs,
                                                overlays: overlays,
                                                globalGrid: grid,
                                                panels: panels))
        }
        return UserViewSnapshot(schemaVersion: 1,
                                capturedAt: ISO8601DateFormatter().string(from: Date()),
                                activeScreenID: activeScreenID,
                                workspaces: workspaces)
    }

    private func panelsByID(_ id: String) -> GlassPanelView? { panels[id] }

    private func modeName(_ mode: WorkspaceMode) -> String {
        switch mode {
        case .grid: "全局排列"
        case .focused: "面板全屏"
        case .sidebar: "面板＋側欄"
        }
    }

    private func kindName(_ kind: WorkspacePanel.Kind) -> String {
        switch kind {
        case .agentIdentity: "agentIdentity"
        case .agentCoreTest: "agentCoreTest"
        case .browser: "browser"
        case .canvas: "flowchartCanvas"
        case .chart: "lineChart"
        case .conversationHistory: "conversation"
        case .document: "markdownDocument"
        case .imageGallery: "imageGallery"
        case .notes: "notes"
        case .table: "table"
        }
    }

    private func panelDetails(_ panel: GlassPanelView, presentation: String) async -> [String: UserViewValue] {
        if let model = panel.conversationHistoryModel {
            let session = model.currentSession
            let focused = !panel.isGlobal && !panel.isPreview
            let readable = ConversationHistoryLayout(width: panel.contentBounds.width, focused: focused).showsText
            var details: [String: UserViewValue] = [
                "sessionID": .string(session?.id ?? ""),
                "sessionTitle": .string(session?.title ?? ""),
                "textVisibleAtCurrentSize": .boolean(readable),
                "presentationMode": .string(presentation)
            ]
            if readable, let session {
                details["recentMessages"] = .strings(session.messages.suffix(12).map { message in
                    let role = message.speaker == .user ? "使用者" : "Agent"
                    return "\(role)：\(String(message.text.prefix(700)))"
                })
            }
            return details
        }
        if let model = panel.markdownDocumentModel {
            let focused = !panel.isGlobal && !panel.isPreview
            let readable = MarkdownDocumentLayout(width: panel.contentBounds.width, focused: focused).showsText
            let excerpts = model.blocks.compactMap(markdownExcerpt).prefix(32)
            var details: [String: UserViewValue] = [
                "blockCount": .number(Double(model.blocks.count)),
                "textVisibleAtCurrentSize": .boolean(readable),
                "presentationMode": .string(presentation)
            ]
            if readable { details["contentExcerpt"] = .strings(Array(excerpts)) }
            else {
                details["imageBlocks"] = .strings(model.blocks.compactMap { block in
                    if case let .image(alt, source) = block.content { return "\(alt)：\(source)" }
                    return nil
                })
            }
            return details
        }
        if let model = panel.chartModel {
            let names = model.data.seriesNames
            let bands = model.filledBands.compactMap { band, opacity -> String? in
                guard names.indices.contains(band.firstSeries), names.indices.contains(band.secondSeries) else { return nil }
                return "\(names[band.firstSeries]) ↔ \(names[band.secondSeries]) (alpha \(opacity))"
            }
            var details: [String: UserViewValue] = [
                "source": .string(model.sourceName),
                "xAxis": .string(model.data.xTitle),
                "rowCount": .number(Double(model.data.rows.count)),
                "series": .strings(names),
                "visibleSeries": .strings(model.visibleSeries.sorted().compactMap { names.indices.contains($0) ? names[$0] : nil }),
                "xZoom": .number(Double(model.xZoom)),
                "xPan": .number(model.xPan),
                "filledBands": .strings(bands)
            ]
            if let hovered = model.hoveredPoint {
                details["hoveredPoint"] = .object([
                    "x": .string(hovered.xLabel),
                    "series": .string(hovered.seriesName),
                    "value": .number(hovered.value),
                    "note": .string(hovered.note)
                ])
            }
            return details
        }
        if let model = panel.imageGalleryModel {
            let image = model.selectedImage
            var details: [String: UserViewValue] = [
                "selectedIndex": .number(Double(model.selectedIndex)),
                "imageCount": .number(Double(model.images.count)),
                "isExpanded": .boolean(model.expandedIndex != nil),
                "zoomScale": .number(Double(model.zoomScale)),
                "panX": .number(Double(model.panOffset.width)),
                "panY": .number(Double(model.panOffset.height))
            ]
            if let image {
                details["imageTitle"] = .string(image.title)
                switch image.source {
                case .sample: details["source"] = .string("內建範例")
                case let .remote(url): details["source"] = .string(url.absoluteString)
                case .local: details["source"] = .string("本機圖片：\(image.title)")
                }
            }
            return details
        }
        if let model = panel.browserModel { return await model.userViewDetails() }
        if let model = panel.flowchartModel {
            return [
                "documentTitle": .string(model.documentTitle),
                "nodeCount": .number(Double(model.nodes.count)),
                "connectionCount": .number(Double(model.connections.count)),
                "selectedNodes": .strings(model.nodes.filter { model.selectedNodeIDs.contains($0.id) }.map { "\($0.type.title)：\($0.text)" }),
                "nodes": .strings(model.nodes.map { "\($0.id) | \($0.type.rawValue) | \($0.text) | (\(Int($0.position.x)), \(Int($0.position.y)))" }),
                "connections": .strings(model.connections.map { edge in
                    let source = model.nodes.first(where: { $0.id == edge.fromNodeID })?.text ?? edge.fromNodeID
                    let target = model.nodes.first(where: { $0.id == edge.toNodeID })?.text ?? edge.toNodeID
                    return "\(source) → \(target)\(edge.label.map { " [\($0)]" } ?? "")"
                })
            ]
        }
        if let model = panel.sampleContentModel, catalog.first(where: { $0.id == panel.surfaceID })?.kind == .notes {
            return ["text": .string(String(model.note.prefix(4000)))]
        }
        if catalog.first(where: { $0.id == panel.surfaceID })?.kind == .table {
            let rows = (0..<8).map { index in
                "\(String(format: "%02d", index + 1)) | \(["工作空間", "面板排列", "內容尺寸", "互動狀態"][index % 4]) | \(index % 2 == 0 ? "進行中" : "待確認")"
            }
            return ["rowCount": .number(Double(rows.count)), "visibleRows": .strings(rows)]
        }
        if catalog.first(where: { $0.id == panel.surfaceID })?.kind == .agentIdentity {
            return ["animationState": .string(AgentIdentityAnimationModel.shared.preset.title)]
        }
        return [:]
    }

    private func markdownExcerpt(_ block: MarkdownDocumentBlock) -> String? {
        switch block.content {
        case let .heading(level, text): "\(String(repeating: "#", count: level)) \(text)"
        case let .paragraph(text): String(text.prefix(500))
        case let .bullet(text): "• \(text)"
        case let .quote(text): "> \(text)"
        case let .code(language, source): "程式碼（\(language ?? "text")）：\(String(source.prefix(500)))"
        case let .table(rows): "表格：\(rows.prefix(4).map { $0.joined(separator: " | ") }.joined(separator: " / "))"
        case let .image(alt, source): "圖片：\(alt)（\(source)）"
        case .divider: nil
        }
    }

    /// Adds a new workspace panel instance and returns its stable identifier.
    /// Identity and chat are singleton panel types; the animation playground is not a workspace panel.
    @discardableResult func addPanel(kind: WorkspacePanel.Kind, to screenID: String? = nil) -> WorkspacePanel? {
        guard kind != .agentCoreTest,
              kind.allowsMultipleInstances || !catalog.contains(where: { $0.kind == kind }) else { return nil }
        let id: String
        switch kind {
        case .agentIdentity: id = "agent-identity"
        case .conversationHistory: id = "chat"
        default: id = "\(kind.defaultInstanceTitle.lowercased())-\(UUID().uuidString.lowercased())"
        }
        let instanceNumber = catalog.filter { $0.kind == kind }.count + 1
        let panel = WorkspacePanel(id: id, title: "\(kind.defaultInstanceTitle) \(instanceNumber)", kind: kind)
        catalog.append(panel)
        if let screenID, windows[screenID] != nil { assignments[id] = screenID }
        synchronize()
        return panel
    }

    /// Removes one panel instance. Singleton types may be closed and later recreated.
    @discardableResult func closePanel(_ id: String) -> Bool {
        guard catalog.contains(where: { $0.id == id }) else { return false }
        if draggingIDs.contains(id) { endDrag() }
        catalog.removeAll { $0.id == id }
        synchronize()
        return true
    }

    /// Exercises the same high-level workspace and panel APIs an agent will use.
    /// Every temporary layout/model change is restored when the run finishes.
    func runAgentInteractionTest() {
        guard agentInteractionTestTask == nil, let activeRoot else { return }
        let rootSnapshots = roots.mapValues {
            AgentWorkspaceSnapshot(state: $0.state, zoom: $0.agentTestGridZoom,
                                   scrollOffset: $0.globalScrollOffset)
        }
        let assignmentSnapshot = assignments
        let selectedScreenID = activeRoot.screenID
        let chatScreenID = assignmentSnapshot["chat"] ?? selectedScreenID
        let chatModel = assignmentSnapshot["chat"] == selectedScreenID ? panels["chat"]?.conversationHistoryModel : nil
        let originalSessionID = chatModel?.currentSessionID
        let chartModel = assignmentSnapshot["chart"] == selectedScreenID ? panels["chart"]?.chartModel : nil
        let galleryModel = assignmentSnapshot["gallery"] == selectedScreenID ? panels["gallery"]?.imageGalleryModel : nil
        let originalGalleryIndex = galleryModel?.selectedIndex ?? 0
        let originalSeries = chartModel.map { model in
            model.visibleSeries.sorted().compactMap { model.data.seriesNames.indices.contains($0) ? model.data.seriesNames[$0] : nil }
        } ?? []
        let originalBands = chartModel.map { model in
            model.filledBands.map { band, opacity in
                CSVLineChartBandRequest(firstSeriesName: model.data.seriesNames[band.firstSeries],
                                        secondSeriesName: model.data.seriesNames[band.secondSeries], opacity: opacity)
            }
        } ?? []
        let originalChartZoom = chartModel?.xZoom ?? 1
        let originalChartPan = chartModel?.xPan ?? 0
        var addedPanelIDs: [String] = []

        func status(_ value: String) {
            for root in self.roots.values { root.setAgentTestStatus(value) }
        }

        AgentIdentityAnimationModel.shared.runStateTest()
        agentInteractionTestTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                for id in addedPanelIDs.reversed() { _ = self.closePanel(id) }
                self.assignments = assignmentSnapshot
                self.synchronize()
                for (screenID, snapshot) in rootSnapshots {
                    self.roots[screenID]?.restoreAgentTestState(snapshot.state, zoom: snapshot.zoom,
                                                                scrollOffset: snapshot.scrollOffset)
                }
                if let chatModel, let originalSessionID,
                   let session = chatModel.sessions.first(where: { $0.id == originalSessionID }) {
                    chatModel.configure(mode: .focused)
                    chatModel.selectSession(session)
                }
                chatModel?.configure(mode: rootSnapshots[chatScreenID]?.state.mode ?? .grid)
                chartModel?.configureAgentVisibleSeries(originalSeries)
                chartModel?.configureAgentBands(originalBands)
                chartModel?.setXAxisViewport(zoom: originalChartZoom, pan: originalChartPan)
                galleryModel?.collapse()
                galleryModel?.selectImage(at: originalGalleryIndex)
                status("測試完成")
                self.agentInteractionTestTask = nil
            }

            let root = self.roots[selectedScreenID] ?? self.activeRoot
            guard let root else { return }
            let steps: [(String, @MainActor () -> Void)] = [
                ("測試：檢視提示與設定", {
                    root.setAgentTestOverlay(tips: true, settings: false)
                }),
                ("測試：調整全局排列比例", {
                    root.setAgentTestOverlay(tips: false, settings: true)
                    root.setGlobalZoom(0.28)
                }),
                ("測試：多選並重新排列面板", {
                    root.setAgentTestOverlay(tips: false, settings: false)
                    root.state.mode = .grid
                    root.state.selectedIDs = Set(["chat", "chart"])
                    let columns = root.globalGridGeometry.columns
                    _ = root.state.repositionPanels(["chart"], to: WorkspaceGridPosition(row: 2, column: 0), columns: columns)
                    root.arrange(animated: true)
                }),
                ("測試：新增多個面板並檢查單例限制", {
                    root.setAgentTestMode(.grid)
                    for kind in [WorkspacePanel.Kind.chart, .notes, .document, .imageGallery, .browser, .table, .canvas] {
                        if let panel = self.addPanel(kind: kind, to: selectedScreenID) {
                            addedPanelIDs.append(panel.id)
                        }
                    }
                    for kind in [WorkspacePanel.Kind.agentIdentity, .conversationHistory] {
                        if let panel = self.addPanel(kind: kind, to: selectedScreenID) {
                            addedPanelIDs.append(panel.id)
                        }
                    }
                }),
                ("測試：網頁面板開啟離線測試頁", {
                    guard let browserID = addedPanelIDs.first(where: { id in
                        self.catalog.first(where: { $0.id == id })?.kind == .browser
                    }) else { return }
                    self.selectPanel(browserID)
                    self.panels[browserID]?.browserModel?.simulateTestPage()
                }),
                ("測試：建立並編輯流程圖", {
                    guard let canvasID = addedPanelIDs.first(where: { id in
                        self.catalog.first(where: { $0.id == id })?.kind == .canvas
                    }), let model = self.panels[canvasID]?.flowchartModel else { return }
                    let stepID = model.addNode(.process, at: FlowchartPoint(x: -80, y: 250))
                    model.updateText("檢查流程條件", for: stepID)
                    _ = model.connect(from: "flow-start", to: stepID)
                    model.selectNode(stepID)
                    model.moveNodes([stepID], by: CGSize(width: 28, height: 16))
                    model.setZoom(1.1)
                    model.pan(by: CGSize(width: 12, height: -8))
                    model.deleteSelection()
                }),
                ("測試：關閉新建的面板", {
                    for id in addedPanelIDs.reversed() { _ = self.closePanel(id) }
                    addedPanelIDs.removeAll()
                }),
                ("測試：切換聊天紀錄", {
                    if assignmentSnapshot["chat"] == selectedScreenID { self.selectPanel("chat") }
                    if let session = chatModel?.sessions.first(where: { $0.id != originalSessionID }) {
                        chatModel?.selectSession(session)
                    }
                }),
                ("測試：展開側欄檢視", {
                    root.setAgentTestMode(.sidebar)
                }),
                ("測試：檢視 Markdown 面板", {
                    if assignmentSnapshot["document"] == selectedScreenID { self.selectPanel("document") }
                }),
                ("測試：建立互動線圖", {
                    if assignmentSnapshot["chart"] == selectedScreenID { self.selectPanel("chart") }
                    if let chartModel {
                        let names = chartModel.data.seriesNames
                        chartModel.configureAgentVisibleSeries(Array(names.prefix(2)))
                        if names.count > 1 {
                            chartModel.configureAgentBands([
                                CSVLineChartBandRequest(firstSeriesName: names[0], secondSeriesName: names[1], opacity: 0.2)
                            ])
                        }
                        chartModel.setXAxisViewport(zoom: 1.8, pan: 0)
                    }
                }),
                ("測試：瀏覽圖片、放大與平移", {
                    if assignmentSnapshot["gallery"] == selectedScreenID {
                        self.selectPanel("gallery")
                        galleryModel?.selectImage(at: 3)
                        galleryModel?.expandImage(at: 3)
                        galleryModel?.beginMagnification()
                        galleryModel?.updateMagnification(1.8)
                        galleryModel?.beginPan()
                        galleryModel?.updatePan(CGSize(width: 30, height: 18))
                    }
                }),
                ("測試：返回圖片預覽並切換", {
                    galleryModel?.collapse()
                    galleryModel?.move(by: -1)
                }),
                ("測試：切換資料與畫布面板", {
                    if assignmentSnapshot["table"] == selectedScreenID { self.selectPanel("table") }
                    if assignmentSnapshot["canvas"] == selectedScreenID { self.selectPanel("canvas") }
                }),
                ("測試：返回全局排列", {
                    root.setAgentTestMode(.grid)
                    root.setAgentTestOverlay(tips: false, settings: false)
                })
            ]

            for (index, step) in steps.enumerated() {
                guard !Task.isCancelled else { return }
                status("\(index + 1)/\(steps.count) · \(step.0)")
                step.1()
                do { try await Task.sleep(for: .milliseconds(950)) }
                catch { return }
            }
            status("測試：核心五種狀態（每種 3 秒）")
            do { try await Task.sleep(for: .seconds(8)) }
            catch { return }
        }
    }
    func restoreWindowFrame(_ screenID: String) {
        guard let screen = NSScreen.screens.first(where: { Self.screenID($0) == screenID }),
              let window = windows[screenID], !window.styleMask.contains(.fullScreen),
              roots[screenID]?.fullScreenTransitioning != true, window.frame != screen.frame else { return }
        window.setFrame(screen.frame, display: true)
    }

    /// Fullscreen transitions must be serialized; concurrent toggles can be rejected by AppKit.
    private func enterNextFullscreen(preferred: String? = nil) {
        guard transitioningScreenID == nil else { return }
        let eligible = NSScreen.screens.map(Self.screenID).filter {
            windows[$0] != nil && !fullscreenAttempted.contains($0)
                && (NSScreen.screensHaveSeparateSpaces || $0 == Self.screenID(NSScreen.screens[0]))
        }
        let chosen = preferred.flatMap { eligible.contains($0) ? $0 : nil } ?? eligible.first
        guard let id = chosen, let window = windows[id] else { return }
        fullscreenAttempted.insert(id)
        transitioningScreenID = id
        roots[id]?.fullScreenTransitioning = true
        fullscreenTask = Task { [weak self, weak window] in
            do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
            guard let self, let window else { return }
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            window.toggleFullScreen(nil)
            do { try await Task.sleep(for: .seconds(8)) } catch { return }
            // Some system configurations reject a transition without delivering completion.
            self.finishedFullscreen(id, succeeded: window.styleMask.contains(.fullScreen))
        }
    }
    func enterFullscreenForActiveWindow() {
        guard transitioningScreenID == nil, let root = activeRoot, !root.fullScreenTransitioning,
              let window = root.window else { return }
        if window.styleMask.contains(.fullScreen) { window.toggleFullScreen(nil); return }
        fullscreenAttempted.remove(root.screenID)
        enterNextFullscreen(preferred: root.screenID)
    }
    func finishedFullscreen(_ id: String, succeeded: Bool) {
        roots[id]?.fullScreenTransitioning = false
        roots[id]?.setNativeFullscreen(succeeded)
        if !succeeded { fullscreenFailures.insert(id); restoreWindowFrame(id) }
        if transitioningScreenID == id {
            fullscreenTask?.cancel()
            transitioningScreenID = nil
            if automaticallyFullscreen { enterNextFullscreen() }
        }
    }

    func beginDrag(_ id: String) {
        guard let screen = assignments[id], let source = roots[screen] else { return }
        source.cancelPendingPanelSelection()
        if source.state.selectedIDs.contains(id) {
            draggingIDs = source.state.panelIDs.filter { source.state.selectedIDs.contains($0) }
        } else {
            source.state.highlight(id, extending: false)
            source.arrange(animated: false)
            draggingIDs = [id]
        }
        dragSourceScreenID = screen
        originalDragState = source.state
        dragCommitted = false
        for draggedID in draggingIDs { panels[draggedID]?.alphaValue = 0.28 }
        for root in roots.values { root.cancelHover(collapse: false) }
    }
    func acceptsDrag(_ info: NSDraggingInfo) -> Bool {
        guard !draggingIDs.isEmpty, info.draggingSource is GlassPanelView,
              let ids = info.draggingPasteboard.propertyList(forType: .maltosePanels) as? [String] else { return false }
        return ids == draggingIDs
    }

    func isDraggingFrom(_ screenID: String) -> Bool { dragSourceScreenID == screenID }

    func previewDraggedPanels(to screenID: String, position: WorkspaceGridPosition, columns: Int) {
        guard dragSourceScreenID == screenID, let root = roots[screenID] else { return }
        let beforeIDs = root.state.panelIDs
        let beforeIdentityPosition = root.state.identityPosition
        guard root.state.repositionPanels(draggingIDs, to: position, columns: columns) else { return }
        guard beforeIDs != root.state.panelIDs || beforeIdentityPosition != root.state.identityPosition else { return }
        root.arrange(animated: true)
    }

    @discardableResult func moveDraggedPanels(to screenID: String) -> Bool {
        guard !draggingIDs.isEmpty, let target = roots[screenID], draggingIDs.allSatisfy({ panels[$0] != nil }) else { return false }
        let ids = draggingIDs
        guard let sourceScreen = assignments[ids[0]], ids.allSatisfy({ assignments[$0] == sourceScreen }) else { return false }
        let source = roots[sourceScreen]
        if sourceScreen == screenID {
            dragCommitted = true
            return true
        }
        if sourceScreen != screenID {
            let movedIdentityPosition = source?.state.identityPosition
            source?.state = originalDragState ?? source?.state ?? WorkspaceLayoutState()
            for id in ids {
                panels[id]?.removeFromSuperview()
                assignments[id] = screenID
            }
            if ids.contains("agent-identity"), let movedIdentityPosition {
                target.state.identityPosition = movedIdentityPosition
            }
            target.state.primaryID = ids[0]
            target.state.selectedIDs = Set(ids)
            synchronize()
            source?.arrange(animated: true)
            target.arrange(animated: true)
        }
        dragCommitted = true
        focus(ids[0])
        return true
    }
    @discardableResult func moveDraggedPanel(to screenID: String) -> Bool { moveDraggedPanels(to: screenID) }
    func endDrag(committed: Bool = false) {
        if !committed, !dragCommitted,
           let dragSourceScreenID, let root = roots[dragSourceScreenID], let originalDragState {
            root.state = originalDragState
            root.arrange(animated: true)
        }
        for id in draggingIDs { panels[id]?.alphaValue = 1 }
        draggingIDs = []
        dragSourceScreenID = nil
        originalDragState = nil
        dragCommitted = false
        for root in roots.values { root.pointerMoved() }
    }
    func stop() {
        fullscreenTask?.cancel()
        agentInteractionTestTask?.cancel()
        agentInteractionTestTask = nil
        transitioningScreenID = nil
        coreAnimationTestWindowController?.close()
        coreAnimationTestWindowController = nil
        userViewTestWindowController?.close()
        userViewTestWindowController = nil
        if let screenObserver { NotificationCenter.default.removeObserver(screenObserver) }
        if let resignObserver { NotificationCenter.default.removeObserver(resignObserver) }
        for root in roots.values { root.dispose() }
        for panel in panels.values { panel.dispose() }
        for window in windows.values { NSApp.removeWindowsItem(window); window.delegate = nil; window.close() }
        roots.removeAll(); panels.removeAll(); windows.removeAll()
    }
}

@MainActor final class WorkspaceWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
    override func cancelOperation(_ sender: Any?) {
        guard let root = contentView as? WorkspaceRootView else { return }
        root.manager?.showGrid()
    }
}
