import AppKit
import XCTest
@testable import MaltoseApp

@MainActor final class WorkspaceSessionTests: XCTestCase {
    private func location() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("maltose-workspace-\(UUID())/session.json")
    }
    private func manager(_ catalog: [WorkspacePanel] = WorkspacePanel.initial) throws -> WorkspaceWindowManager {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native workspace") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let manager = WorkspaceWindowManager(catalog: catalog, automaticallyFullscreen: false)
        manager.restoresOpenPanelsOnly = true
        manager.synchronize()
        return manager
    }

    func testFirstLaunchContainsFixedPanelsAndJournalInLowerRight() throws {
        let url = location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        XCTAssertNil(try WorkspaceSessionStore(url: url).load())
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.deletingLastPathComponent().path))
        XCTAssertEqual(Set(WorkspacePanel.initial.map(\.id)), ["agent-identity", "chat", "agent-activity"])
        let manager = try manager(); defer { manager.stop() }
        manager.applyInitialLayout()
        XCTAssertEqual(Set(manager.panels.keys), ["agent-identity", "chat", "agent-activity"])
        for id in ["agent-identity", "chat"] { XCTAssertFalse(manager.closePanel(id)) }
        XCTAssertEqual(manager.catalog.first { $0.kind == .agentActivity }?.title, "工作日誌")
        let root = try XCTUnwrap(manager.roots[try XCTUnwrap(manager.assignments["chat"])])
        let grid = root.globalGridGeometry
        let chatIndex = try XCTUnwrap(root.state.panelIDs.firstIndex(of: "chat"))
        let logIndex = try XCTUnwrap(root.state.panelIDs.firstIndex(of: "agent-activity"))
        XCTAssertGreaterThanOrEqual(grid.frames[logIndex].minX, grid.frames[chatIndex].minX)
        XCTAssertEqual(root.state.panelPositions?["agent-activity"]?.column, grid.columns - 1)
        XCTAssertGreaterThan(grid.frames[logIndex].minY, grid.frames[chatIndex].minY)
    }

    func testTwoLaunchesRestoreLastOpenPanelsNotesLayoutAndStableIDs() async throws {
        let url = location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = WorkspaceSessionStore(url: url)
        let first = try manager()
        first.restoreSession(nil, store: store)
        first.showWorkPanel(.agentActivity); first.showWorkPanel(.taskProgress)
        let response = await first.agentInterface.handle(.init(command: .create_panel(kind: .notes, screenID: nil)))
        XCTAssertTrue(response.ok)
        let note = try XCTUnwrap(first.catalog.first { $0.kind == .notes })
        first.panels[note.id]?.sampleContentModel?.note = "保留的筆記"
        let logID = try XCTUnwrap(first.catalog.first { $0.kind == .agentActivity }?.id)
        XCTAssertTrue(first.closePanel(logID))
        first.selectPanel(note.id)
        let screen = try XCTUnwrap(first.assignments[note.id])
        first.stop()

        let saved = try XCTUnwrap(store.load())
        XCTAssertFalse(saved.panels.contains { $0.descriptor.id == logID })
        XCTAssertEqual(saved.panels.first { $0.descriptor.id == note.id }?.note, "保留的筆記")
        let next = try manager(saved.panels.map(\.descriptor)); defer { next.stop() }
        next.restoreSession(saved, store: store)
        XCTAssertEqual(next.catalog.map(\.id), saved.panels.map { $0.descriptor.id })
        XCTAssertEqual(next.panels[note.id]?.sampleContentModel?.note, "保留的筆記")
        XCTAssertEqual(next.roots[screen]?.state.primaryID, note.id)
        XCTAssertEqual(next.roots[screen]?.state.mode, .focused)
        XCTAssertEqual(next.roots[screen]?.savedGridZoom, saved.gridZooms?[screen])
        XCTAssertNil(next.panels[logID])
        XCTAssertNotNil(next.catalog.first { $0.kind == .taskProgress })
        let permissions = try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(permissions?.intValue, 0o600)
    }

    func testDisconnectedScreenFallsBackAndMissingFixedPanelsAreRepaired() throws {
        let url = location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = WorkspaceSessionStore(url: url)
        let note = WorkspacePanel(id: "saved-note", title: "筆記", kind: .notes)
        try store.save(.init(panels: [.init(descriptor: note, screenID: "disconnected", note: "原內容")]))
        let saved = try XCTUnwrap(store.load())
        XCTAssertEqual(saved.panels.count, 3)
        let next = try manager(saved.panels.map(\.descriptor)); defer { next.stop() }
        next.restoreSession(saved, store: store)
        XCTAssertNotEqual(next.assignments[note.id], "disconnected")
        XCTAssertNotNil(next.roots[try XCTUnwrap(next.assignments[note.id])])
        XCTAssertEqual(next.panels[note.id]?.sampleContentModel?.note, "原內容")
    }

    func testInvalidSessionAndSymbolicLinkDoNotReplaceExistingData() throws {
        let url = location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = WorkspaceSessionStore(url: url)
        try store.save(.init(panels: WorkspacePanel.initial.map { .init(descriptor: $0) }))
        let original = try Data(contentsOf: url)
        XCTAssertThrowsError(try store.save(.init(panels: [.init(descriptor: WorkspacePanel.initial[0]), .init(descriptor: WorkspacePanel.initial[0])])))
        XCTAssertEqual(try Data(contentsOf: url), original)
        let malformed = Data("invalid workspace".utf8)
        try malformed.write(to: url)
        XCTAssertThrowsError(try store.load())
        XCTAssertThrowsError(try store.save(.init(panels: [])))
        XCTAssertEqual(try Data(contentsOf: url), malformed)
        let link = url.deletingLastPathComponent().appendingPathComponent("link.json")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: url)
        XCTAssertThrowsError(try WorkspaceSessionStore(url: link).load())
        XCTAssertThrowsError(try WorkspaceSessionStore(url: link).save(.init(panels: [])))
        XCTAssertEqual(try Data(contentsOf: url), malformed)
        let alias = WorkspacePanel(id: "chat", title: "偽裝", kind: .notes)
        XCTAssertThrowsError(try WorkspaceSession(panels: [.init(descriptor: alias)]).validated())
    }

    func testHistoricalResultsOnlyRestoreWhenTheyBelongToSavedOpenSet() throws {
        let url = location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let journal = url.deletingLastPathComponent().appendingPathComponent("chat.jsonl")
        let first = try manager()
        try first.prepareLiveConversation(at: journal)
        let record = ResultDeliveryRecord(publicationID: "workspace-result", conversationID: "test", messageID: "result-message",
            title: "保存成果", markdown: "## 結果\n\n已完成。", createDocument: true)
        _ = try first.deliverResult(record)
        let id = try XCTUnwrap(record.panelID)
        let openCatalog = first.catalog
        first.stop()
        let fresh = try manager()
        try fresh.prepareLiveConversation(at: journal)
        XCTAssertNil(fresh.panels[id], "A first launch must not open all historical publications")
        fresh.stop()
        let restored = try manager(openCatalog); defer { restored.stop() }
        try restored.prepareLiveConversation(at: journal)
        XCTAssertEqual(restored.panels[id]?.markdownDocumentModel?.resultTitle, record.title)
        XCTAssertTrue(restored.closePanel(id))
        restored.stop()
        let closed = try manager(); defer { closed.stop() }
        try closed.prepareLiveConversation(at: journal)
        XCTAssertNil(closed.panels[id])
    }
}
