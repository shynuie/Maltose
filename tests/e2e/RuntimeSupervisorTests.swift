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

    private func config(arguments: [String]? = nil, timeout: Duration = .seconds(5),
                        shutdownGrace: Duration = .seconds(3)) throws -> RuntimeLaunchConfiguration {
        let python = project.appendingPathComponent("runtime/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Run scripts/setup-runtime.sh before runtime integration tests") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-supervisor-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return .init(executable: python,
                     arguments: arguments ?? ["-m", "maltose.desktop", "--native-text-only", "--brain", "echo", "--config", directory.appendingPathComponent("none.toml").path],
                     directory: directory, moduleDirectory: project.appendingPathComponent("runtime"),
                     logURL: directory.appendingPathComponent("runtime.log"), startupTimeout: timeout,
                     shutdownGrace: shutdownGrace)
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
        XCTAssertTrue(supervisor.foregroundResultsEnabled, "Foreground delivery is enabled only when the native workflow is also enabled")
        XCTAssertEqual(supervisor.foregroundResultVersion, 0)
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
        XCTAssertEqual(supervisor.state, .stopped,
                       (try? String(contentsOf: configuration.logURL, encoding: .utf8)) ?? "No runtime diagnostics")
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
            let configuration = try config(arguments: ["-c", program], timeout: .milliseconds(100), shutdownGrace: .milliseconds(100))
            let supervisor = RuntimeSupervisor()
            try supervisor.start(configuration: configuration)
            try await waitFor { supervisor.processID == nil }
            if case .failed = supervisor.state {} else { XCTFail("Missing or invalid handshake must fail") }
            try FileManager.default.removeItem(at: configuration.directory)
        }
    }

    func testStopDuringInitializationFinishesBeforeReportingStopped() async throws {
        let configuration = try config(arguments: ["-c", "import time; time.sleep(30)"], shutdownGrace: .milliseconds(100))
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
    func testStructuredResultCrossesManagedRuntimeAndCreatesNewDocumentWithoutOverwriting() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native output panels") }
        _ = NSApplication.shared
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize()
        defer { manager.stop() }
        let original = try XCTUnwrap(manager.panels["document"]?.markdownDocumentModel)
        let originalCount = original.blocks.count
        let program = """
        import json,sys
        from maltose.agent import cli
        from maltose.desktop import main
        class ScriptedModel:
            def stream(self, messages, tools):
                import time
                assert 'spoken_summary' in messages[0]['content']
                result=dict(schemaVersion=1,title='整合結果',full_text='完整結果內容。\\n\\n'*40+'https://example.com/source',
                    spoken_summary='已完成整理，仍有一項待確認。',kind='partial',visual='document',limitations=['資料時間仍需確認'])
                raw=json.dumps(result,ensure_ascii=False)
                boundary=raw.index('完整結果內容。')+len('完整結果內容。')
                yield {'choices':[{'delta':{'content':raw[:boundary]}}]}
                time.sleep(.15)
                yield {'choices':[{'delta':{'content':raw[boundary:]}}]}
        cli.OpenAICompatibleTaskModel=lambda **kwargs:ScriptedModel()
        sys.argv=['maltose','--config','not-present.toml','--native-text-only','--brain','taskbrain',
            '--speaker-recognition','none','--taskbrain-embedding','none','--taskbrain-search','none']
        main()
        """
        let configuration = try config(arguments: ["-c", program])
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        try manager.prepareLiveConversation(at: configuration.directory.appendingPathComponent("conversation.jsonl"))
        let supervisor = RuntimeSupervisor()
        var applied = false
        var events: [[String: Any]] = []
        supervisor.onEvent = { data in
            let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            if let event = message?["event"] as? [String: Any] {
                events.append(event)
                if event["type"] as? String == "result_presentation",
                   let payload = event["payload"] as? [String: Any], payload["status"] as? String == "panel_applied" { applied = true }
            }
            try? manager.receiveRuntimeEvent(data)
        }
        supervisor.onPanelCommand = { request, transfer in
            await manager.agentInterface.handle(request, fileTransfer: transfer, requiresFileTransfer: true)
        }
        try supervisor.start(configuration: configuration)
        try await waitFor { supervisor.state == .ready }
        XCTAssertTrue(supervisor.submitText("請整理完整結果"))
        try await waitFor {
            applied && events.contains { event in
                event["type"] as? String == "speech_summary" && (event["payload"] as? [String: Any])?["content"] as? String == ""
            }
        }
        let resultPanels = manager.panels.values.compactMap(\.markdownDocumentModel).filter { $0.resultTitle == "整合結果" }
        XCTAssertEqual(resultPanels.count, 1)
        XCTAssertEqual(original.blocks.count, originalCount)
        XCTAssertTrue(manager.panels["document"]?.markdownDocumentModel === original)
        let text = try XCTUnwrap(manager.liveConversationModel?.currentSession?.messages.last?.text)
        XCTAssertTrue(text.contains("https://example.com/source"))
        XCTAssertTrue(text.contains("資料時間仍需確認"))
        XCTAssertFalse(text.hasPrefix("{\"schemaVersion"))
        XCTAssertEqual(manager.liveConversationModel?.currentSession?.messages.count, 2,
                       "Durable final delivery must upsert the streamed answer, not add a duplicate")
        let streamedText = events.compactMap { event -> String? in
            guard event["type"] as? String == "assistant_delta" else { return nil }
            return (event["payload"] as? [String: Any])?["content"] as? String
        }
        XCTAssertGreaterThan(streamedText.count, 1, "Full text must stream before the final envelope completes")
        XCTAssertEqual(streamedText.first, "完整結果內容。")
        XCTAssertFalse(streamedText.contains { $0.contains("schemaVersion") || $0.contains("spoken_summary") })
        XCTAssertTrue(events.contains { event in
            event["type"] as? String == "speech_summary" && (event["payload"] as? [String: Any])?["content"] as? String == ""
        }, "Native keyboard input must not trigger unsolicited speech")
        supervisor.stop()
        try await waitFor { supervisor.processID == nil }
    }

    func testBackgroundWorkerCompletesWhileIdleAndLostDeliveryAckRecoversAcrossAppAndRuntimeRestartWithoutRerun() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native result panels") }
        _ = NSApplication.shared
        let program = """
        import os,time
        from pathlib import Path
        from types import SimpleNamespace
        from maltose.agent import AgentConfig,VoiceAgent,TaskBrain,TaskManager,TaskStore,MemoryStore,FunctionTaskWorker
        from maltose.runtime import EventHub
        from maltose.ui.native import NativeRuntimeBridge
        if os.getpgrp()!=os.getpid(): os.setsid()
        base=Path.cwd(); hub=EventHub(); bridge=NativeRuntimeBridge(hub)
        bridge.start(); bridge.wait_for_initialize()
        store=TaskStore(base/'tasks.sqlite3'); manager=TaskManager(store,control_gate=bridge.control)
        def work(data):
            count=base/'worker-count'
            count.write_text(str(int(count.read_text())+1 if count.exists() else 1))
            deadline=time.monotonic()+10
            while not (base/'release-worker').exists():
                if time.monotonic()>deadline: raise RuntimeError('Fixture worker did not receive release')
                time.sleep(.01)
            return '背景完整原文。\\n'*100+'https://example.com/background'
        manager.register_worker('fixture',FunctionTaskWorker(work))
        if not store.list('verified-fixture'):
            manager.create_plan([dict(title='背景整合結果',worker_type='fixture')],user_id='verified-fixture')
        brain=TaskBrain(SimpleNamespace(),memory=MemoryStore(base/'memory.json'),task_manager=manager,control_gate=bridge.control)
        # Fixture identity is supplied by this test, never by a native text packet.
        brain._active_user_id='verified-fixture'; brain._active_speaker_status='identified'; brain._active_input_source='native'
        agent=VoiceAgent(config=AgentConfig(),brain=brain,event_hub=hub,voice_enabled=False,control_gate=bridge.control)
        original_ack=brain.acknowledge_task_result
        def acknowledged(identity):
            result=original_ack(identity)
            (base/'delivery-ack').touch()
            return result
        brain.acknowledge_task_result=acknowledged
        bridge.attach(agent,brain); agent.result_handler=bridge.present_result; agent.durable_result_delivery=True
        try: agent.run()
        finally: manager.shutdown(); bridge.close(); store.close()
        """
        let configuration = try config(arguments: ["-u", "-c", program])
        defer { try? FileManager.default.removeItem(at: configuration.directory) }
        let journal = configuration.directory.appendingPathComponent("conversation.jsonl")
        let first = WorkspaceWindowManager(automaticallyFullscreen: false)
        first.synchronize(); try first.prepareLiveConversation(at: journal)
        let supervisor = RuntimeSupervisor()
        supervisor.conversationID = "background-conversation"
        var uncertain = false
        supervisor.onEvent = { data in
            try? first.receiveRuntimeEvent(data)
            if let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let event = value["event"] as? [String: Any], event["type"] as? String == "result_presentation",
               let payload = event["payload"] as? [String: Any], payload["chatStored"] as? Bool == false { uncertain = true }
        }
        supervisor.onPanelCommand = { request, transfer in
            let actual = await first.agentInterface.handle(request, fileTransfer: transfer, requiresFileTransfer: true)
            guard actual.ok else { return actual }
            // The native journal/panel succeeded, but the runtime never receives that ACK.
            return WorkspaceAgentResponse(requestID: request.requestID, ok: false, error: .init(code: "fixture_lost_ack", message: "Simulated lost delivery acknowledgement"))
        }
        try supervisor.start(configuration: configuration)
        try await waitFor { supervisor.state == .ready }
        try Data().write(to: configuration.directory.appendingPathComponent("release-worker"))
        try await waitFor { uncertain }
        XCTAssertFalse(FileManager.default.fileExists(atPath: configuration.directory.appendingPathComponent("delivery-ack").path))
        let record = try XCTUnwrap(first.liveConversationModel?.resultDeliveries.values.first)
        XCTAssertTrue(record.markdown.contains("https://example.com/background"))
        XCTAssertTrue(record.markdown.contains("整體需求的完成條件仍需核對"))
        XCTAssertEqual(first.liveConversationModel?.currentSession?.messages.count, 1)
        supervisor.stop(); try await waitFor { supervisor.processID == nil }
        XCTAssertEqual(supervisor.state, .stopped)
        first.stop()

        let restored = WorkspaceWindowManager(automaticallyFullscreen: false)
        restored.synchronize(); try restored.prepareLiveConversation(at: journal)
        defer { restored.stop() }
        XCTAssertNotNil(restored.panels[record.panelID!])
        let restarted = RuntimeSupervisor()
        restarted.conversationID = "background-conversation"
        restarted.onEvent = { try? restored.receiveRuntimeEvent($0) }
        restarted.onPanelCommand = { request, transfer in await restored.agentInterface.handle(request, fileTransfer: transfer, requiresFileTransfer: true) }
        try restarted.start(configuration: configuration)
        try await waitFor { restarted.state == .ready && FileManager.default.fileExists(atPath: configuration.directory.appendingPathComponent("delivery-ack").path) }
        // Flush the runtime event stream through a real request, not a fixed sleep.
        _ = try await restarted.call("snapshot")
        restarted.stop(); try await waitFor { restarted.processID == nil }
        XCTAssertEqual(try String(contentsOf: configuration.directory.appendingPathComponent("worker-count"), encoding: .utf8), "1")
        XCTAssertEqual(restored.liveConversationModel?.sessions.flatMap(\.messages).count, 1)
        XCTAssertEqual(restored.liveConversationModel?.resultDeliveries.count, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: configuration.directory.appendingPathComponent("memory.json").path))
    }

}
