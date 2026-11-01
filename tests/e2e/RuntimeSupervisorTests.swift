import AppKit
import XCTest
@testable import MaltoseApp

@MainActor final class RuntimeSupervisorTests: XCTestCase {
    func testNativeDataLocationHasExplicitNewNamePriorityAndRejectsRelativePaths() throws {
        XCTAssertEqual(try RuntimeLaunchConfiguration.supportDirectory(environment: ["MALTOSE_DATA_DIR": "/tmp/current", "MYAGENT_DATA_DIR": "/tmp/legacy"]).path, "/tmp/current")
        XCTAssertEqual(try RuntimeLaunchConfiguration.supportDirectory(environment: ["MYAGENT_DATA_DIR": "/tmp/legacy"]).path, "/tmp/legacy")
        XCTAssertTrue(try RuntimeLaunchConfiguration.supportDirectory(environment: [:]).path.hasSuffix("Library/Application Support/Maltose"))
        XCTAssertThrowsError(try RuntimeLaunchConfiguration.supportDirectory(environment: ["MALTOSE_DATA_DIR": "relative"]))
    }
    private var project: URL { URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent() }

    private func config(arguments: [String]? = nil, timeout: Duration = .seconds(5)) throws -> RuntimeLaunchConfiguration {
        let python = project.appendingPathComponent("runtime/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Run scripts/setup-runtime.sh before runtime integration tests") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-supervisor-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return .init(executable: python,
                     arguments: arguments ?? ["-m", "maltose.desktop", "--native-text-only", "--brain", "echo", "--config", directory.appendingPathComponent("none.toml").path],
                     directory: directory, moduleDirectory: project.appendingPathComponent("runtime"),
                     logURL: directory.appendingPathComponent("runtime.log"), startupTimeout: timeout,
                     shutdownGrace: .milliseconds(100))
    }

    private func waitFor(_ condition: () -> Bool, seconds: Double = 8, file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(seconds)
        while !condition(), Date() < deadline { try await Task.sleep(for: .milliseconds(20)) }
        XCTAssertTrue(condition(), "Runtime condition timed out", file: file, line: line)
    }

    func testRealManagedAgentHandshakeInputAndGracefulShutdown() async throws {
        let configuration = try config()
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        let supervisor = RuntimeSupervisor()
        var events: [[String: Any]] = []
        supervisor.onEvent = { data in if let event = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] { events.append(event) } }
        try supervisor.start(configuration: configuration)
        try await waitFor { supervisor.state == .ready }
        XCTAssertNotNil(supervisor.sessionID)
        let pid = supervisor.processID
        try supervisor.start(configuration: configuration)
        XCTAssertEqual(supervisor.processID, pid, "Starting twice must not create another writer")
        var accepted = false
        XCTAssertTrue(supervisor.submitText("native supervisor test") { ok, _ in accepted = ok })
        try await waitFor {
            events.contains { message in
                guard let event = message["event"] as? [String: Any], let payload = event["payload"] as? [String: Any] else { return false }
                return event["type"] as? String == "assistant_message" && (payload["content"] as? String)?.contains("native supervisor test") == true
            }
        }
        XCTAssertTrue(accepted)
        var stopped = false
        supervisor.stop { stopped = true }
        try await waitFor { stopped && supervisor.processID == nil }
        XCTAssertEqual(supervisor.state, .stopped)
        XCTAssertFalse(supervisor.submitText("offline"))
    }

    func testExistingComposerAndChatRoundTripThroughManagedAgentAndPersist() async throws {
        let configuration = try config()
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        let journal = configuration.directory.appendingPathComponent("conversation.jsonl")
        let model = ConversationHistoryModel()
        try model.enableLiveStorage(at: journal)
        let supervisor = RuntimeSupervisor()
        var eventErrors: [String] = []
        supervisor.onEvent = { data in
            do { try model.applyRuntimeEvent(data) }
            catch { eventErrors.append(error.localizedDescription) }
        }
        let composer = WorkspaceChromeModel()
        composer.onSubmitText = { supervisor.submitText($0) }
        try supervisor.start(configuration: configuration)
        try await waitFor { supervisor.state == .ready }
        composer.draft = "message from existing composer"
        composer.submitDraft()
        XCTAssertEqual(composer.draft, "")
        try await waitFor { model.currentSession?.messages.count == 2 }
        XCTAssertEqual(model.currentSession?.messages.first?.speaker, .user)
        XCTAssertEqual(model.currentSession?.messages.first?.text, "message from existing composer")
        XCTAssertTrue(model.currentSession?.messages.last?.text.contains("message from existing composer") == true)
        XCTAssertTrue(eventErrors.isEmpty)
        supervisor.stop()
        try await waitFor { supervisor.processID == nil }
        model.closeLiveStorage()
        let restored = ConversationHistoryModel()
        try restored.enableLiveStorage(at: journal)
        XCTAssertEqual(restored.currentSession?.messages.map(\.text), model.currentSession?.messages.map(\.text))
        restored.closeLiveStorage()
    }

    func testStartupFailureDoesNotReportReadyAndAllowsRetry() async throws {
        let bad = try config(arguments: ["-c", "raise SystemExit(23)"])
        defer { try? FileManager.default.removeItem(at: bad.directory) }
        let supervisor = RuntimeSupervisor()
        try supervisor.start(configuration: bad)
        try await waitFor { supervisor.processID == nil }
        if case .failed = supervisor.state {} else { XCTFail("Early process exit must fail initialization") }
        let good = try config()
        defer { try? FileManager.default.removeItem(at: good.directory) }
        try supervisor.start(configuration: good)
        try await waitFor { supervisor.state == .ready }
        supervisor.stop()
        try await waitFor { supervisor.processID == nil }
    }

    func testPanelFileTransferCrossesActualChildPipeWithoutAppFileIO() async throws {
        let program = """
        from maltose.runtime import EventHub
        from maltose.ui.native import NativeRuntimeBridge
        import base64
        hub = EventHub()
        bridge = NativeRuntimeBridge(hub)
        bridge.start()
        bridge.wait_for_initialize()
        hub.publish('state_changed', {'state': 'standby'})
        original_send = bridge._send
        panel_request = None
        def duplicate_send(message):
            global panel_request
            original_send(message)
            if message.get('method') == 'panel.call':
                panel_request = message
                original_send(message)
        bridge._send = duplicate_send
        response = bridge.call_panel({'chart_open_csv': {'panelID': 'chart', 'path': '/no-such-directory/native.csv'}},
            file_transfer={'mode': 'load', 'data': base64.b64encode(b'x,tea\\n0,10\\n1,20').decode()})
        original_send(panel_request)
        hub.publish('assistant_message', {'content': 'loaded' if response['ok'] else 'failed'})
        bridge._shutdown_requested.wait(20)
        bridge.close()
        """
        let configuration = try config(arguments: ["-c", program])
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        let supervisor = RuntimeSupervisor()
        var transferred = 0, resultReceived = false
        supervisor.onPanelCommand = { request, transfer in
            guard case let .chart_open_csv(id, path) = request.command else { return .init(ok: false) }
            XCTAssertEqual(id, "chart"); XCTAssertEqual(path, "/no-such-directory/native.csv")
            XCTAssertEqual(transfer?.mode, .load)
            let data = try? XCTUnwrap(Data(base64Encoded: transfer?.data ?? ""))
            XCTAssertEqual(data.map { String(decoding: $0, as: UTF8.self) }, "x,tea\n0,10\n1,20")
            transferred += 1
            return .init(requestID: request.requestID, ok: true)
        }
        supervisor.onEvent = { data in
            let message = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let event = message?["event"] as? [String: Any]
            if (event?["payload"] as? [String: Any])?["content"] as? String == "loaded" { resultReceived = true }
        }
        try supervisor.start(configuration: configuration)
        try await waitFor { supervisor.state == .ready && transferred > 0 && resultReceived }
        XCTAssertEqual(transferred, 1, "Duplicate pending or completed requests must not execute the panel operation again")
        supervisor.stop()
        try await waitFor { supervisor.processID == nil }
    }

    func testExistingTaskBrainCallsNativePanelToolsThroughActualManagedRuntime() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires macOS desktop session") }
        _ = NSApplication.shared
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize()
        defer { manager.stop() }
        let program = """
        import json,sys
        from maltose.agent import cli
        from maltose.desktop import main
        class ScriptedModel:
            def __init__(self): self.round = 0
            def stream(self, messages, tools):
                self.round += 1
                if self.round <= 2:
                    assert any(t['function']['name'] == 'maltose_notes_set_text' for t in tools)
                    if self.round == 2:
                        rejected = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
                        assert not rejected['ok'] and rejected['error']['code'] == 'invalid_argument'
                    yield {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'native-test-tool', 'type': 'function',
                        'function': {'name': 'maltose_notes_set_text', 'arguments': json.dumps({'panelID': 3 if self.round == 1 else 'notes', 'text': 'edited by existing TaskBrain'})}}]}}]}
                else:
                    result = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
                    assert result['ok'], result
                    yield {'choices': [{'delta': {'content': 'native panel operation completed'}}]}
        cli.OpenAICompatibleTaskModel = lambda **kwargs: ScriptedModel()
        sys.argv = ['maltose', '--config', 'not-present.toml', '--native-text-only', '--brain', 'taskbrain',
            '--speaker-recognition', 'none', '--taskbrain-embedding', 'none', '--taskbrain-search', 'none']
        main()
        """
        let configuration = try config(arguments: ["-c", program])
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        try manager.prepareLiveConversation(at: configuration.directory.appendingPathComponent("conversation.jsonl"))
        let supervisor = RuntimeSupervisor()
        var eventErrors: [String] = []
        supervisor.onEvent = { data in
            do { try manager.receiveRuntimeEvent(data) } catch { eventErrors.append(error.localizedDescription) }
        }
        supervisor.onPanelCommand = { request, transfer in
            await manager.agentInterface.handle(request, fileTransfer: transfer, requiresFileTransfer: true)
        }
        try supervisor.start(configuration: configuration)
        try await waitFor { supervisor.state == .ready }
        XCTAssertTrue(supervisor.submitText("Update the notes panel"))
        try await waitFor {
            manager.liveConversationModel?.currentSession?.messages.last?.text == "native panel operation completed"
        }
        XCTAssertEqual(manager.panels["notes"]?.sampleContentModel?.note, "edited by existing TaskBrain")
        XCTAssertTrue(eventErrors.isEmpty)
        supervisor.stop()
        try await waitFor { supervisor.processID == nil }
    }

    func testTimeoutAndInvalidProtocolReapOnlyTheOwnedChild() async throws {
        for program in ["import time; time.sleep(30)", "import time; print('not protocol',flush=True); time.sleep(30)"] {
            let configuration = try config(arguments: ["-c", program], timeout: .milliseconds(100))
            let supervisor = RuntimeSupervisor()
            try supervisor.start(configuration: configuration)
            try await waitFor { supervisor.processID == nil }
            if case .failed = supervisor.state {} else { XCTFail("Missing or invalid handshake must fail") }
            try FileManager.default.removeItem(at: configuration.directory)
        }
    }

    func testStopDuringInitializationFinishesBeforeReportingStopped() async throws {
        let configuration = try config(arguments: ["-c", "import time; time.sleep(30)"])
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        let supervisor = RuntimeSupervisor()
        try supervisor.start(configuration: configuration)
        XCTAssertEqual(supervisor.state, .starting)
        var completed = false
        supervisor.stop { completed = true }
        XCTAssertFalse(completed)
        XCTAssertNotNil(supervisor.processID)
        try await waitFor { completed && supervisor.processID == nil }
    }

    func testMissingExecutableDoesNotLeaveAPartialRuntime() throws {
        var configuration = try config()
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        configuration.executable = configuration.directory.appendingPathComponent("missing-python")
        let supervisor = RuntimeSupervisor()
        XCTAssertThrowsError(try supervisor.start(configuration: configuration))
        XCTAssertNil(supervisor.processID)
        XCTAssertEqual(supervisor.state, .stopped)
    }
}
