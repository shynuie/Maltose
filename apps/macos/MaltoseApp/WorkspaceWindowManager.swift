import AppKit
import SwiftUI

@MainActor final class WorkspaceWindowManager {
    let catalog: [WorkspacePanel]
    let automaticallyFullscreen: Bool
    private(set) var transitioningScreenID: String?
    private(set) var fullscreenFailures: Set<String> = []
    private var fullscreenAttempted: Set<String> = []
    private var fullscreenTask: Task<Void, Never>?
    private var coreAnimationTestWindowController: AgentCoreTestWindowController?
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
        roots.values.first { $0.window?.isKeyWindow == true } ?? roots.values.first
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
        transitioningScreenID = nil
        coreAnimationTestWindowController?.close()
        coreAnimationTestWindowController = nil
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
