import XCTest
import AppKit
@testable import MaltoseApp

final class WorkspaceLayoutTests: XCTestCase {
    func testClosingOrMovingPrimaryKeepsRemainingPanelsUsable() {
        var state = WorkspaceLayoutState()
        state.reconcile(["a", "b", "c"])
        state.toggle("b")
        XCTAssertEqual(state.mode, .focused)
        state.reconcile(["a", "c"])
        XCTAssertEqual(state.primaryID, "a")
        XCTAssertEqual(state.mode, .focused)
        state.toggle("a")
        XCTAssertEqual(state.mode, .grid)
        state.reconcile([])
        XCTAssertNil(state.primaryID)
        XCTAssertEqual(state.mode, .grid)
    }

    func testRefreshDoesNotDiscardUserOrderOrSwitchTheSelectedPanel() {
        var state = WorkspaceLayoutState(panelIDs: ["c", "a"], primaryID: "c", mode: .sidebar)
        state.reconcile(["a", "b", "c"])
        XCTAssertEqual(state.panelIDs, ["c", "a", "b"])
        XCTAssertEqual(state.primaryID, "c")
        state.select("b")
        XCTAssertEqual(state.mode, .sidebar)
        state.toggle("b")
        XCTAssertEqual(state.mode, .grid)
        state.toggle("missing")
        XCTAssertEqual(state.mode, .grid)
    }

    func testPanelHighlightSupportsCommandMultiSelectAndPrunesMovedItems() {
        var state = WorkspaceLayoutState()
        state.reconcile(["a", "b", "c"])
        state.highlight("b", extending: false)
        XCTAssertEqual(state.selectedIDs, ["b"])
        state.highlight("a", extending: true)
        XCTAssertEqual(state.selectedIDs, ["a", "b"])
        state.highlight("a", extending: true)
        XCTAssertEqual(state.selectedIDs, ["b"])
        state.reconcile(["b", "c"])
        XCTAssertEqual(state.selectedIDs, ["b"])
    }

    func testClickingWorkspaceSpaceClearsPanelSelectionWithoutChangingPrimaryMode() {
        var state = WorkspaceLayoutState(panelIDs: ["a", "b", "c"], primaryID: "b",
                                         selectedIDs: ["a", "b"], mode: .focused)
        state.clearSelection()
        XCTAssertTrue(state.selectedIDs.isEmpty)
        XCTAssertEqual(state.primaryID, "b")
        XCTAssertEqual(state.mode, .focused)
    }

    func testMovingAlongTheEdgeDoesNotAccumulateDwellTime() {
        var dwell = SidebarDwell()
        dwell.update(point: CGPoint(x: 8, y: 100), eligible: true, now: 0)
        XCTAssertFalse(dwell.isReady(at: 0.99))
        dwell.update(point: CGPoint(x: 8, y: 101), eligible: true, now: 0.9)
        XCTAssertFalse(dwell.isReady(at: 1.1))
        XCTAssertTrue(dwell.isReady(at: 1.91))
        dwell.update(point: CGPoint(x: 100, y: 101), eligible: false, now: 2)
        XCTAssertFalse(dwell.isReady(at: 10))
        dwell.update(point: CGPoint(x: 8, y: 100), eligible: true, now: 10)
        dwell.cancel()
        XCTAssertFalse(dwell.isReady(at: 12))
    }

    func testGridFitsScreenShapesWithoutOverlapAndKeepsEqualSizes() {
        for size in [CGSize(width: 1440, height: 900), CGSize(width: 900, height: 1440), CGSize(width: 3440, height: 1440)] {
            let bounds = CGRect(origin: .zero, size: size)
            for count in 1...32 {
                let frames = WorkspaceGeometry.legacyGrid(count: count, in: bounds)
                XCTAssertEqual(frames.count, count)
                for (index, frame) in frames.enumerated() {
                    XCTAssertTrue(bounds.contains(frame), "\(size), count \(count)")
                    XCTAssertEqual(frame.size, frames[0].size)
                    for other in frames.dropFirst(index + 1) { XCTAssertFalse(frame.intersects(other)) }
                }
            }
        }
    }

    func testThumbnailFitsTheWholeContentWithoutChangingItsAspectRatio() {
        let bounds = CGRect(x: 12, y: 12, width: 240, height: 140)
        for size in [CGSize(width: 1600, height: 900), CGSize(width: 600, height: 1200)] {
            let rect = WorkspaceGeometry.fittedPreview(content: size, in: bounds)
            XCTAssertTrue(bounds.contains(rect))
            XCTAssertEqual(rect.width / rect.height, size.width / size.height, accuracy: 0.0001)
            XCTAssertEqual(rect.midX, bounds.midX)
            XCTAssertEqual(rect.midY, bounds.midY)
        }
    }

    func testGlobalGridUsesSixteenNinePanelsAndTenColumnBounds() {
        for viewport in [CGSize(width: 1440, height: 700), CGSize(width: 900, height: 1200), CGSize(width: 3400, height: 900)] {
            let small = WorkspaceGeometry.globalGrid(count: 31, viewport: viewport, zoom: 0)
            let large = WorkspaceGeometry.globalGrid(count: 31, viewport: viewport, zoom: 1)
            XCTAssertEqual(small.columns, 10)
            XCTAssertEqual(large.columns, 2)
            for grid in [small, large] {
                XCTAssertEqual(grid.frames.count, 31)
                XCTAssertEqual(grid.panelSize.width / grid.panelSize.height, 16.0 / 9.0, accuracy: 0.0001)
                XCTAssertEqual(grid.rows, Int(ceil(31.0 / Double(grid.columns))))
                for (index, frame) in grid.frames.enumerated() {
                    XCTAssertGreaterThan(frame.width, 0)
                    XCTAssertGreaterThan(frame.height, 0)
                    XCTAssertEqual(frame.size, grid.panelSize)
                    if index >= grid.columns {
                        XCTAssertEqual(frame.minX, grid.frames[index % grid.columns].minX, accuracy: 0.001)
                    }
                    for other in grid.frames.dropFirst(index + 1) { XCTAssertFalse(frame.intersects(other)) }
                }
                XCTAssertGreaterThanOrEqual(grid.documentSize.height, viewport.height)
                XCTAssertGreaterThanOrEqual(grid.documentSize.height, grid.frames.last!.maxY)
            }
        }
    }

    func testInitialGlobalColumnsFollowWindowAspectRatio() {
        let wideWindow = CGSize(width: 1920, height: 1080)
        let tallWindow = CGSize(width: 1080, height: 1920)
        let wideColumns = WorkspaceGeometry.defaultGlobalColumns(forWindowAspectRatio: wideWindow.width / wideWindow.height)
        let tallColumns = WorkspaceGeometry.defaultGlobalColumns(forWindowAspectRatio: tallWindow.width / tallWindow.height)
        XCTAssertEqual(wideColumns, 4)
        XCTAssertEqual(tallColumns, 2)

        let wideViewport = wideWindow
        let tallViewport = tallWindow
        let wideGrid = WorkspaceGeometry.globalGrid(count: 20, viewport: wideViewport,
                                                    zoom: WorkspaceGeometry.initialGlobalZoom(viewportWidth: wideViewport.width, initialColumns: wideColumns))
        let tallGrid = WorkspaceGeometry.globalGrid(count: 20, viewport: tallViewport,
                                                    zoom: WorkspaceGeometry.initialGlobalZoom(viewportWidth: tallViewport.width, initialColumns: tallColumns))
        XCTAssertEqual(wideGrid.columns, 4)
        XCTAssertEqual(tallGrid.columns, 2)
    }

    func testGlobalGridHandlesEmptyAndPartialRowsWithoutStretching() {
        let viewport = CGSize(width: 1600, height: 800)
        for count in [0, 1, 2, 9, 10, 11, 30] {
            let grid = WorkspaceGeometry.globalGrid(count: count, viewport: viewport, zoom: 0.42)
            XCTAssertEqual(grid.frames.count, count)
            XCTAssertTrue((2...10).contains(grid.columns))
            if count > 0 {
                XCTAssertTrue(grid.frames.allSatisfy { abs($0.width - grid.panelSize.width) < 0.001 && abs($0.height - grid.panelSize.height) < 0.001 })
                XCTAssertGreaterThanOrEqual(grid.documentSize.height, grid.frames.last!.maxY)
            } else {
                XCTAssertEqual(grid.rows, 0)
            }
        }
        let narrowGrid = WorkspaceGeometry.globalGrid(count: 10, viewport: CGSize(width: 100, height: 500), zoom: 0)
        let inset = WorkspaceGeometry.globalGlassInset(for: narrowGrid.panelSize)
        XCTAssertGreaterThan(narrowGrid.panelSize.width - 2 * inset, 0)
        XCTAssertGreaterThan(narrowGrid.panelSize.height - 2 * inset, 0)
    }

    func testGlobalZoomAndScrollClampAtBothEdges() {
        XCTAssertEqual(WorkspaceGeometry.zoomed(0.5, deltaY: 1000), 1)
        XCTAssertEqual(WorkspaceGeometry.zoomed(0.5, deltaY: -1000), 0)
        XCTAssertGreaterThan(WorkspaceGeometry.zoomed(0.5, deltaY: 1), 0.5)
        XCTAssertLessThan(WorkspaceGeometry.zoomed(0.5, deltaY: -1), 0.5)
        let grid = WorkspaceGeometry.globalGrid(count: 40, viewport: CGSize(width: 1400, height: 600), zoom: 0.5)
        XCTAssertEqual(WorkspaceGeometry.clampedScrollOffset(-50, grid: grid, viewportHeight: 600), 0)
        XCTAssertEqual(WorkspaceGeometry.clampedScrollOffset(100_000, grid: grid, viewportHeight: 600), grid.documentSize.height - 600)
    }

    func testZoomAnchorRestoresTheSamePanelPositionInTheViewport() {
        let grid = WorkspaceGeometry.globalGrid(count: 40, viewport: CGSize(width: 1400, height: 600), zoom: 0.5)
        let resized = CGRect(x: 300, y: 920, width: 480, height: 270)
        let offset = WorkspaceGeometry.anchoredScrollOffset(frame: resized, relativeY: 0.4, viewportY: 260, grid: grid, viewportHeight: 600)
        XCTAssertEqual(resized.minY + resized.height * 0.4 - offset, 260, accuracy: 0.001)
        XCTAssertEqual(WorkspaceGeometry.anchoredScrollOffset(frame: resized, relativeY: 0.4, viewportY: 2_000, grid: grid, viewportHeight: 600), 0)
    }

    func testGlobalScrollRoutingConsumesOnlyGridEvents() {
        XCTAssertEqual(WorkspaceScrollAction.route(mode: .grid, isInsideGrid: true, isCovered: false, controlPressed: false, deltaY: -4), .scroll(-4))
        XCTAssertEqual(WorkspaceScrollAction.route(mode: .grid, isInsideGrid: true, isCovered: false, controlPressed: true, deltaY: 4), .zoom(4))
        XCTAssertEqual(WorkspaceScrollAction.route(mode: .grid, isInsideGrid: false, isCovered: false, controlPressed: true, deltaY: 4), .passThrough)
        XCTAssertEqual(WorkspaceScrollAction.route(mode: .grid, isInsideGrid: true, isCovered: true, controlPressed: false, deltaY: 4), .passThrough)
        XCTAssertEqual(WorkspaceScrollAction.route(mode: .focused, isInsideGrid: true, isCovered: false, controlPressed: true, deltaY: 4), .passThrough)
    }

    func testWheelNormalizationAndGestureModifierRemainStableThroughMomentum() {
        XCTAssertEqual(WorkspaceGeometry.normalizedWheelDelta(3, precise: false), 36)
        XCTAssertEqual(WorkspaceGeometry.normalizedWheelDelta(120, precise: true), 80)
        XCTAssertEqual(WorkspaceGeometry.normalizedWheelDelta(-120, precise: true), -80)
        var gesture = WorkspaceWheelGesture()
        XCTAssertTrue(gesture.controlModifier(currentlyPressed: true, began: true, isActive: true, ended: false))
        XCTAssertTrue(gesture.controlModifier(currentlyPressed: false, began: false, isActive: true, ended: false))
        XCTAssertTrue(gesture.controlModifier(currentlyPressed: false, began: false, isActive: true, ended: true))
        XCTAssertFalse(gesture.controlModifier(currentlyPressed: false, began: false, isActive: false, ended: false))
    }
}

@MainActor final class WorkspaceNativeTests: XCTestCase {
    private func requireDesktop() throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Set MALTOSE_GUI_TESTS=1 in a macOS desktop session") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("No WindowServer screen is available") }
    }

    private func textEditor(in view: NSView) -> NSTextView? {
        if let text = view as? NSTextView { return text }
        return view.subviews.lazy.compactMap { self.textEditor(in: $0) }.first
    }

    func testPureUIContentSurvivesLayoutAndCrossScreenMoves() async throws {
        try requireDesktop()
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize()
        defer { manager.stop() }
        XCTAssertEqual(manager.windows.count, NSScreen.screens.count)
        for screen in NSScreen.screens {
            let window = try XCTUnwrap(manager.windows[WorkspaceWindowManager.screenID(screen)])
            XCTAssertEqual(window.frame, screen.frame)
            XCTAssertFalse(window.isMovable)
            XCTAssertFalse(window.isOpaque, "Windowed fallback should expose the translucent black backdrop")
            XCTAssertTrue(window.collectionBehavior.contains(.fullScreenPrimary) || window.collectionBehavior.contains(.fullScreenAuxiliary))
        }
        let panel = try XCTUnwrap(manager.panels["notes"])
        let originalContent = panel.contentView
        panel.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(200))
        let editor = try XCTUnwrap(textEditor(in: originalContent))
        editor.string = "A draft that must survive layout changes"
        editor.didChangeText()
        let screen = try XCTUnwrap(manager.assignments["notes"])
        let root = try XCTUnwrap(manager.roots[screen])
        let topFrame = root.topChromeFrame
        let bottomFrame = root.bottomChromeFrame
        manager.togglePanel("notes")
        root.arrange(animated: false)
        root.layoutSubtreeIfNeeded()
        XCTAssertEqual(root.state.mode, .focused)
        XCTAssertTrue(root.chromeIsVisible)
        XCTAssertEqual(root.topChromeFrame, topFrame)
        XCTAssertEqual(root.bottomChromeFrame, bottomFrame)
        let focusedPanelFrame = panel.convert(panel.bounds, to: root)
        XCTAssertEqual(focusedPanelFrame.minY, root.workspaceFrame.minY, accuracy: 0.001)
        XCTAssertLessThanOrEqual(focusedPanelFrame.maxY, root.workspaceFrame.maxY)
        XCTAssertEqual(panel.glassInset, 24)
        XCTAssertEqual(originalContent.superview?.frame.minX, 24)
        root.state.mode = .sidebar
        manager.selectPanel("chart")
        root.arrange(animated: false)
        root.layoutSubtreeIfNeeded()
        let chart = try XCTUnwrap(manager.panels["chart"])
        XCTAssertTrue(root.chromeIsVisible)
        XCTAssertEqual(root.topChromeFrame, topFrame)
        XCTAssertEqual(root.bottomChromeFrame, bottomFrame)
        XCTAssertGreaterThanOrEqual(root.sidebar.frame.minY, root.workspaceFrame.minY)
        XCTAssertLessThanOrEqual(root.sidebar.frame.maxY, root.workspaceFrame.maxY)
        let sidebarMainFrame = chart.convert(chart.bounds, to: root)
        XCTAssertEqual(sidebarMainFrame.minY, root.workspaceFrame.minY, accuracy: 0.001)
        XCTAssertLessThanOrEqual(sidebarMainFrame.maxY, root.workspaceFrame.maxY)
        XCTAssertTrue(panel.isPreview)
        XCTAssertTrue(panel.contentView === originalContent)
        let previewSize = try XCTUnwrap(originalContent.superview?.frame.size)
        XCTAssertEqual(previewSize.width / previewSize.height, panel.fullContentSize.width / panel.fullContentSize.height, accuracy: 0.001)
        manager.togglePanel("chart")
        root.arrange(animated: false)
        root.layoutSubtreeIfNeeded()
        let expectedGlobalInset = WorkspaceGeometry.globalGlassInset(for: panel.bounds.size)
        XCTAssertEqual(panel.glassInset, expectedGlobalInset, accuracy: 0.001)
        XCTAssertGreaterThan(originalContent.superview?.frame.width ?? 0, 0)
        XCTAssertTrue(panel.hitTest(NSPoint(x: panel.frame.minX + 4, y: panel.frame.minY + 4)) === panel)
        XCTAssertFalse(panel.hitTest(NSPoint(x: panel.frame.midX, y: panel.frame.midY)) === panel)
        manager.beginDrag("notes"); manager.endDrag()
        XCTAssertEqual(manager.assignments["notes"], screen)
        if let other = manager.roots.keys.first(where: { $0 != screen }) {
            manager.beginDrag("notes")
            XCTAssertTrue(manager.moveDraggedPanel(to: other))
            manager.endDrag()
            XCTAssertTrue(panel.window === manager.windows[other])

            root.state.highlight("chart", extending: false)
            root.state.highlight("table", extending: true)
            root.arrange(animated: false)
            manager.beginDrag("chart")
            XCTAssertEqual(Set(manager.draggingIDs), ["chart", "table"])
            XCTAssertTrue(manager.moveDraggedPanels(to: other))
            XCTAssertEqual(manager.assignments["chart"], other)
            XCTAssertEqual(manager.assignments["table"], other)
            XCTAssertTrue(manager.panels["chart"]?.isSelected == true)
            XCTAssertTrue(manager.panels["table"]?.isSelected == true)
            manager.endDrag()
        }
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertTrue(panel.contentView === originalContent)
        XCTAssertEqual(editor.string, "A draft that must survive layout changes")
    }

    func testAutomaticNativeFullscreenUsesSystemSpace() async throws {
        try requireDesktop()
        let manager = WorkspaceWindowManager()
        manager.synchronize()
        defer { manager.stop() }
        for _ in 0..<150 {
            if manager.transitioningScreenID == nil { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertNil(manager.transitioningScreenID)
        XCTAssertTrue(manager.fullscreenFailures.isEmpty)
        let eligibleScreens = NSScreen.screensHaveSeparateSpaces ? NSScreen.screens : Array(NSScreen.screens.prefix(1))
        for screen in eligibleScreens {
            let id = WorkspaceWindowManager.screenID(screen)
            let window = try XCTUnwrap(manager.windows[id])
            XCTAssertTrue(window.styleMask.contains(.fullScreen), "AppKit must confirm native fullscreen, not just a screen-sized frame")
            XCTAssertTrue(manager.roots[id]?.nativeFullscreen == true)
            XCTAssertTrue(window.isOpaque)
        }
    }

    func testChromeDraftAndDropdownStateRemainLocalAndIndependent() throws {
        try requireDesktop()
        let model = WorkspaceChromeModel()
        model.draft = "Keep this while scrolling"
        model.tipsExpanded = true
        model.panelCount = 30
        XCTAssertTrue(model.tipsExpanded)
        XCTAssertEqual(model.draft, "Keep this while scrolling")
        XCTAssertEqual(model.panelCount, 30)
        model.settingsPresented = true
        XCTAssertEqual(model.draft, "Keep this while scrolling")
    }

    func testThirtyPanelGridScrollsBetweenFixedChromeZones() throws {
        try requireDesktop()
        let manager = WorkspaceWindowManager(catalog: WorkspacePanel.previewSamples(count: 30), automaticallyFullscreen: false)
        manager.synchronize()
        defer { manager.stop() }
        let screenID = try XCTUnwrap(manager.assignments.values.first)
        let window = try XCTUnwrap(manager.windows[screenID])
        let root = try XCTUnwrap(manager.roots[screenID])
        window.displayIfNeeded()
        root.layoutSubtreeIfNeeded()
        root.setGlobalZoom(1)
        let grid = root.globalGridGeometry
        XCTAssertEqual(grid.frames.count, 30)
        XCTAssertEqual(grid.columns, 2)
        XCTAssertGreaterThan(grid.documentSize.height, root.globalViewportFrame.height)
        let topBefore = root.topChromeFrame
        let bottomBefore = root.bottomChromeFrame
        root.scrollGlobalGrid(by: 500)
        XCTAssertGreaterThan(root.globalScrollOffset, 0)
        XCTAssertEqual(root.topChromeFrame, topBefore)
        XCTAssertEqual(root.bottomChromeFrame, bottomBefore)
        root.scrollGlobalGrid(by: 1_000_000)
        XCTAssertEqual(root.globalScrollOffset, grid.documentSize.height - root.globalViewportFrame.height, accuracy: 1)
        XCTAssertEqual(manager.panels.count, 30)
    }
}
