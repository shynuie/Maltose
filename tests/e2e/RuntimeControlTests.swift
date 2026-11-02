import XCTest
@testable import MaltoseApp

@MainActor final class RuntimeControlTests: XCTestCase {
    private var project: URL { URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent() }
    private func configuration(program: String? = nil) throws -> RuntimeLaunchConfiguration {
        let python = project.appendingPathComponent("runtime/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Requires locked runtime test environment") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-control-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let arguments = program.map { ["-c", $0] } ?? ["-m", "maltose.desktop", "--native-text-only", "--brain", "echo", "--config", directory.appendingPathComponent("none.toml").path]
        return .init(executable: python, arguments: arguments, directory: directory, moduleDirectory: project.appendingPathComponent("runtime"),
                     logURL: directory.appendingPathComponent("runtime.log"), startupTimeout: .seconds(5), shutdownGrace: .milliseconds(100))
    }
    private func waitFor(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(6)
        while !condition(), Date() < deadline { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(condition(), file: file, line: line)
    }

    func testLeadingMentionAndStickyRecipientNeverFollowPanelSelectionOrQuotedText() {
        XCTAssertEqual(AgentComposerMessage(" @CoDeX：新增需求 "), .init(explicitRecipient: .codex, body: "新增需求"))
        XCTAssertEqual(AgentComposerMessage("@maltose next").recipient(current: .codex), .maltose)
        XCTAssertEqual(AgentComposerMessage("下一項需求").recipient(current: .codex), .codex)
        XCTAssertEqual(AgentComposerMessage("@codex").body, "")
        for text in ["正文 @codex", "`@codex`", "> @codex", "\"@codex\"", "```\n@codex\n```", "    @codex code", "\t@codex code", "@codex-tools", "@codexfoo"] {
            XCTAssertNil(AgentComposerMessage(text).explicitRecipient, text)
            XCTAssertEqual(AgentComposerMessage(text).body, text)
        }
    }

    func testActualNativeChildStartsPausedRoutesInputAndResumesOnlyWithCurrentLeaseAndIntent() async throws {
        let config = try configuration(); defer { try? FileManager.default.removeItem(at: config.directory) }
        let supervisor = RuntimeSupervisor()
        supervisor.initialAutonomyOwner = "restored-task"; supervisor.inputRoutingEnabled = true
        var events: [[String: Any]] = []
        supervisor.onEvent = { data in
            if let envelope = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let event = envelope["event"] as? [String: Any] { events.append(event) }
        }
        try supervisor.start(configuration: config)
        defer { supervisor.stop() }
        try await waitFor { supervisor.state == .ready }
        let paused = try await supervisor.readAutonomy()
        XCTAssertEqual(paused.state, .paused); XCTAssertEqual(paused.inFlight, 0)
        XCTAssertTrue(supervisor.submitText("routed fixture"))
        try await waitFor { events.contains { $0["type"] as? String == "input_routed" } }
        XCTAssertFalse(events.contains { $0["type"] as? String == "assistant_message" })
        let routed = try XCTUnwrap(events.first { $0["type"] as? String == "input_routed" }?["payload"] as? [String: Any])
        XCTAssertEqual(routed["source"] as? String, "native")
        XCTAssertEqual((routed["speaker"] as? [String: Any])?["status"] as? String, "unknown")
        let lease = try XCTUnwrap(paused.leaseID)
        do {
            _ = try await supervisor.call("resume_autonomy", params: ["ownerID": .string("restored-task"), "leaseID": .string("old-lease"), "intentConfirmed": .boolean(true)])
            XCTFail("A stale lease must be rejected")
        } catch RuntimeRequestError.rejected {}
        do {
            _ = try await supervisor.call("resume_autonomy", params: ["ownerID": .string("restored-task"), "leaseID": .string(lease)])
            XCTFail("Missing renewed intent must be rejected")
        } catch RuntimeRequestError.rejected {}
        _ = try await supervisor.call("resume_autonomy", params: ["ownerID": .string("restored-task"), "leaseID": .string(lease), "intentConfirmed": .boolean(true)])
        try await waitFor { supervisor.autonomy?.state == .active }
        XCTAssertTrue(supervisor.submitText("fresh intent fixture"))
        try await waitFor { events.contains { $0["type"] as? String == "assistant_message" } }
        let assistant = try XCTUnwrap(events.first { $0["type"] as? String == "assistant_message" }?["payload"] as? [String: Any])
        XCTAssertTrue((assistant["content"] as? String)?.contains("fresh intent fixture") == true)
        supervisor.stop(); try await waitFor { supervisor.processID == nil }
    }

    func testActualPanelReplyCanFinishWhilePauseIsDraining() async throws {
        let program = """
        from maltose.runtime import EventHub
        from maltose.ui.native import NativeRuntimeBridge
        from types import SimpleNamespace
        import threading
        hub=EventHub(); bridge=NativeRuntimeBridge(hub)
        bridge.attach(SimpleNamespace(state=SimpleNamespace(value='standby'),request_shutdown=lambda:None),None)
        bridge.start(); bridge.wait_for_initialize()
        hub.publish('state_changed',{'state':'standby'})
        def tool():
            with bridge.control.activity('tool'):
                bridge.call_panel({'get_user_view':{}})
        worker=threading.Thread(target=tool); worker.start()
        bridge._shutdown_requested.wait(20); worker.join(2); bridge.close()
        """
        let config = try configuration(program: program); defer { try? FileManager.default.removeItem(at: config.directory) }
        let supervisor = RuntimeSupervisor()
        var panelRequested = false, releasePanel = false
        supervisor.onPanelCommand = { request, _ in
            panelRequested = true
            while !releasePanel { try? await Task.sleep(for: .milliseconds(10)) }
            return .init(requestID: request.requestID, ok: true)
        }
        defer { releasePanel = true; supervisor.stop() }
        try supervisor.start(configuration: config)
        try await waitFor { supervisor.state == .ready && panelRequested }
        let response = try await supervisor.call("pause_autonomy", params: ["ownerID": .string("codex-task")])
        XCTAssertEqual(response["state"], .string("pausing"))
        let draining = try await supervisor.readAutonomy()
        XCTAssertEqual(draining.state, .pausing); XCTAssertEqual(draining.inFlight, 1)
        releasePanel = true
        try await waitFor { supervisor.autonomy?.state == .paused }
        XCTAssertEqual(supervisor.autonomy?.inFlight, 0)
        supervisor.stop(); try await waitFor { supervisor.processID == nil }
    }

    func testControlSnapshotRejectsImpossiblePausedState() throws {
        let invalid = RuntimeAutonomySnapshot(state: .paused, ownerID: "task", leaseID: "lease", epoch: 1, version: 1, activities: ["tool": 1], inFlight: 1)
        XCTAssertThrowsError(try invalid.validate())
        let active = RuntimeAutonomySnapshot(state: .active, ownerID: "task", leaseID: nil, epoch: 1, version: 1, activities: [:], inFlight: 0)
        XCTAssertThrowsError(try active.validate())
    }

    func testTimedOutControlMutationIsNotReplayedAfterRestart() async throws {
        let program = """
        import time
        from pathlib import Path
        from types import SimpleNamespace
        from maltose.runtime import EventHub
        from maltose.ui.native import NativeRuntimeBridge
        hub=EventHub(); bridge=NativeRuntimeBridge(hub)
        original=bridge._dispatch
        def dispatch(method,params):
            if method=='slow-fixture-mutation':
                path=Path('calls'); path.write_text(str(int(path.read_text())+1 if path.exists() else 1))
                time.sleep(2)
                return {'accepted':True}
            return original(method,params)
        bridge._dispatch=dispatch
        bridge.attach(SimpleNamespace(state=SimpleNamespace(value='standby'),request_shutdown=lambda:None),None)
        bridge.start(); bridge.wait_for_initialize()
        hub.publish('state_changed',{'state':'standby'})
        bridge._shutdown_requested.wait(20); bridge.close()
        """
        let config = try configuration(program: program); defer { try? FileManager.default.removeItem(at: config.directory) }
        let supervisor = RuntimeSupervisor(); defer { supervisor.stop() }
        try supervisor.start(configuration: config); try await waitFor { supervisor.state == .ready }
        do {
            _ = try await supervisor.call("slow-fixture-mutation", timeout: .milliseconds(100))
            XCTFail("The result must remain uncertain")
        } catch RuntimeRequestError.outcomeUnknown(let method) { XCTAssertEqual(method, "slow-fixture-mutation") }
        supervisor.stop(); try await waitFor { supervisor.processID == nil }
        try supervisor.start(configuration: config); try await waitFor { supervisor.state == .ready }
        let state = try await supervisor.readAutonomy(); XCTAssertEqual(state.state, .active)
        XCTAssertEqual(try String(contentsOf: config.directory.appendingPathComponent("calls"), encoding: .utf8), "1")
        supervisor.stop(); try await waitFor { supervisor.processID == nil }
    }
}

private extension AgentComposerMessage {
    init(explicitRecipient: AgentRecipient?, body: String) { self.init(body); self.explicitRecipient = explicitRecipient; self.body = body }
}
