import AppKit
import XCTest
@testable import MaltoseApp

final class WorkspaceAgentContractTests: XCTestCase {
    func testWireContractUsesNamedArgumentsAndPreservesRequestID() throws {
        let json = #"{"schemaVersion":1,"requestID":"call-7","command":{"chart_viewport":{"panelID":"chart","zoom":2,"pan":10}}}"#
        let request = try JSONDecoder().decode(WorkspaceAgentRequest.self, from: Data(json.utf8))
        XCTAssertEqual(request.requestID, "call-7")
        guard case let .chart_viewport(id, zoom, pan) = request.command else { return XCTFail("Wrong command") }
        XCTAssertEqual(id, "chart"); XCTAssertEqual(zoom, 2); XCTAssertEqual(pan, 10)
        XCTAssertEqual(request.command.name, "chart_viewport")
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
        XCTAssertEqual(object["requestID"] as? String, "call-7")
    }

    @MainActor func testPublishedToolSchemasCoverCapabilitiesAndTheirExecutableExamples() throws {
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        defer { manager.stop() }
        let definitions = WorkspaceAgentToolDefinitions.all
        XCTAssertEqual(definitions.count, Set(definitions.map(\.name)).count)
        XCTAssertEqual(Set(definitions.map(\.command)), Set(manager.agentInterface.capabilities().map(\.name)))
        let byName = Dictionary(uniqueKeysWithValues: definitions.map { ($0.command, $0) })
        for capability in manager.agentInterface.capabilities() {
            let definition = try XCTUnwrap(byName[capability.name])
            guard case let .object(properties) = definition.inputSchema["properties"],
                  case let .strings(required) = definition.inputSchema["required"] else { return XCTFail("Missing JSON Schema") }
            let encoded = try JSONEncoder().encode(capability.example.command)
            let command = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
            let arguments = try XCTUnwrap(command[capability.name] as? [String: Any])
            XCTAssertTrue(Set(arguments.keys).isSubset(of: Set(properties.keys)))
            XCTAssertTrue(Set(required).isSubset(of: Set(arguments.keys)))
        }
        if let path = ProcessInfo.processInfo.environment["MALTOSE_TOOL_SCHEMA_EXPORT"] {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            try encoder.encode(definitions).write(to: URL(fileURLWithPath: path), options: .atomic)
        }
    }

    @MainActor func testMalformedRequestsVersionsAndUnavailableWorkspaceReturnStructuredErrors() async throws {
        let manager = WorkspaceWindowManager(catalog: [], automaticallyFullscreen: false)
        defer { manager.stop() }
        let api = manager.agentInterface
        for json in ["not json", #"{"command":{"unknown":{}}}"#, #"{"command":{"image_select":{"panelID":"gallery","index":"wrong"}}}"#] {
            let response = try JSONDecoder().decode(WorkspaceAgentResponse.self, from: Data(await api.handleJSON(json).utf8))
            XCTAssertFalse(response.ok); XCTAssertEqual(response.error?.code, "invalid_request")
        }
        let version = await api.handle(.init(schemaVersion: 99, requestID: "v99", command: .list_capabilities))
        XCTAssertEqual(version.error?.code, "unsupported_version"); XCTAssertEqual(version.requestID, "v99")
        let view = await api.handle(.init(command: .get_user_view))
        XCTAssertFalse(view.ok); XCTAssertEqual(view.error?.code, "operation_failed")
    }
}

@MainActor final class WorkspaceAgentNativeTests: XCTestCase {
    private func manager() throws -> WorkspaceWindowManager {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Set MALTOSE_GUI_TESTS=1 in a macOS desktop session") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("No WindowServer screen is available") }
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize()
        return manager
    }

    @discardableResult private func send(_ command: WorkspaceAgentCommand, to manager: WorkspaceWindowManager,
                                        code: String? = nil, file: StaticString = #filePath, line: UInt = #line) async throws -> WorkspaceAgentResponse {
        // Round trip through JSON, as the simulator and future transport do.
        let request = WorkspaceAgentRequest(requestID: "test", command: command)
        let json = String(decoding: try JSONEncoder().encode(request), as: UTF8.self)
        let response = try JSONDecoder().decode(WorkspaceAgentResponse.self, from: Data(await manager.agentInterface.handleJSON(json).utf8))
        XCTAssertEqual(response.requestID, "test", file: file, line: line)
        XCTAssertEqual(response.ok, code == nil, response.error?.message ?? "", file: file, line: line)
        XCTAssertEqual(response.error?.code, code, file: file, line: line)
        return response
    }

    func testEveryAdvertisedOperationCanBeSimulatedThroughTheSharedModels() async throws {
        let manager = try manager()
        defer { manager.stop(); AgentIdentityAnimationModel.shared.setState(.idle) }
        let screenID = try XCTUnwrap(manager.assignments["notes"])
        let root = try XCTUnwrap(manager.roots[screenID])
        let originalNotes = try XCTUnwrap(manager.panels["notes"])
        let advertised = Set(manager.agentInterface.capabilities().map(\.name))
        var exercised: Set<String> = []
        @discardableResult func run(_ command: WorkspaceAgentCommand) async throws -> WorkspaceAgentResponse {
            exercised.insert(command.name)
            return try await send(command, to: manager)
        }
        _ = try await run(.get_user_view)
        let beforeRead = root.state.mode
        let read = try await run(.read_panel(panelID: "document"))
        XCTAssertEqual(root.state.mode, beforeRead)
        guard case let .object(details) = read.result["details"] else { return XCTFail("Missing explicit panel content") }
        XCTAssertNotNil(details["contentExcerpt"])
        let capabilities = try await run(.list_capabilities)
        XCTAssertFalse(capabilities.capabilities?.isEmpty ?? true)
        for capability in capabilities.capabilities ?? [] {
            let encoded = try JSONEncoder().encode(capability.example.command)
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
            XCTAssertEqual(Array(object.keys), [capability.name])
        }
        for kind in WorkspacePanel.Kind.allCases where kind.allowsMultipleInstances && kind != .agentCoreTest {
            let created = try await run(.create_panel(kind: kind, screenID: screenID))
            guard case let .string(id) = created.result["panelID"] else { return XCTFail("Missing new ID") }
            XCTAssertEqual(manager.catalog.first(where: { $0.id == id })?.kind, kind)
            _ = try await run(.close_panel(panelID: id, discardChanges: true))
            XCTAssertNil(manager.panels[id])
        }
        _ = try await run(.select_panel(panelID: "notes", extending: false))
        _ = try await run(.select_panel(panelID: "chart", extending: true))
        XCTAssertEqual(root.state.selectedIDs, ["notes", "chart"])
        XCTAssertEqual(root.state.mode, .grid)
        _ = try await run(.focus_panel(panelID: "notes"))
        XCTAssertEqual(root.state.mode, .focused)
        _ = try await run(.notes_set_text(panelID: "notes", text: "Written through Agent API"))
        XCTAssertTrue(manager.panels["notes"] === originalNotes)
        XCTAssertEqual(originalNotes.sampleContentModel?.note, "Written through Agent API")
        originalNotes.sampleContentModel?.note = "Edited through UI model"
        let view = try await run(.get_user_view)
        XCTAssertEqual(view.view?.workspaces.flatMap(\.panels).first(where: { $0.panelID == "notes" })?.details["text"], .string("Edited through UI model"))
        _ = try await run(.toggle_panel(panelID: "notes"))
        XCTAssertEqual(root.state.mode, .grid)
        _ = try await run(.set_mode(screenID: screenID, mode: .grid))
        _ = try await run(.grid_viewport(screenID: screenID, zoom: 0.3, scrollOffset: 0))
        _ = try await run(.move_panels(panelIDs: ["notes"], screenID: screenID, row: 0, column: 0))
        XCTAssertTrue(manager.panels["notes"] === originalNotes)
        _ = try await run(.focus_panel(panelID: "chat"))
        let history = try XCTUnwrap(manager.panels["chat"]?.conversationHistoryModel)
        let session = try XCTUnwrap(history.sessions.last)
        _ = try await run(.conversation_select_session(panelID: "chat", sessionID: session.id))
        XCTAssertEqual(history.currentSessionID, session.id)
        let chart = try XCTUnwrap(manager.panels["chart"]?.chartModel)
        let fixtureDirectory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-agent-files-\(UUID())")
        try FileManager.default.createDirectory(at: fixtureDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: fixtureDirectory) }
        let csvURL = fixtureDirectory.appendingPathComponent("test.csv")
        try "X,A,B\n1,2,3\n2,4,8".write(to: csvURL, atomically: true, encoding: .utf8)
        _ = try await run(.chart_open_csv(panelID: "chart", path: csvURL.path))
        XCTAssertEqual(chart.sourceName, "test.csv")
        _ = try await run(.chart_load_csv(panelID: "chart", csv: "X,A,B,note\n1,2,3,hello\n2,4,8,world", sourceName: "Simulation"))
        _ = try await run(.chart_set_series(panelID: "chart", names: ["B"]))
        _ = try await run(.chart_set_bands(panelID: "chart", bands: [.init(firstSeriesName: "A", secondSeriesName: "B", opacity: 0.25)]))
        _ = try await run(.chart_viewport(panelID: "chart", zoom: 3, pan: 1))
        XCTAssertEqual(chart.sourceName, "Simulation"); XCTAssertEqual(chart.visibleSeries, [1])
        XCTAssertEqual(chart.filledBands.values.first, 0.25); XCTAssertEqual(chart.xZoom, 3)
        _ = try await run(.image_add_url(panelID: "gallery", url: "https://example.invalid/test.png"))
        let gallery = try XCTUnwrap(manager.panels["gallery"]?.imageGalleryModel)
        XCTAssertEqual(gallery.images.count, 7)
        let imageURL = fixtureDirectory.appendingPathComponent("pixel.png")
        let png = try XCTUnwrap(Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO1sAAAAASUVORK5CYII="))
        try png.write(to: imageURL)
        _ = try await run(.image_add_file(panelID: "gallery", path: imageURL.path))
        XCTAssertEqual(gallery.images.count, 8)
        _ = try await run(.image_select(panelID: "gallery", index: 2))
        _ = try await run(.focus_panel(panelID: "gallery"))
        _ = try await run(.image_expand(panelID: "gallery", index: 2))
        _ = try await run(.image_viewport(panelID: "gallery", zoom: 2, panX: 20, panY: 10))
        XCTAssertEqual(gallery.zoomScale, 2); XCTAssertLessThanOrEqual(abs(gallery.panOffset.width), 20)
        _ = try await run(.image_viewport(panelID: "gallery", zoom: 2, panX: 1_000_000, panY: 1_000_000))
        XCTAssertLessThan(abs(gallery.panOffset.width), 1_000_000)
        XCTAssertLessThan(abs(gallery.panOffset.height), 1_000_000)
        _ = try await run(.image_collapse(panelID: "gallery"))
        XCTAssertNil(gallery.expandedIndex)
        _ = try await run(.browser_navigate(panelID: "browser-news", address: "https://example.invalid"))
        _ = try await run(.browser_control(panelID: "browser-news", action: .offlineTestPage))
        XCTAssertEqual(manager.panels["browser-news"]?.browserModel?.pageTitle, "Maltose 網頁測試")
        _ = try await run(.browser_control(panelID: "browser-news", action: .reload))
        _ = try await run(.browser_control(panelID: "browser-news", action: .stop))
        _ = try await run(.flowchart_new(panelID: "canvas", discardChanges: true))
        let canvas = try XCTUnwrap(manager.panels["canvas"]?.flowchartModel)
        let node1 = try await run(.flowchart_add_node(panelID: "canvas", type: .start, x: 0, y: 0))
        let node2 = try await run(.flowchart_add_node(panelID: "canvas", type: .process, x: 0, y: 120))
        guard case let .string(firstID) = node1.result["nodeID"], case let .string(secondID) = node2.result["nodeID"] else { return XCTFail("Missing node IDs") }
        _ = try await run(.flowchart_update_node(panelID: "canvas", nodeID: secondID, text: "Updated", x: 10, y: 100))
        _ = try await run(.flowchart_select_node(panelID: "canvas", nodeID: secondID, extending: false))
        _ = try await run(.flowchart_connect(panelID: "canvas", from: firstID, to: secondID, label: "next"))
        _ = try await run(.flowchart_viewport(panelID: "canvas", zoom: 1.4, panX: 10, panY: 20))
        _ = try await run(.focus_panel(panelID: "canvas"))
        let canvasView = try await run(.get_user_view)
        let canvasDetails = canvasView.view?.workspaces.flatMap(\.panels).first { $0.panelID == "canvas" }
        XCTAssertEqual(canvasDetails?.kind, WorkspacePanel.Kind.canvas.rawValue)
        guard case let .object(nodesByID) = canvasDetails?.details["nodesByID"],
              case let .object(node) = nodesByID[secondID] else { return XCTFail("Missing structured flowchart node") }
        XCTAssertEqual(node["text"], .string("Updated"))
        // Valid flowchart files may contain finite coordinates outside Int's range.
        canvas.setPosition(.init(x: 1e100, y: -1e100), for: firstID)
        _ = try await run(.get_user_view)
        canvas.setPosition(.init(x: 0, y: 0), for: firstID)
        XCTAssertEqual(canvas.nodes.last?.text, "Updated"); XCTAssertEqual(canvas.connections.count, 1)
        XCTAssertEqual(canvas.zoom, 1.4); XCTAssertEqual(canvas.panOffset.height, 20)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-agent-\(UUID()).maltoseflow.json")
        defer { try? FileManager.default.removeItem(at: url) }
        _ = try await run(.flowchart_save(panelID: "canvas", path: url.path))
        XCTAssertFalse(canvas.isDirty)
        _ = try await run(.flowchart_delete_selection(panelID: "canvas"))
        XCTAssertEqual(canvas.nodes.count, 1); XCTAssertTrue(canvas.connections.isEmpty)
        _ = try await run(.flowchart_open(panelID: "canvas", path: url.path, discardChanges: true))
        XCTAssertEqual(canvas.nodes.count, 2); XCTAssertFalse(canvas.isDirty)
        _ = try await run(.identity_set_state(panelID: "agent-identity", state: .thinking))
        XCTAssertEqual(AgentIdentityAnimationModel.shared.preset, .thinking)
        XCTAssertEqual(exercised, advertised, "Every advertised operation needs a JSON simulation")
    }

    func testInvalidCommandsDoNotPartiallyMutateWorkspaceOrContent() async throws {
        let manager = try manager(); defer { manager.stop() }
        let screenID = try XCTUnwrap(manager.assignments["notes"])
        let root = try XCTUnwrap(manager.roots[screenID])
        let beforeCatalog = manager.catalog.map(\.id)
        let beforeOrder = root.state.panelIDs
        let canvas = try XCTUnwrap(manager.panels["canvas"]?.flowchartModel)
        let beforeDocument = canvas.document
        let chart = try XCTUnwrap(manager.panels["chart"]?.chartModel)
        let series = chart.visibleSeries
        let invalid: [(WorkspaceAgentCommand, String)] = [
            (.create_panel(kind: .chart, screenID: "missing"), "not_found"),
            (.create_panel(kind: .agentIdentity, screenID: screenID), "panel_limit"),
            (.close_panel(panelID: "missing", discardChanges: false), "not_found"),
            (.close_panel(panelID: "canvas", discardChanges: false), "unsaved_changes"),
            (.notes_set_text(panelID: "chart", text: "wrong kind"), "unsupported_operation"),
            (.focus_panel(panelID: "agent-identity"), "unsupported_operation"),
            (.move_panels(panelIDs: ["notes", "missing"], screenID: screenID, row: nil, column: nil), "not_found"),
            (.move_panels(panelIDs: ["notes", "notes"], screenID: screenID, row: nil, column: nil), "invalid_argument"),
            (.move_panels(panelIDs: ["notes"], screenID: screenID, row: 1001, column: 0), "invalid_argument"),
            (.chart_set_series(panelID: "chart", names: ["unknown"]), "invalid_argument"),
            (.chart_set_bands(panelID: "chart", bands: [.init(firstSeriesName: "a", secondSeriesName: "b")]), "invalid_argument"),
            (.chart_load_csv(panelID: "chart", csv: "invalid", sourceName: "bad"), "operation_failed"),
            (.chart_open_csv(panelID: "chart", path: "relative.csv"), "invalid_argument"),
            (.image_add_file(panelID: "gallery", path: "relative.png"), "invalid_argument"),
            (.image_add_file(panelID: "gallery", path: "/dev/null"), "operation_failed"),
            (.image_select(panelID: "gallery", index: -1), "invalid_argument"),
            (.image_expand(panelID: "gallery", index: 0), "invalid_state"),
            (.image_viewport(panelID: "gallery", zoom: 2, panX: 0, panY: 0), "invalid_state"),
            (.image_add_url(panelID: "gallery", url: "file:///tmp/test"), "invalid_argument"),
            (.browser_navigate(panelID: "browser-news", address: "javascript:alert(1)"), "invalid_argument"),
            (.browser_control(panelID: "browser-news", action: .back), "invalid_state"),
            (.browser_control(panelID: "browser-news", action: .forward), "invalid_state"),
            (.conversation_select_session(panelID: "chat", sessionID: "missing"), "invalid_state"),
            (.flowchart_update_node(panelID: "canvas", nodeID: "missing", text: "bad", x: 0, y: 0), "not_found"),
            (.flowchart_new(panelID: "canvas", discardChanges: false), "unsaved_changes"),
            (.flowchart_open(panelID: "canvas", path: "/tmp/missing.maltoseflow.json", discardChanges: false), "unsaved_changes"),
            (.flowchart_save(panelID: "canvas", path: "relative.json"), "invalid_argument")
        ]
        for (command, code) in invalid { try await send(command, to: manager, code: code) }
        let nonfinite = await manager.agentInterface.handle(.init(command: .chart_viewport(panelID: "chart", zoom: .nan, pan: 0)))
        XCTAssertEqual(nonfinite.error?.code, "invalid_argument")
        XCTAssertEqual(manager.catalog.map(\.id), beforeCatalog); XCTAssertEqual(root.state.panelIDs, beforeOrder)
        XCTAssertEqual(canvas.document, beforeDocument); XCTAssertEqual(chart.visibleSeries, series)
        manager.beginDrag("notes")
        try await send(.notes_set_text(panelID: "notes", text: "busy"), to: manager, code: "busy")
        manager.endDrag()
    }

    func testNativeFileTransfersUseBytesAndProtectEditsMadeDuringSave() async throws {
        let manager = try manager()
        defer { manager.stop() }
        let api = manager.agentInterface
        let path = "/tmp/nonexistent-\(UUID().uuidString).maltoseflow.json"
        let command = WorkspaceAgentRequest(command: .flowchart_save(panelID: "canvas", path: path))
        let blocked = await api.handle(command, requiresFileTransfer: true)
        XCTAssertEqual(blocked.error?.code, "file_transfer_required")
        let canvas = try XCTUnwrap(manager.panels["canvas"]?.flowchartModel)
        canvas.newDocument()
        let node = canvas.addNode(.process, at: .init(x: 0, y: 0))
        let exported = await api.handle(command, fileTransfer: .init(mode: .export))
        XCTAssertTrue(exported.ok)
        func value(_ name: String) throws -> String {
            guard case let .string(value) = exported.result[name] else { throw NSError(domain: "test", code: 1) }
            return value
        }
        let identity = try value("documentID"), fingerprint = try value("fingerprint")
        canvas.updateText("new edit during save", for: node)
        let acknowledged = await api.handle(command, fileTransfer: .init(mode: .saved, documentID: identity, fingerprint: fingerprint, fileSHA256: "saved-hash"))
        XCTAssertTrue(acknowledged.ok)
        XCTAssertEqual(acknowledged.result["panelReflectsSavedDocument"], .boolean(true))
        XCTAssertTrue(canvas.isDirty, "New edits must not be marked clean by an older snapshot")
        XCTAssertFalse(FileManager.default.fileExists(atPath: path), "Native export/acknowledge must perform no filesystem write")

        canvas.newDocument()
        let stale = await api.handle(command, fileTransfer: .init(mode: .saved, documentID: identity, fingerprint: fingerprint, fileSHA256: "saved-hash"))
        XCTAssertEqual(stale.result["panelReflectsSavedDocument"], .boolean(false))
        XCTAssertNil(canvas.fileURL, "Old acknowledgements must not bind a new document to the old file")
        let loaded = await api.handle(.init(command: .flowchart_open(panelID: "canvas", path: path, discardChanges: false)),
                                      fileTransfer: .init(mode: .load, data: try value("data")))
        XCTAssertTrue(loaded.ok)
        XCTAssertEqual(canvas.nodes.count, 1)
        XCTAssertFalse(canvas.isDirty)
        let mismatch = await api.handle(.init(command: .notes_set_text(panelID: "notes", text: "unsafe")), fileTransfer: .init(mode: .export))
        XCTAssertEqual(mismatch.error?.code, "invalid_argument")
    }

    func testUserViewPrioritizesMainPanelAndSummarizesGridSidebarAndHiddenPanels() async throws {
        let manager = try manager(); defer { manager.stop() }
        let screenID = try XCTUnwrap(manager.assignments["notes"])
        let root = try XCTUnwrap(manager.roots[screenID])
        let grid = try await manager.getUserView()
        XCTAssertEqual(grid.schemaVersion, 2)
        XCTAssertTrue(grid.workspaces.flatMap(\.panels).allSatisfy { $0.detailLevel == "summary" })
        XCTAssertTrue(grid.workspaces.allSatisfy { !$0.isNativeFullscreen })
        try await send(.focus_panel(panelID: "document"), to: manager)
        root.arrange(animated: false); root.layoutSubtreeIfNeeded()
        let focused = try await manager.getUserView()
        let workspace = try XCTUnwrap(focused.workspaces.first { $0.screenID == screenID })
        XCTAssertEqual(workspace.visiblePanelIDs, ["document"])
        XCTAssertEqual(workspace.primaryPanelID, "document")
        XCTAssertEqual(workspace.layoutMode, .focused)
        let document = try XCTUnwrap(workspace.panels.first { $0.panelID == "document" })
        XCTAssertEqual(document.detailLevel, "content"); XCTAssertNotNil(document.details["contentExcerpt"])
        let notes = try XCTUnwrap(workspace.panels.first { $0.panelID == "notes" })
        XCTAssertEqual(notes.presentation, "hidden"); XCTAssertNil(notes.details["text"])
        XCTAssertFalse(notes.capabilities.isEmpty)
        try await send(.set_mode(screenID: screenID, mode: .sidebar), to: manager)
        root.arrange(animated: false); root.layoutSubtreeIfNeeded()
        let sidebar = try await manager.getUserView()
        let panels = try XCTUnwrap(sidebar.workspaces.first { $0.screenID == screenID }?.panels)
        XCTAssertEqual(panels.filter { $0.detailLevel == "content" }.map(\.panelID), ["document"])
        XCTAssertTrue(panels.filter { $0.panelID != "document" }.allSatisfy { $0.detailLevel == "summary" && $0.details["contentExcerpt"] == nil && $0.details["recentMessages"] == nil })
    }

    func testAgentMovesReuseNativePanelsAndPruneSourceSelection() async throws {
        let manager = try manager(); defer { manager.stop() }
        let sourceID = try XCTUnwrap(manager.assignments["notes"])
        guard let targetID = manager.roots.keys.first(where: { $0 != sourceID }) else {
            throw XCTSkip("Cross-screen Agent move requires a second WindowServer screen")
        }
        let target = try XCTUnwrap(manager.roots[targetID])
        let window = try XCTUnwrap(manager.windows[targetID])
        let panel = try XCTUnwrap(manager.panels["notes"])
        let content = panel.contentView
        try await send(.select_panel(panelID: "notes", extending: false), to: manager)
        try await send(.select_panel(panelID: "chart", extending: true), to: manager)
        try await send(.move_panels(panelIDs: ["notes", "chart"], screenID: targetID, row: nil, column: nil), to: manager)
        XCTAssertEqual(manager.assignments["notes"], targetID)
        XCTAssertEqual(manager.assignments["chart"], targetID)
        XCTAssertFalse(manager.roots[sourceID]?.state.selectedIDs.contains("notes") ?? true)
        XCTAssertEqual(target.state.selectedIDs, ["notes", "chart"])
        XCTAssertTrue(panel.contentView === content)
        XCTAssertTrue(panel.window === window)
        manager.beginDrag("agent-identity")
        let identityPosition = WorkspaceGridPosition(row: 2, column: 1)
        manager.previewDraggedPanels(to: sourceID, position: identityPosition,
                                     columns: try XCTUnwrap(manager.roots[sourceID]).globalGridGeometry.columns)
        XCTAssertTrue(manager.moveDraggedPanels(to: targetID))
        manager.endDrag(committed: true)
        XCTAssertEqual(target.state.identityPosition, identityPosition)
        XCTAssertEqual(target.state.mode, .grid)
    }

    func testFixedPanelsCannotBeClosedOrDuplicated() async throws {
        let manager = try manager(); defer { manager.stop() }
        let screenID = try XCTUnwrap(manager.assignments["notes"])
        for kind in [WorkspacePanel.Kind.conversationHistory, .agentIdentity] {
            let id = try XCTUnwrap(manager.catalog.first(where: { $0.kind == kind })?.id)
            try await send(.create_panel(kind: kind, screenID: screenID), to: manager, code: "panel_limit")
            let original = manager.panels[id]
            try await send(.close_panel(panelID: id, discardChanges: true), to: manager, code: "protected_panel")
            XCTAssertFalse(manager.closePanel(id))
            XCTAssertEqual(manager.catalog.filter { $0.kind == kind }.count, 1)
            XCTAssertNotNil(manager.panels[id])
            XCTAssertTrue(manager.panels[id] === original)
        }
        try await send(.create_panel(kind: .agentCoreTest, screenID: screenID), to: manager, code: "panel_limit")
    }

    func testRejectedChatCloseKeepsReceivingRuntimeMessages() async throws {
        let manager = try manager(); defer { manager.stop() }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-closed-chat-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        try manager.prepareLiveConversation(at: directory.appendingPathComponent("chat.jsonl"))
        let shared = try XCTUnwrap(manager.liveConversationModel)
        let screenID = try XCTUnwrap(manager.assignments["chat"])
        try await send(.close_panel(panelID: "chat", discardChanges: false), to: manager, code: "protected_panel")
        let data = try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "sessionID": "test", "sequence": 1,
            "event": ["type": "assistant_message", "timestamp": "now", "payload": ["content": "arrived while chat closed"]]])
        try manager.receiveRuntimeEvent(data)
        try await send(.create_panel(kind: .conversationHistory, screenID: screenID), to: manager, code: "panel_limit")
        XCTAssertTrue(manager.panels["chat"]?.conversationHistoryModel === shared)
        XCTAssertEqual(shared.currentSession?.messages.last?.text, "arrived while chat closed")
    }

    func testSimulatorExecutesTheSameJSONInterfaceAndKeepsCaptureAvailable() async throws {
        let manager = try manager(); defer { manager.stop() }
        let model = UserViewTestModel(capture: { try await manager.getUserView() }, agentInterface: manager.agentInterface)
        let example = try XCTUnwrap(model.capabilities.first { $0.name == "notes_set_text" })
        model.useExample(example)
        await model.executeAndWait()
        let response = try JSONDecoder().decode(WorkspaceAgentResponse.self, from: Data(model.response.utf8))
        XCTAssertTrue(response.ok); XCTAssertFalse(model.isSending)
        XCTAssertEqual(manager.panels["notes"]?.sampleContentModel?.note, "Agent 測試筆記")
        await model.sendAndWait()
        XCTAssertTrue(model.response.contains("workspaces"))
    }
}
