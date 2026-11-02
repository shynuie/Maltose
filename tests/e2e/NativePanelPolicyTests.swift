import AppKit
import XCTest
@testable import MaltoseApp

@MainActor final class NativePanelPolicyTests: XCTestCase {
    private func fixture() throws -> WorkspaceWindowManager {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native panel models") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false); manager.synchronize()
        manager.agentInterface.panelPolicy.validateSource = { source in
            .init(inputID: source.inputID, text: "聚焦 Google 新聞面板", canReadExisting: false)
        }
        manager.agentInterface.panelPolicy.assessIntent = { _, _ in
            XCTFail("UI operations must not call the authorization model")
            return .init(decision: "deny", command: "", targetIDs: [], evidence: "", reason: "")
        }
        return manager
    }
    private var source: NativePanelSource { .init(runtimeSessionID: "runtime", executor: .maltose, inputID: "human", scopeID: "invocation") }
    private func call(_ command: WorkspaceAgentCommand, in manager: WorkspaceWindowManager,
                      source: NativePanelSource? = nil, transfer: NativePanelFileTransfer? = nil) async -> WorkspaceAgentResponse {
        await manager.agentInterface.handleAgent(.init(command: command, source: source ?? self.source), fileTransfer: transfer)
    }

    func testFixedPanelClosesAreRejectedWithoutAuthorizationPrompts() async throws {
        let manager = try fixture(); defer { manager.stop() }
        for id in ["agent-identity", "chat"] {
            let original = manager.panels[id]
            let response = await call(.close_panel(panelID: id, discardChanges: true), in: manager)
            XCTAssertFalse(response.ok)
            XCTAssertEqual(response.error?.code, "protected_panel")
            XCTAssertTrue(manager.panels[id] === original)
        }
    }

    func testUnidentifiedAgentCanReadFocusSwitchSelectMoveAndCloseWithoutInputSnapshotOrConsent() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let screen = try XCTUnwrap(manager.roots.keys.first)
        let created = await call(.create_panel(kind: .notes, screenID: screen), in: manager)
        let id = try XCTUnwrap(created.result["panelID"]?.stringValue)
        for command: WorkspaceAgentCommand in [.list_capabilities, .read_panel(panelID: id), .focus_panel(panelID: id),
            .select_panel(panelID: id, extending: false), .toggle_panel(panelID: id),
            .set_mode(screenID: screen, mode: .grid), .close_panel(panelID: id, discardChanges: false)] {
            let response = await call(command, in: manager)
            XCTAssertTrue(response.ok, "\(command.name): \(String(describing: response.error))")
        }
        XCTAssertNil(manager.panels[id])
    }

    func testInMemoryEditsAndDifferentInvocationsDoNotRequireAuthorizationOrSpeakerIdentity() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let first = await call(.notes_set_text(panelID: "notes", text: "自主更新"), in: manager)
        XCTAssertTrue(first.ok)
        manager.panels["notes"]?.sampleContentModel?.note = "人員稍後編輯"
        var next = source; next.scopeID = "next-invocation"
        let second = await call(.notes_set_text(panelID: "notes", text: "後續工作可更新面板"), in: manager, source: next)
        XCTAssertTrue(second.ok)
        XCTAssertEqual(manager.panels["notes"]?.sampleContentModel?.note, "後續工作可更新面板")
        let chart = await call(.chart_load_csv(panelID: "chart", csv: "X,A\n1,2\n2,3", sourceName: "本機測試資料"), in: manager)
        XCTAssertTrue(chart.ok)
        XCTAssertEqual(manager.panels["chart"]?.chartModel?.data.rows.map(\.values), [[2], [3]])
    }

    func testEveryAdvertisedUIOperationPassesAuthorizationAndKeepsArgumentValidation() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let denied = ["identity_required", "update_not_authorized", "ambiguous_target", "source_snapshot_expired", "update_scope_expired", "discard_not_authorized"]
        var checked = Set<String>()
        // Isolate each capability so closing/moving one panel cannot affect the next.
        for capability in manager.agentInterface.capabilities() {
            let command = capability.example.command
            if case let .mutation(category, _, _) = command.panelEffect, category != "save" {
                let isolated = try fixture(); defer { isolated.stop() }
                let response = await call(command, in: isolated)
                XCTAssertFalse(denied.contains(response.error?.code ?? ""), command.name)
                checked.insert(command.name)
            }
        }
        let expected = Set(WorkspaceAgentToolDefinitions.all.map(\.command)).subtracting(["create_panel", "get_user_view", "list_capabilities", "read_panel", "flowchart_save"])
        XCTAssertEqual(checked, expected)
    }

    func testFileReadsStillRequireRuntimeTransferAndSavingDoesNotInheritUIPermission() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let load = await call(.chart_open_csv(panelID: "chart", path: "/tmp/should-not-open.csv"), in: manager)
        XCTAssertEqual(load.error?.code, "file_transfer_required")
        let transferred = await call(.chart_open_csv(panelID: "chart", path: "/tmp/runtime-validated.csv"), in: manager,
            transfer: .init(mode: .load, data: Data("X,A\n1,2\n2,3".utf8).base64EncodedString()))
        XCTAssertTrue(transferred.ok)
        let export = await call(.flowchart_save(panelID: "canvas", path: "/tmp/should-not-write.maltoseflow.json"), in: manager, transfer: .init(mode: .export))
        XCTAssertFalse(export.ok); XCTAssertNil(export.result["data"])
        XCTAssertEqual(export.error?.code, "identity_required")
    }

    func testActualSessionSourceAndPrivatePublicationBoundaryStillApply() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let missing = await manager.agentInterface.handleAgent(.init(command: .focus_panel(panelID: "notes")))
        XCTAssertEqual(missing.error?.code, "source_required")
        let forged = await call(.publish_document(publicationID: "forged", title: "內容", markdown: "內容"), in: manager)
        XCTAssertEqual(forged.error?.code, "access_denied")
        manager.agentInterface.panelPolicy.validateSource = { _ in throw CodexTaskStoreError.conflict }
        let stopped = await call(.notes_set_text(panelID: "notes", text: "過期執行不可繼續"), in: manager)
        XCTAssertFalse(stopped.ok)
    }
}
