import XCTest
@testable import MaltoseApp

@MainActor final class CodexAdapterTests: XCTestCase {
    private var project: URL { URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent() }
    private func fixture(mode: String = "complete") throws -> CodexLaunchConfiguration {
        let python = project.appendingPathComponent("runtime/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Requires the locked runtime test environment") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-codex-adapter-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let program = """
        import json,sys,os
        from pathlib import Path
        mode=\(String(reflecting: mode)); cwd=\(String(reflecting: directory.path)); thread='fixture-thread'; turn='fixture-turn'
        def send(v): print(json.dumps(v),flush=True)
        def response(r,v): send({'id':r['id'],'result':v})
        def event(m,p): send({'method':m,'params':dict(threadId=thread,**p)})
        if mode=='lifetime-fail':
            import uuid
            if os.getpgrp()!=os.getpid(): os.setsid()
            lifetime_token=str(uuid.uuid4())
            send(dict(method='maltose/lifetime/started',params=dict(rootPID=os.getpid(),token=lifetime_token)))
        init=json.loads(input()); response(init,{})
        assert json.loads(input())['method']=='initialized'
        turns=[]; interrupts=0; first_panel_result=None
        for line in sys.stdin:
            r=json.loads(line)
            if 'method' not in r:
                if mode=='panel-uncertain':
                    assert not r['result']['success']
                    if first_panel_result is None:
                        first_panel_result=r['result']
                        send(dict(id=43,method='item/tool/call',params=dict(threadId=thread,turnId=turn,callId='same-call',
                            tool='maltose_notes_set_text',arguments=dict(panelID='notes',text='once'))))
                    else:
                        assert r['result']==first_panel_result
                        event('turn/completed',{'turn':dict(id=turn,status='completed',items=[])})
                    continue
                if mode=='question':
                    assert r['result']=={'answers':{'public':{'answers':['New requirement']},'secret':{'answers':['fixture-sensitive-answer']}}}
                else: assert r['result']=={'decision':'decline'}
                event('serverRequest/resolved',{'requestId':42})
                event('turn/completed',{'turn':dict(id=turn,status='interrupted',items=[])})
                continue
            m=r['method']; p=r.get('params',{})
            if m=='fixture/lifetime-fail':
                response(r,{})
                send(dict(method='maltose/lifetime/failed',params=dict(rootPID=os.getpid(),token=lifetime_token)))
                for _ in sys.stdin: pass
                break
            elif m=='account/read': response(r,{'requiresOpenaiAuth':True,'account':None})
            elif m=='model/list':
                data=[dict(id='primary',model='primary',displayName='Primary',isDefault=True)] if not p.get('cursor') else [dict(id='secondary',model='secondary',displayName='Secondary',isDefault=False)]
                cursor='page-2' if not p.get('cursor') or mode=='catalog-cycle' else None
                response(r,dict(data=data,nextCursor=cursor))
            elif m=='thread/start':
                assert p['cwd']==cwd and p['sandbox']=='workspace-write' and p['approvalPolicy']=='on-request'
                if mode=='catalog': assert p['model']=='secondary'
                response(r,{'thread':dict(id=thread,cwd=cwd,turns=[])})
            elif m=='thread/resume':
                assert p['threadId']==thread and p['cwd']==cwd
                if mode=='catalog': assert p['model']=='secondary'
                history=[]
                if mode=='legacy-history' and not p.get('excludeTurns',False):
                    history=[dict(id=turn,status='completed',items=[dict(type='agentMessage',id='result',text='Fixture evidence')])]
                response(r,{'thread':dict(id=thread,cwd=cwd,turns=history)})
            elif m=='thread/read':
                items=[dict(type='agentMessage',id='result',text='Recovered fixture evidence')]
                if mode=='lost-ack':
                    accepted=json.loads(Path(cwd,'accepted.json').read_text())
                    items.insert(0,dict(type='userMessage',id='user-item',clientId=accepted['clientId'],content=[]))
                if mode=='legacy-history': send({'id':r['id'],'error':{'code':-32601,'message':'history method unavailable'}})
                elif mode=='interrupt-race': response(r,{'thread':dict(id=thread,cwd=cwd,turns=[dict(id=turn,status='inProgress',items=[])])})
                else: response(r,{'thread':dict(id=thread,cwd=cwd,turns=[dict(id=turn,status='completed',items=items)])})
            elif m=='turn/start':
                assert p['threadId']==thread and p['clientUserMessageId']
                event('turn/started',{'turn':dict(id=turn,status='inProgress',items=[])})
                if mode=='uncertain':
                    response(r,{'turn':dict(id=turn)}); os._exit(0)
                elif mode.startswith('lost-ack'):
                    Path(cwd,'accepted.json').write_text(json.dumps({'clientId':p['clientUserMessageId']}))
                    os._exit(0)
                elif mode=='approval':
                    response(r,{'turn':dict(id=turn)})
                    send({'id':42,'method':'item/commandExecution/requestApproval','params':dict(threadId=thread,turnId=turn,itemId='command')})
                elif mode=='question':
                    response(r,{'turn':dict(id=turn)})
                    send({'id':42,'method':'item/tool/requestUserInput','params':dict(threadId=thread,turnId=turn,itemId='question',isBlocking=True,questions=[
                        dict(id='public',header='Requirement',question='What should change?'),
                        dict(id='secret',header='Secret',question='Fixture secret?',isSecret=True)])})
                elif mode=='panel-uncertain':
                    response(r,{'turn':dict(id=turn)})
                    send(dict(id=42,method='item/tool/call',params=dict(threadId=thread,turnId=turn,callId='same-call',
                        tool='maltose_notes_set_text',arguments=dict(panelID='notes',text='once'))))
                elif mode in ('steer','interrupt-race'): response(r,{'turn':dict(id=turn)})
                else:
                    item=dict(type='agentMessage',id='result',text='Fixture evidence')
                    if mode=='tool': item=dict(type='commandExecution',id='command',command='fixture-check',cwd=cwd,status='completed',exitCode=0,aggregatedOutput='fixture passed')
                    else: event('item/agentMessage/delta',dict(turnId=turn,itemId='result',delta='Fixture evidence'))
                    event('item/completed',dict(turnId=turn,item=item))
                    item=dict(reversed(list(item.items())))
                    event('turn/completed',{'turn':dict(id=turn,status='completed',items=[item])})
                    # Deliberately complete before acknowledging the start RPC.
                    response(r,{'turn':dict(id=turn)})
            elif m=='turn/steer':
                assert p['threadId']==thread and p['expectedTurnId']==turn and p['clientUserMessageId']
                item=dict(type='agentMessage',id='result',text='Steered fixture result')
                event('turn/completed',{'turn':dict(id=turn,status='completed',items=[item])})
                response(r,{'turnId':turn})
            elif m=='turn/interrupt':
                assert p['threadId']==thread and p['turnId']==turn
                if mode=='interrupt-race' and interrupts==0:
                    interrupts+=1; send({'id':r['id'],'error':{'code':-32600,'message':'no active turn to interrupt'}})
                else:
                    response(r,{})
                    event('turn/completed',{'turn':dict(id=turn,status='interrupted',items=[])})
            else: send({'id':r['id'],'error':{'code':-32601,'message':'unsupported fixture method'}})
        """
        return .init(executable: python, arguments: ["-u", "-c", program], directory: directory,
                     logURL: directory.appendingPathComponent("codex.log"), startupTimeout: .seconds(3),
                     requestTimeout: .seconds(3), shutdownGrace: .milliseconds(50))
    }
    private func record(_ config: CodexLaunchConfiguration) -> CodexTaskRecord {
        .init(conversationID: "native-session", repositoryPath: config.directory.path, worktreePath: config.directory.path,
              delegation: .init(objective: "Fixture work", constraints: [], acceptanceCriteria: ["Fixture evidence"]))
    }
    private func waitFor(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(6)
        while !condition(), Date() < deadline { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(condition(), file: file, line: line)
    }

    func testTurnCompletionPersistsEvidenceWithoutCompletingProductTaskOrResumingMaltose() async throws {
        let config = try fixture(); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store)
        defer { store.close() }
        var issues: [String] = [], deltas = ""
        adapter.onIssue = { issues.append($0) }
        adapter.onEvent = { _, method, value in if method == "item/agentMessage/delta" { deltas += value["delta"]?.stringValue ?? "" } }
        try await connection.start(configuration: config)
        let authenticated = try await adapter.authenticationAvailable()
        XCTAssertFalse(authenticated)
        let id = try await adapter.createTask(record(config))
        try store.update(id) { $0.control = .codexDirect }
        let turn = try await adapter.submit("Fixture request", to: id, author: .user, origin: .native)
        XCTAssertEqual(turn, "fixture-turn")
        try await waitFor { store.task(id)?.status == .awaitingReview }
        XCTAssertNil(store.task(id)?.activeTurnID)
        XCTAssertEqual(store.task(id)?.control, .codexDirect)
        XCTAssertEqual(store.task(id)?.messages.map(\.author), [.user, .codex])
        XCTAssertEqual(store.task(id)?.messages.first?.turnID, turn)
        XCTAssertEqual(store.task(id)?.messages.first?.delivery, .accepted)
        XCTAssertEqual(deltas, "Fixture evidence")
        XCTAssertTrue(issues.isEmpty)
        connection.stop(); try await waitFor { connection.processID == nil }
        XCTAssertEqual(store.task(id)?.status, .awaitingReview)
    }

    func testUncertainPanelToolResultIsDurableAndDuplicateCallNeverReexecutesMutation() async throws {
        let config = try fixture(mode: "panel-uncertain")
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store)
        defer { store.close(); connection.stop() }
        connection.experimentalAPI = true
        adapter.panelTools = WorkspaceAgentToolDefinitions.all.filter { $0.command == "notes_set_text" }
        var calls = 0
        adapter.onPanelTool = { _, _, _, _ in
            calls += 1
            throw CodexConnectionError.outcomeUnknown("panel response lost after mutation")
        }
        adapter.onInteraction = { _, _ in XCTFail("A dynamic tool must not become a human approval") }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Uncertain panel mutation", to: id, author: .user, origin: .native)
        try await waitFor { store.task(id)?.status == .awaitingReview }
        XCTAssertEqual(calls, 1)
        XCTAssertTrue(adapter.activePanelCalls.isEmpty)
        let receipts = try XCTUnwrap(store.task(id)?.messages.filter { $0.id.hasPrefix("panel:") })
        XCTAssertEqual(receipts.count, 2)
        XCTAssertEqual(receipts.map(\.author), [.codex, .tool])
        let result = try JSONDecoder().decode(UserViewValue.self, from: Data(try XCTUnwrap(receipts.last?.content).utf8))
        XCTAssertEqual(result["success"], .boolean(false))
        XCTAssertTrue(result["contentItems"]?.arrayValue?.first?["text"]?.stringValue?.contains("outcome_unknown") == true)
        connection.stop(); try await waitFor { connection.processID == nil }
        store.close()
        let reopened = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json")); try reopened.open(); defer { reopened.close() }
        XCTAssertEqual(reopened.task(id)?.messages.filter { $0.id.hasPrefix("panel:") }, receipts)
    }

    func testApprovalRemainsWaitingAndDeclineIsNotTaskSuccess() async throws {
        let config = try fixture(mode: "approval"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        var request: CodexServerRequest?
        adapter.onInteraction = { _, value in request = value }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Approval fixture", to: id, author: .maltose, origin: .delegation)
        try await waitFor { request != nil }
        XCTAssertEqual(store.task(id)?.status, .waitingForUser)
        XCTAssertTrue(adapter.respond(to: try XCTUnwrap(request), result: .success(.object(["decision": .string("decline")]))))
        try await waitFor { store.task(id)?.status == .interrupted }
        XCTAssertFalse(adapter.respond(to: try XCTUnwrap(request), result: .success(.object(["decision": .string("accept")]))))
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testHumanQuestionResponseRetainsProvenanceAndRedactsSecretFromProductJournal() async throws {
        let config = try fixture(mode: "question"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close(); connection.stop() }
        var request: CodexServerRequest?
        adapter.onInteraction = { _, value in request = value }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Question fixture", to: id, author: .user, origin: .native)
        try await waitFor { request != nil }
        let answer: UserViewValue = .object(["answers": .object([
            "public": .object(["answers": .strings(["New requirement"])]),
            "secret": .object(["answers": .strings(["fixture-sensitive-answer"])])])])
        XCTAssertTrue(adapter.respond(to: try XCTUnwrap(request), result: .success(answer)))
        try await waitFor { store.task(id)?.status == .interrupted }
        let receipts = try XCTUnwrap(store.task(id)?.messages.filter { $0.author == .integration })
        XCTAssertEqual(receipts.count, 2)
        XCTAssertEqual(receipts.map(\.origin), [.codex, .native])
        XCTAssertEqual(receipts.last?.delivery, .accepted)
        XCTAssertTrue(receipts.last?.content.contains("New requirement") == true)
        XCTAssertFalse(try String(contentsOf: config.directory.appendingPathComponent("tasks.json"), encoding: .utf8).contains("fixture-sensitive-answer"))
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testPaginatedModelSelectionPinsTaskModelAcrossRestartAndFuturePreferenceChanges() async throws {
        let config = try fixture(mode: "catalog"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close(); connection.stop() }
        try await connection.start(configuration: config)
        let choices = try await adapter.models()
        XCTAssertEqual(choices.map(\.model), ["primary", "secondary"])
        XCTAssertEqual(choices.first?.isDefault, true)
        adapter.modelID = "secondary"; try store.setPreferredModel("secondary")
        let id = try await adapter.createTask(record(config))
        XCTAssertEqual(store.task(id)?.model, "secondary")
        XCTAssertThrowsError(try store.update(id) { $0.model = "primary" })
        adapter.modelID = "primary"; try store.setPreferredModel("primary")
        connection.stop(); try await waitFor { connection.processID == nil }
        try await connection.start(configuration: config)
        try await adapter.attachIfNeeded(id)
        XCTAssertEqual(store.task(id)?.model, "secondary")
        connection.stop(); try await waitFor { connection.processID == nil }
        store.close(); try store.open()
        XCTAssertEqual(store.preferredModel, "primary")
        XCTAssertEqual(store.task(id)?.model, "secondary")
    }

    func testCyclicModelCatalogFailsInsteadOfLoopingOrInventingFallback() async throws {
        let config = try fixture(mode: "catalog-cycle"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close(); connection.stop() }
        try await connection.start(configuration: config)
        do { _ = try await adapter.models(); XCTFail("Repeated cursor must fail") }
        catch CodexConnectionError.protocolViolation {}
        XCTAssertNil(store.preferredModel)
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testDisconnectRequiresReadingExistingThreadBeforeAnyFurtherInput() async throws {
        let config = try fixture(mode: "uncertain"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        do { _ = try await adapter.submit("Before disconnect", to: id, author: .user, origin: .voice) } catch {}
        try await waitFor { connection.processID == nil }
        XCTAssertEqual(store.task(id)?.status, .needsReconciliation)
        do { _ = try await adapter.submit("Must not replay", to: id, author: .user, origin: .native); XCTFail("Requires reconciliation") } catch {}
        try await connection.start(configuration: config)
        try await adapter.reconcile(id)
        XCTAssertEqual(store.task(id)?.threadID, "fixture-thread")
        XCTAssertNil(store.task(id)?.activeTurnID)
        XCTAssertEqual(store.task(id)?.status, .awaitingReview)
        XCTAssertTrue(store.task(id)?.messages.contains { $0.content == "Recovered fixture evidence" } == true)
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testDirectFollowupSteersSameThreadAndRetainsUserAndDelegatorProvenance() async throws {
        let config = try fixture(mode: "steer"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        let first = try await adapter.submit("Delegated scope", to: id, author: .maltose, origin: .delegation)
        let second = try await adapter.submit("User adds requirement", to: id, author: .user, origin: .voice)
        XCTAssertEqual(first, second)
        XCTAssertEqual(store.task(id)?.threadID, "fixture-thread")
        XCTAssertEqual(store.task(id)?.status, .awaitingReview)
        XCTAssertEqual(store.task(id)?.messages.map(\.author), [.maltose, .user, .codex])
        XCTAssertEqual(store.task(id)?.messages[1].origin, .voice)
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testInstalledCodexPrivateStdioHandshakeInterruptAndThreadResume() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_CODEX_TESTS"] == "1" else { throw XCTSkip("Opt in to installed Codex app-server integration") }
        let executable = URL(fileURLWithPath: ProcessInfo.processInfo.environment["MALTOSE_CODEX_EXECUTABLE"] ?? "/opt/homebrew/bin/codex")
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: executable.path))
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-real-codex-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        // Codex may retain protected sockets in its home until process cleanup completes.
        // Teardown is explicit below, after both server instances have been reaped.
        let home = base.appendingPathComponent("codex-home")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        var environment = ProcessInfo.processInfo.environment
        for key in ["OPENAI_API_KEY", "CODEX_API_KEY", "ACCESS_TOKEN"] { environment.removeValue(forKey: key) }
        environment["CODEX_HOME"] = home.path
        // The provider is a deliberately closed localhost port: no account or external inference.
        // An empty thread has no persisted rollout in 0.155.1. Start/interrupt a fixture turn
        // before checking persistence/resume; never claim empty thread creation guarantees it.
        let arguments = ["-c", "model_provider=\"maltose_fixture\"", "-c", "model=\"fixture\"",
            "-c", "model_providers.maltose_fixture.name=\"Maltose offline fixture\"",
            "-c", "model_providers.maltose_fixture.base_url=\"http://127.0.0.1:9/v1\"",
            "-c", "model_providers.maltose_fixture.wire_api=\"responses\"",
            "-c", "model_providers.maltose_fixture.requires_openai_auth=false",
            "-c", "model_providers.maltose_fixture.request_max_retries=0",
            "-c", "model_providers.maltose_fixture.stream_max_retries=0",
            "-c", "features.plugins=false", "-c", "features.apps=false", "app-server"]
        let config = CodexLaunchConfiguration(executable: executable, arguments: arguments, directory: base, logURL: base.appendingPathComponent("codex.log"),
                                             environment: environment, startupTimeout: .seconds(15))
        let connection = CodexConnection(), store = CodexTaskStore(url: base.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        try await connection.start(configuration: config)
        let available = try await adapter.authenticationAvailable()
        XCTAssertTrue(available)
        let id = try await adapter.createTask(record(config))
        XCTAssertNotNil(store.task(id)?.threadID)
        _ = try await adapter.submit("Offline fixture request", to: id, author: .user, origin: .native)
        try await Task.sleep(for: .milliseconds(100))
        try await adapter.interrupt(id)
        try await waitFor { store.task(id)?.status == .interrupted }
        connection.stop(); try await waitFor { connection.processID == nil }
        try await connection.start(configuration: config)
        try await adapter.reconcile(id)
        XCTAssertEqual(store.task(id)?.status, .interrupted)
        connection.stop(); try await waitFor { connection.processID == nil }
        try FileManager.default.removeItem(at: base)
    }

    func testCompletedToolEvidenceIsCanonicalAcrossDuplicateItemAndTurnEvents() async throws {
        let config = try fixture(mode: "tool"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        var issues: [String] = []; adapter.onIssue = { issues.append($0) }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Fixture check", to: id, author: .user, origin: .native)
        XCTAssertEqual(store.task(id)?.messages.filter { $0.author == .tool }.count, 1)
        XCTAssertEqual(store.task(id)?.status, .awaitingReview)
        XCTAssertTrue(issues.isEmpty)
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testUnsupportedHistoryUsesFullResumeWithoutInventingMissingHistory() async throws {
        let config = try fixture(mode: "legacy-history"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Fixture history", to: id, author: .user, origin: .native)
        connection.stop(); try await waitFor { connection.processID == nil }
        try await connection.start(configuration: config)
        try await adapter.reconcile(id)
        XCTAssertEqual(store.task(id)?.status, .awaitingReview)
        XCTAssertEqual(store.task(id)?.messages.filter { $0.author == .codex }.count, 1)
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testInterruptRegistrationRaceReadsSameTurnBeforeRetryingCancellation() async throws {
        let config = try fixture(mode: "interrupt-race"); defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store); defer { store.close() }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Fixture interrupt", to: id, author: .user, origin: .native)
        try await adapter.interrupt(id)
        try await waitFor { store.task(id)?.status == .interrupted }
        XCTAssertNil(store.task(id)?.activeTurnID)
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testLostStartAcknowledgementRequiresMatchingClientMessageBeforeClearingUncertainty() async throws {
        for mode in ["lost-ack", "lost-ack-missing"] {
            let config = try fixture(mode: mode)
            let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
            let adapter = try CodexAdapter(connection: connection, store: store)
            try await connection.start(configuration: config)
            let id = try await adapter.createTask(record(config))
            do { _ = try await adapter.submit("Accepted before lost acknowledgement", to: id, author: .user, origin: .voice); XCTFail("Lost acknowledgement must remain uncertain") }
            catch CodexConnectionError.outcomeUnknown {}
            try await waitFor { connection.processID == nil }
            XCTAssertEqual(store.task(id)?.messages.first?.delivery, .uncertain)
            XCTAssertEqual(store.task(id)?.status, .needsReconciliation)
            try await connection.start(configuration: config)
            if mode == "lost-ack" {
                try await adapter.reconcile(id)
                XCTAssertEqual(store.task(id)?.messages.first?.delivery, .accepted)
                XCTAssertEqual(store.task(id)?.messages.first?.turnID, "fixture-turn")
                XCTAssertEqual(store.task(id)?.status, .awaitingReview)
                XCTAssertNil(store.task(id)?.pendingOperation)
            } else {
                do { try await adapter.reconcile(id); XCTFail("History without client identity cannot resolve the accepted input") }
                catch CodexConnectionError.outcomeUnknown {}
                XCTAssertEqual(store.task(id)?.status, .needsReconciliation)
                XCTAssertNotNil(store.task(id)?.pendingOperation)
            }
            XCTAssertEqual(store.task(id)?.messages.filter { $0.author == .user }.count, 1)
            connection.stop(); try await waitFor { connection.processID == nil }
            store.close(); try FileManager.default.removeItem(at: config.directory)
        }
    }
    func testIdleCleanupFailureIsVisibleEvenAfterTheTurnHasFinished() async throws {
        var config = try fixture(mode: "lifetime-fail")
        config.ownsProcessGroup = true
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection(), store = CodexTaskStore(url: config.directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: connection, store: store)
        defer { connection.stop(); store.close() }
        var issues: [String] = []
        adapter.onIssue = { issues.append($0) }
        try await connection.start(configuration: config)
        let id = try await adapter.createTask(record(config))
        _ = try await adapter.submit("Fixture", to: id, author: .user, origin: .native)
        try await waitFor { store.task(id)?.status == .awaitingReview }
        XCTAssertTrue(issues.isEmpty)
        _ = try await connection.request("fixture/lifetime-fail")
        try await waitFor { connection.processID == nil }
        XCTAssertFalse(connection.ownedCleanupConfirmed)
        XCTAssertTrue(issues.contains { $0.contains("清理尚未確認") })
        XCTAssertNotEqual(store.task(id)?.status,.completed)
    }

}
