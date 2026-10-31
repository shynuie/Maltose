import AppKit
import SwiftUI

@MainActor final class WorkspaceRootView: NSView, NSWindowDelegate {
    let screenID: String
    weak var manager: WorkspaceWindowManager?
    var state = WorkspaceLayoutState()
    let sidebar = NSScrollView()
    private let thumbnails = FlippedWorkspaceView()
    private let canvas = FlippedWorkspaceView()
    private let globalScroll = NSScrollView()
    private let globalDocument = FlippedWorkspaceView()
    private let chrome: WorkspaceChromeModel
    private let topChrome: NSHostingView<WorkspaceTopChrome>
    private let bottomChrome: NSHostingView<WorkspaceBottomChrome>
    private let tipsDropdown: NSHostingView<WorkspaceTipsDropdown>
    private let settingsPlaceholder: NSHostingView<WorkspaceSettingsPlaceholder>
    private var emptyView: NSView?
    private let backdrop = NSVisualEffectView()
    private let backgroundTint = NSView()
    var fullScreenTransitioning = false
    private(set) var nativeFullscreen = false
    private var tracking: NSTrackingArea?
    private var eventMonitor: Any?
    private var hoverTask: Task<Void, Never>?
    private var dwell = SidebarDwell()
    private var arrangedIDs: [String] = []
    private var lastArrangedMode: WorkspaceMode?
    private var gridZoom: CGFloat = -1
    private var gridScrollOffset: CGFloat = 0
    private var isAdjustingScroll = false
    private var isAnimatingModeTransition = false
    private var wheelGesture = WorkspaceWheelGesture()
    private(set) var workspaceFrame = CGRect.zero
    private let chromeTopHeight: CGFloat = 66
    private let chromeBottomHeight: CGFloat = 78
    private let chromeGap: CGFloat = 8
    override var isFlipped: Bool { true }

    var globalViewportFrame: CGRect { globalScroll.frame }
    var topChromeFrame: CGRect { topChrome.frame }
    var bottomChromeFrame: CGRect { bottomChrome.frame }
    var chromeIsVisible: Bool { !topChrome.isHidden && !bottomChrome.isHidden }
    var globalScrollOffset: CGFloat { gridScrollOffset }
    var globalGridGeometry: WorkspaceGeometry.GlobalGrid { makeGlobalGrid(viewport: globalScroll.contentView.bounds.size) }

    init(screenID: String, manager: WorkspaceWindowManager) {
        self.screenID = screenID
        self.manager = manager
        let model = WorkspaceChromeModel()
        chrome = model
        topChrome = NSHostingView(rootView: WorkspaceTopChrome(model: model))
        bottomChrome = NSHostingView(rootView: WorkspaceBottomChrome(model: model))
        tipsDropdown = NSHostingView(rootView: WorkspaceTipsDropdown())
        settingsPlaceholder = NSHostingView(rootView: WorkspaceSettingsPlaceholder())
        super.init(frame: .zero)
        chrome.onPresentationChange = { [weak self] in self?.arrange(animated: true) }
        autoresizingMask = [.width, .height]
        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor
        backdrop.material = .underWindowBackground
        backdrop.blendingMode = .behindWindow
        backdrop.state = .active
        backgroundTint.wantsLayer = true
        addSubview(backdrop)
        addSubview(backgroundTint)
        setNativeFullscreen(false)
        sidebar.documentView = thumbnails
        sidebar.drawsBackground = false
        sidebar.hasVerticalScroller = true
        sidebar.autohidesScrollers = true
        sidebar.scrollerStyle = .overlay
        addSubview(canvas)
        globalScroll.documentView = globalDocument
        globalScroll.drawsBackground = false
        globalScroll.hasVerticalScroller = true
        globalScroll.hasHorizontalScroller = false
        globalScroll.autohidesScrollers = true
        globalScroll.scrollerStyle = .overlay
        globalScroll.contentView.postsBoundsChangedNotifications = true
        addSubview(globalScroll)
        addSubview(sidebar)
        tipsDropdown.isHidden = true
        settingsPlaceholder.isHidden = true
        addSubview(topChrome)
        addSubview(bottomChrome)
        addSubview(tipsDropdown)
        addSubview(settingsPlaceholder)
        NotificationCenter.default.addObserver(self, selector: #selector(globalClipDidScroll), name: NSView.boundsDidChangeNotification, object: globalScroll.contentView)
        registerForDraggedTypes([.maltosePanel])
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved, .leftMouseDown, .leftMouseUp, .scrollWheel, .keyDown]) { [weak self] event in
            guard let self, event.window === self.window else { return event }
            if event.type == .keyDown, event.keyCode == 53, self.chrome.tipsExpanded {
                self.chrome.tipsExpanded = false
                return nil
            }
            if event.type == .leftMouseDown {
                self.closeChromeIfClickedOutside(event)
                self.handlePanelMouseDown(event)
            }
            if event.type == .leftMouseUp { self.handlePanelMouseUp(event) }
            if event.type == .scrollWheel, self.routeGlobalScroll(event) { return nil }
            if event.type == .mouseMoved { self.pointerMoved() }
            return event
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let tracking { removeTrackingArea(tracking) }
        let area = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeInActiveApp, .inVisibleRect], owner: self)
        addTrackingArea(area)
        tracking = area
    }
    override func mouseExited(with event: NSEvent) { cancelHover(collapse: true) }
    override func mouseEntered(with event: NSEvent) { pointerMoved() }
    func windowDidMove(_ notification: Notification) { manager?.restoreWindowFrame(screenID) }
    func windowDidResize(_ notification: Notification) { manager?.restoreWindowFrame(screenID) }
    func windowDidResignKey(_ notification: Notification) { cancelHover(collapse: true) }
    func windowWillEnterFullScreen(_ notification: Notification) { fullScreenTransitioning = true }
    func windowDidEnterFullScreen(_ notification: Notification) { manager?.finishedFullscreen(screenID, succeeded: true) }
    func windowDidFailToEnterFullScreen(_ window: NSWindow) { manager?.finishedFullscreen(screenID, succeeded: false) }
    func windowWillExitFullScreen(_ notification: Notification) { fullScreenTransitioning = true }
    func windowDidExitFullScreen(_ notification: Notification) {
        fullScreenTransitioning = false
        setNativeFullscreen(false)
        manager?.restoreWindowFrame(screenID)
    }
    func setNativeFullscreen(_ value: Bool) {
        nativeFullscreen = value
        backdrop.isHidden = value
        backgroundTint.layer?.backgroundColor = NSColor.black.withAlphaComponent(value ? 1 : 0.60).cgColor
        window?.isOpaque = value
        window?.backgroundColor = value ? .black : .clear
    }

    func update(panelIDs: [String]) {
        state.reconcile(panelIDs)
        chrome.panelCount = state.panelIDs.count
        if arrangedIDs != state.panelIDs { arrange(animated: false) }
    }

    override func layout() {
        super.layout()
        // Reparenting/resizing panels can invalidate the root view during an animation.
        // Don't immediately lay out the final frames and cancel the in-flight transition.
        guard !isAnimatingModeTransition else { return }
        arrange(animated: false)
    }

    func arrange(animated: Bool) {
        guard let manager else { return }
        arrangedIDs = state.panelIDs
        let modeTransition = lastArrangedMode == .grid && state.mode == .focused
            || lastArrangedMode == .focused && state.mode == .grid
        let animations = animated && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        let zoomTransition = animations && modeTransition
        backdrop.frame = bounds
        backgroundTint.frame = bounds
        let globalMode = state.mode == .grid
        let topFrame = NSRect(x: 0, y: 0, width: bounds.width, height: chromeTopHeight)
        let bottomFrame = NSRect(x: 0, y: max(chromeTopHeight, bounds.height - chromeBottomHeight), width: bounds.width, height: chromeBottomHeight)
        let centerFrame = NSRect(x: 0, y: chromeTopHeight + chromeGap, width: bounds.width,
                                 height: max(1, bounds.height - chromeTopHeight - chromeBottomHeight - chromeGap * 2))
        workspaceFrame = centerFrame
        topChrome.isHidden = false
        bottomChrome.isHidden = false
        globalScroll.isHidden = !globalMode
        canvas.isHidden = globalMode
        topChrome.frame = topFrame
        bottomChrome.frame = bottomFrame
        globalScroll.frame = centerFrame
        canvas.frame = centerFrame
        emptyView?.isHidden = !state.panelIDs.isEmpty
        if state.panelIDs.isEmpty, emptyView == nil {
            let empty = NSHostingView(rootView: WorkspaceEmptyView())
            empty.autoresizingMask = [.width, .height]
            addSubview(empty)
            emptyView = empty
        }
        emptyView?.frame = centerFrame

        let sidebarWidth = WorkspaceGeometry.sidebarWidth(in: bounds)
        let showsSidebar = state.mode == .sidebar
        sidebar.isHidden = state.mode == .grid
        let sidebarFrame = NSRect(x: showsSidebar ? 0 : -sidebarWidth, y: centerFrame.minY, width: sidebarWidth, height: centerFrame.height)
        // Panels are children of `canvas`, whose own frame already starts at centerFrame.minY.
        // Keep their frames in canvas-local coordinates to avoid applying the top chrome offset twice.
        let primaryFrame = NSRect(x: WorkspaceGeometry.margin, y: 0,
                                  width: max(1, bounds.width - WorkspaceGeometry.margin * 2),
                                  height: max(1, centerFrame.height - WorkspaceGeometry.margin))
        let mainFrame = showsSidebar
            ? NSRect(x: sidebarWidth + 8, y: primaryFrame.minY, width: max(1, bounds.width - sidebarWidth - 24), height: primaryFrame.height)
            : primaryFrame
        let previewIDs = state.panelIDs.filter { $0 != state.primaryID }
        let thumbnailWidth = max(1, sidebarWidth - 24)
        let thumbnailHeight = thumbnailWidth * 0.64
        thumbnails.frame = NSRect(x: 0, y: 0, width: sidebarWidth,
                                  height: max(centerFrame.height, 24 + CGFloat(previewIDs.count) * (thumbnailHeight + 16)))
        let grid = makeGlobalGrid(viewport: globalScroll.contentView.bounds.size)
        globalDocument.frame = NSRect(origin: .zero, size: grid.documentSize)
        setGridScrollOffset(gridScrollOffset, grid: grid)

        if state.mode == .grid, lastArrangedMode != .grid, let primaryID = state.primaryID,
           let index = state.panelIDs.firstIndex(of: primaryID), index < grid.frames.count {
            ensurePanelVisible(grid.frames[index], grid: grid)
        }
        if zoomTransition { isAnimatingModeTransition = true }
        var zoomAnimation: (panel: GlassPanelView, start: NSRect, end: NSRect)?
        NSAnimationContext.runAnimationGroup { context in
            context.duration = animations ? 0.22 : 0
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            if animations { sidebar.animator().frame = sidebarFrame } else { sidebar.frame = sidebarFrame }
            for (index, id) in state.panelIDs.enumerated() {
                guard let panel = manager.panels[id] else { continue }
                let isPreview = !globalMode && id != state.primaryID
                let parent = globalMode ? globalDocument : (isPreview ? thumbnails : canvas)
                let reparent = panel.superview !== parent
                let transitionStartFrame = zoomTransition && reparent ? panel.convert(panel.bounds, to: self) : nil
                if reparent { panel.removeFromSuperview(); parent.addSubview(panel) }
                if let transitionStartFrame {
                    panel.frame = parent.convert(transitionStartFrame, from: self)
                }
                panel.configure(preview: isPreview, primary: !globalMode && !isPreview, global: globalMode,
                                selected: state.selectedIDs.contains(id),
                                workspaceMode: id == state.primaryID ? state.mode : (globalMode ? .grid : .sidebar))
                let frame: NSRect
                if globalMode { frame = grid.frames[index] }
                else if !isPreview { frame = mainFrame }
                else {
                    let position = previewIDs.firstIndex(of: id) ?? 0
                    frame = NSRect(x: 12, y: 16 + CGFloat(position) * (thumbnailHeight + 16), width: thumbnailWidth, height: thumbnailHeight)
                }
                if zoomTransition, id == state.primaryID, let transitionStartFrame {
                    let start = parent.convert(transitionStartFrame, from: self)
                    panel.frame = start
                    zoomAnimation = (panel, start, frame)
                } else if animations && !reparent { panel.animator().frame = frame }
                else { panel.frame = frame }
                panel.needsLayout = true
            }
        }
        if let zoomAnimation {
            animateZoomTransition(panel: zoomAnimation.panel, from: zoomAnimation.start, to: zoomAnimation.end)
        } else if zoomTransition {
            isAnimatingModeTransition = false
        }
        for parent in [canvas, thumbnails, globalDocument] {
            for case let panel as GlassPanelView in parent.subviews where !state.panelIDs.contains(panel.surfaceID) { panel.removeFromSuperview() }
        }
        let dropdownWidth = min(440, max(300, bounds.width - 40))
        tipsDropdown.frame = NSRect(x: max(20, bounds.width - dropdownWidth - 24), y: chromeTopHeight + 8, width: dropdownWidth, height: 178)
        settingsPlaceholder.frame = NSRect(x: max(20, (bounds.width - 360) / 2), y: max(centerFrame.minY, centerFrame.midY - 70), width: min(360, bounds.width - 40), height: 120)
        tipsDropdown.isHidden = !chrome.tipsExpanded
        settingsPlaceholder.isHidden = !chrome.settingsPresented
        if !tipsDropdown.isHidden { addSubview(tipsDropdown, positioned: .above, relativeTo: globalScroll) }
        if !settingsPlaceholder.isHidden { addSubview(settingsPlaceholder, positioned: .above, relativeTo: globalScroll) }
        lastArrangedMode = state.mode
    }

    private func animateZoomTransition(panel: GlassPanelView, from startFrame: NSRect, to endFrame: NSRect) {
        // A brief settle centers the selected panel. The longer second stage grows it around
        // that fixed center, so the transition reads as a zoom instead of a lateral slide.
        let centeredStart = NSRect(x: endFrame.midX - startFrame.width / 2,
                                   y: endFrame.midY - startFrame.height / 2,
                                   width: startFrame.width, height: startFrame.height)
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.14
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            context.completionHandler = { [weak self, weak panel] in
                guard let self, let panel else { return }
                NSAnimationContext.runAnimationGroup { zoomContext in
                    zoomContext.duration = 0.58
                    zoomContext.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                    zoomContext.completionHandler = { [weak self] in self?.isAnimatingModeTransition = false }
                    panel.animator().frame = endFrame
                }
            }
            panel.animator().frame = centeredStart
        }
    }

    private func makeGlobalGrid(viewport: CGSize) -> WorkspaceGeometry.GlobalGrid {
        if gridZoom < 0 {
            let windowSize = window?.contentView?.bounds.size ?? bounds.size
            let aspectRatio = windowSize.width / max(1, windowSize.height)
            let columns = WorkspaceGeometry.defaultGlobalColumns(forWindowAspectRatio: aspectRatio)
            gridZoom = WorkspaceGeometry.initialGlobalZoom(viewportWidth: viewport.width, initialColumns: columns)
        }
        let rowSpans = state.panelIDs.map { id in
            manager?.catalog.first(where: { $0.id == id })?.globalGridRowSpan ?? 1
        }
        var pinnedPositions: [Int: WorkspaceGridPosition] = [:]
        for (index, id) in state.panelIDs.enumerated() {
            if (manager?.catalog.first(where: { $0.id == id })?.globalGridRowSpan ?? 1) > 1 {
                pinnedPositions[index] = state.identityPosition
            }
        }
        return WorkspaceGeometry.globalGrid(count: state.panelIDs.count, viewport: viewport,
                                            zoom: gridZoom, rowSpans: rowSpans,
                                            pinnedPositions: pinnedPositions)
    }

    private func closeChromeIfClickedOutside(_ event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        // Keep each disclosure's own trigger clickable while it is open.
        if topChrome.frame.contains(point) || bottomChrome.frame.contains(point) { return }
        if chrome.tipsExpanded && !tipsDropdown.frame.contains(point) { chrome.tipsExpanded = false; arrange(animated: false) }
        if chrome.settingsPresented && !settingsPlaceholder.frame.contains(point) { chrome.settingsPresented = false; arrange(animated: false) }
    }

    private func panel(at event: NSEvent) -> GlassPanelView? {
        let point = convert(event.locationInWindow, from: nil)
        return manager?.panels.values.first {
            $0.window === window && !$0.isHidden && $0.convert($0.bounds, to: self).contains(point)
        }
    }

    private var pendingPanelSelection: (id: String, extending: Bool)?

    private func handlePanelMouseDown(_ event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        guard workspaceFrame.contains(point) else { return }
        if chrome.tipsExpanded && tipsDropdown.frame.contains(point) { return }
        if chrome.settingsPresented && settingsPlaceholder.frame.contains(point) { return }
        guard let panel = panel(at: event) else {
            pendingPanelSelection = nil
            guard !state.selectedIDs.isEmpty else { return }
            state.clearSelection()
            arrange(animated: false)
            return
        }
        let extending = event.modifierFlags.contains(.command)
        if panel.isSelected {
            // Defer collapsing/toggling the set until mouse-up so dragging a selected panel moves the set.
            pendingPanelSelection = (panel.surfaceID, extending)
        } else {
            pendingPanelSelection = nil
            manager?.highlightPanel(panel.surfaceID, extending: extending)
        }
    }

    private func handlePanelMouseUp(_ event: NSEvent) {
        defer { pendingPanelSelection = nil }
        guard let pending = pendingPanelSelection, panel(at: event)?.surfaceID == pending.id else { return }
        manager?.highlightPanel(pending.id, extending: pending.extending)
    }

    func cancelPendingPanelSelection() { pendingPanelSelection = nil }

    private func routeGlobalScroll(_ event: NSEvent) -> Bool {
        let point = convert(event.locationInWindow, from: nil)
        let delta = WorkspaceGeometry.normalizedWheelDelta(event.scrollingDeltaY, precise: event.hasPreciseScrollingDeltas)
        let activeGesture = !event.phase.isEmpty || !event.momentumPhase.isEmpty
        let isGestureEnd = event.phase.contains(.ended) || event.phase.contains(.cancelled)
            || event.momentumPhase.contains(.ended) || event.momentumPhase.contains(.cancelled)
        let useControl = wheelGesture.controlModifier(currentlyPressed: event.modifierFlags.contains(.control),
                                                      began: event.phase.contains(.began) || event.momentumPhase.contains(.began),
                                                      isActive: activeGesture, ended: isGestureEnd)
        let action = WorkspaceScrollAction.route(mode: state.mode,
                                                 isInsideGrid: globalScroll.frame.contains(point),
                                                 isCovered: tipsDropdown.frame.contains(point) || settingsPlaceholder.frame.contains(point),
                                                 isInsideScrollablePanel: panel(at: event).flatMap { panel in
                                                     manager?.catalog.first(where: { $0.id == panel.surfaceID })?.kind
                                                 }.map { [.conversationHistory, .document].contains($0) } ?? false,
                                                 controlPressed: useControl, deltaY: delta)
        switch action {
        case .passThrough: return false
        case .zoom(let delta):
            guard !state.panelIDs.isEmpty else { return true }
            zoomGrid(deltaY: delta, pointer: point)
        case .scroll(let delta): scrollGlobalGrid(by: delta)
        }
        return true
    }

    private func zoomGrid(deltaY: CGFloat, pointer: CGPoint) {
        let viewport = globalScroll.contentView.bounds.size
        let oldGrid = makeGlobalGrid(viewport: viewport)
        let oldOffset = gridScrollOffset
        let localY = pointer.y - globalScroll.frame.minY
        let docPoint = CGPoint(x: pointer.x, y: localY + oldOffset)
        let anchorIndex = oldGrid.frames.indices.min { a, b in
            distance(oldGrid.frames[a], to: docPoint) < distance(oldGrid.frames[b], to: docPoint)
        }
        let anchorID = anchorIndex.map { state.panelIDs[$0] }
        let oldFrame = anchorIndex.map { oldGrid.frames[$0] }
        let relativeY = oldFrame.map { min(1, max(0, (docPoint.y - $0.minY) / max(1, $0.height))) } ?? 0.5
        let screenY = oldFrame.map { $0.minY + relativeY * $0.height - oldOffset } ?? localY
        gridZoom = WorkspaceGeometry.zoomed(gridZoom, deltaY: deltaY)
        let newGrid = makeGlobalGrid(viewport: viewport)
        if let anchorID, let index = state.panelIDs.firstIndex(of: anchorID) {
            let frame = newGrid.frames[index]
            gridScrollOffset = WorkspaceGeometry.anchoredScrollOffset(frame: frame, relativeY: relativeY,
                                                                       viewportY: screenY, grid: newGrid,
                                                                       viewportHeight: viewport.height)
        }
        arrange(animated: false)
        setGridScrollOffset(gridScrollOffset, grid: newGrid)
    }

    private func distance(_ rect: CGRect, to point: CGPoint) -> CGFloat {
        hypot(max(max(rect.minX - point.x, 0), point.x - rect.maxX), max(max(rect.minY - point.y, 0), point.y - rect.maxY))
    }

    private func setGridScrollOffset(_ offset: CGFloat, grid: WorkspaceGeometry.GlobalGrid) {
        let bounded = WorkspaceGeometry.clampedScrollOffset(offset, grid: grid, viewportHeight: globalScroll.contentView.bounds.height)
        gridScrollOffset = bounded
        let clip = globalScroll.contentView
        guard abs(clip.bounds.origin.y - bounded) > 0.5 else { return }
        isAdjustingScroll = true
        clip.scroll(to: NSPoint(x: 0, y: bounded))
        globalScroll.reflectScrolledClipView(clip)
        isAdjustingScroll = false
    }

    private func ensurePanelVisible(_ frame: CGRect, grid: WorkspaceGeometry.GlobalGrid) {
        let top = gridScrollOffset
        let bottom = top + globalScroll.contentView.bounds.height
        let adjusted: CGFloat
        if frame.minY < top { adjusted = frame.minY }
        else if frame.maxY > bottom { adjusted = frame.maxY - globalScroll.contentView.bounds.height }
        else { return }
        setGridScrollOffset(adjusted, grid: grid)
    }

    @objc private func globalClipDidScroll() {
        guard state.mode == .grid, !isAdjustingScroll else { return }
        gridScrollOffset = globalScroll.contentView.bounds.origin.y
    }

    func scrollGlobalGrid(by delta: CGFloat) {
        let grid = makeGlobalGrid(viewport: globalScroll.contentView.bounds.size)
        setGridScrollOffset(gridScrollOffset + delta, grid: grid)
    }

    func setGlobalZoom(_ value: CGFloat) {
        gridZoom = min(1, max(0, value))
        arrange(animated: false)
    }

    func pointerMoved() {
        guard manager?.draggingID == nil else { return }
        let point = convert(window?.convertPoint(fromScreen: NSEvent.mouseLocation) ?? .zero, from: nil)
        let inside = bounds.contains(point) && NSApp.isActive
        if state.mode == .sidebar {
            if !inside || point.x > WorkspaceGeometry.sidebarWidth(in: bounds) { cancelHover(collapse: true) }
            return
        }
        let eligible = inside && state.mode == .focused && state.panelIDs.count > 1 && point.x <= WorkspaceGeometry.triggerWidth
        let oldAnchor = dwell.anchor
        dwell.update(point: point, eligible: eligible, now: ProcessInfo.processInfo.systemUptime)
        if !eligible { hoverTask?.cancel(); hoverTask = nil; return }
        guard oldAnchor != dwell.anchor || hoverTask == nil else { return }
        hoverTask?.cancel()
        hoverTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(1)) } catch { return }
            guard let self else { return }
            self.pointerMoved()
            guard !Task.isCancelled, self.dwell.isReady(at: ProcessInfo.processInfo.systemUptime),
                  self.state.mode == .focused, self.manager?.draggingID == nil, NSApp.isActive else { return }
            self.state.mode = .sidebar
            self.dwell.cancel()
            self.arrange(animated: true)
        }
    }

    func cancelHover(collapse: Bool) {
        hoverTask?.cancel()
        hoverTask = nil
        dwell.cancel()
        if collapse && state.mode == .sidebar && manager?.draggingID == nil {
            state.mode = .focused
            arrange(animated: true)
        }
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        guard manager?.acceptsDrag(sender) == true else { return [] }
        if manager?.isDraggingFrom(screenID) == true {
            guard state.mode == .grid, let target = globalGridPosition(at: sender.draggingLocation) else { return [] }
            manager?.previewDraggedPanels(to: screenID, position: target.position, columns: target.columns)
            return .move
        }
        layer?.borderWidth = 2
        layer?.borderColor = NSColor.systemBlue.cgColor
        return .move
    }
    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        guard manager?.acceptsDrag(sender) == true else { return [] }
        if manager?.isDraggingFrom(screenID) == true {
            guard state.mode == .grid, let target = globalGridPosition(at: sender.draggingLocation) else { return [] }
            manager?.previewDraggedPanels(to: screenID, position: target.position, columns: target.columns)
        }
        return .move
    }
    override func draggingExited(_ sender: NSDraggingInfo?) { layer?.borderWidth = 0 }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        layer?.borderWidth = 0
        guard manager?.acceptsDrag(sender) == true else { return false }
        if manager?.isDraggingFrom(screenID) == true {
            guard state.mode == .grid, let target = globalGridPosition(at: sender.draggingLocation) else { return false }
            manager?.previewDraggedPanels(to: screenID, position: target.position, columns: target.columns)
            return true
        }
        return manager?.moveDraggedPanels(to: screenID) == true
    }
    override func concludeDragOperation(_ sender: NSDraggingInfo?) { layer?.borderWidth = 0 }

    private func globalGridPosition(at windowPoint: NSPoint) -> (position: WorkspaceGridPosition, columns: Int)? {
        let grid = makeGlobalGrid(viewport: globalScroll.contentView.bounds.size)
        guard grid.panelSize.width > 0, grid.panelSize.height > 0 else { return nil }
        let rootPoint = convert(windowPoint, from: nil)
        guard globalScroll.frame.contains(rootPoint) else { return nil }
        let point = globalDocument.convert(rootPoint, from: self)
        let gridWidth = CGFloat(grid.columns) * grid.panelSize.width + CGFloat(grid.columns - 1) * WorkspaceGeometry.gap
        let gridStartX = (globalDocument.bounds.width - gridWidth) / 2
        let column = Int(round((point.x - gridStartX - grid.panelSize.width / 2)
                               / (grid.panelSize.width + WorkspaceGeometry.gap)))
        let row = Int(round((point.y - WorkspaceGeometry.margin - grid.panelSize.height / 2)
                            / (grid.panelSize.height + WorkspaceGeometry.gap)))
        return (WorkspaceGridPosition(row: max(0, row), column: min(grid.columns - 1, max(0, column))), grid.columns)
    }

    func dispose() {
        hoverTask?.cancel()
        if let eventMonitor { NSEvent.removeMonitor(eventMonitor) }
        eventMonitor = nil
        NotificationCenter.default.removeObserver(self)
    }
}

@MainActor private final class FlippedWorkspaceView: NSView {
    override var isFlipped: Bool { true }
}

private struct WorkspaceEmptyView: View {
    var body: some View {
        VStack(spacing: 18) {
            Text("MALTOSE").font(.system(size: 13, weight: .medium, design: .monospaced)).tracking(5).foregroundStyle(.cyan.opacity(0.7))
            Text("這個窗口還沒有面板").font(.system(size: 26, weight: .light))
            Text("將其他螢幕上的面板拖到這裡。").foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .foregroundStyle(.white)
        .preferredColorScheme(.dark)
    }
}
