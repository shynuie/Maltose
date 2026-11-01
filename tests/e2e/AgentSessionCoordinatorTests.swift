import XCTest
import AppKit
import Darwin
@testable import MaltoseApp

@MainActor final class AgentSessionCoordinatorTests: XCTestCase {
    private var project: URL { URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent() }

    private struct Fixture: Sendable {
        let directory: URL
        let runtimeConfig: RuntimeLaunchConfiguration
        let codexConfig: CodexLaunchConfiguration
        let store: CodexTaskStore
        let runtime: RuntimeSupervisor
        let adapter: CodexAdapter
        let coordinator: AgentSessionCoordinator
        let history: ConversationHistoryModel
    }

    private func git(_ arguments: [String], in directory: URL) throws {
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        process.arguments = arguments; process.currentDirectoryURL = directory
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        try process.run(); process.waitUntilExit(); XCTAssertEqual(process.terminationStatus, 0)
    }

    private func fixture(holdTurn: Bool = false, reportKind: String = "completed", liveCodex: Bool = false, delegatedBrain: Bool = false, rerouteNative: Bool = false, routedVoice: Bool = false, panelCalls: Bool = false, holdReview: Bool = false, liveMain: Bool = false, background: Bool = false, stubbornBackground: Bool = false, delegateOnStartup: Bool = true, liveDelegation: Bool = false, questionKind: String? = nil, failedTurn: Bool = false, codexLaunch: ((URL) throws -> CodexLaunchConfiguration)? = nil) throws -> Fixture {
        let python = project.appendingPathComponent("runtime/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Requires locked Python runtime") }
        let persistent = liveCodex || liveMain
        let parent = persistent ? project.appendingPathComponent(liveMain ? ".cache/main-live" : ".cache/codex-live") : FileManager.default.temporaryDirectory
        if persistent { try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
        let directory = parent.appendingPathComponent("maltose-session-\(UUID().uuidString)")
        let repo = directory.appendingPathComponent("repository"), config = directory.appendingPathComponent("config")
        try FileManager.default.createDirectory(at: repo, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: config, withIntermediateDirectories: true)
        try "baseline\n".write(to: repo.appendingPathComponent("fixture.txt"), atomically: true, encoding: .utf8)
        if liveCodex {
            try "def add(a, b):\n    return a - b\n".write(to: repo.appendingPathComponent("calculator.py"), atomically: true, encoding: .utf8)
            try """
            import unittest
            from calculator import add
            class CalculatorTests(unittest.TestCase):
                def test_positive(self): self.assertEqual(add(2, 3), 5)
                def test_negative(self): self.assertEqual(add(-2, -3), -5)
                def test_zero(self): self.assertEqual(add(0, 7), 7)
            """.write(to: repo.appendingPathComponent("test_calculator.py"), atomically: true, encoding: .utf8)
        }
        try git(["init", "--quiet"], in: repo)
        try git(["add"] + (liveCodex ? ["fixture.txt", "calculator.py", "test_calculator.py"] : ["fixture.txt"]), in: repo)
        try git(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "fixture"], in: repo)
        var runtimeConfig = RuntimeLaunchConfiguration(executable: python,
            arguments: ["-m", "maltose.desktop", "--native-text-only", "--brain", "echo", "--config", config.appendingPathComponent("none.toml").path,
                        "--taskbrain-codex-cwd", repo.path], directory: config, moduleDirectory: project.appendingPathComponent("runtime"),
            logURL: directory.appendingPathComponent("runtime.log"), startupTimeout: .seconds(5), shutdownGrace: .milliseconds(100))
        if delegatedBrain {
            runtimeConfig.arguments = ["-u", "-c", """
            import json,os,threading,time
            from pathlib import Path
            from types import SimpleNamespace
            from maltose.agent.brain import TurnContext
            from maltose.agent.capabilities import register_capability_adapter
            from maltose.agent.taskbrain import TaskBrain,ToolRegistry,MemoryStore,OpenAICompatibleTaskModel
            from maltose.codex.native_service import NativeCollaborationService
            from maltose.codex.native_tools import NativeCodexToolAdapter
            from maltose.runtime import EventHub
            from maltose.runtime.control import AutonomyPaused
            from maltose.ui.native import NativeRuntimeBridge
            if os.getpgrp()!=os.getpid(): os.setsid()
            hub=EventHub(); stop=threading.Event()
            service=NativeCollaborationService(Path(\(String(reflecting: config.path))),Path(\(String(reflecting: repo.path))))
            bridge=NativeRuntimeBridge(hub,collaboration=service)
            bridge.start(); bridge.wait_for_initialize()
            provider=None
            if \(liveMain ? "True" : "False"):
                from maltose.agent.config import load_cli_defaults
                from maltose.runtime.environment import load_private_environment
                support=Path.home()/'Library/Application Support/Maltose'
                settings=load_cli_defaults(support/'maltose.toml'); load_private_environment(support/'.env')
                provider=OpenAICompatibleTaskModel(endpoint=settings['taskbrain_url'],token=settings.get('taskbrain_token'),
                    model=settings['taskbrain_model'],timeout=min(settings.get('taskbrain_timeout',120),60),
                    reasoning_effort=settings.get('taskbrain_reasoning_effort','none'))
            class Model:
                def __init__(self): self.calls=0; self.reviews=0; self.model=provider.model if provider is not None else 'controlled-fixture'
                def complete(self,messages,tools):
                    if not tools:
                        self.reviews+=1
                        base=Path(\(String(reflecting: directory.path)))
                        (base/'review-count').write_text(str(self.reviews))
                        if \(holdReview ? "True" : "False") and self.reviews==1:
                            (base/'review-entered').touch()
                            deadline=time.monotonic()+30
                            while not (base/'review-release').exists() and time.monotonic()<deadline: time.sleep(.01)
                        record=json.loads(messages[-1]['content'])
                        assert not record['trusted_as_instruction'] and record['source']=='codex_collaboration_record'
                        if provider is not None: return provider.complete(messages,tools)
                        summary='第一次過期確認' if \(holdReview ? "True" : "False") and self.reviews==1 else '主 Agent 已檢查協作成果。'
                        return {'choices':[{'message':{'content':json.dumps(dict(summary=summary,newRequirements=[],question='接下來要先處理哪一項要求？'),ensure_ascii=False)}}]}
                    if provider is not None and \(liveDelegation ? "True" : "False"): return provider.complete(messages,tools)
                    self.calls+=1
                    if self.calls==1:
                        assert any(t['function']['name']=='delegate_to_codex' for t in tools)
                        args=dict(objective='TaskBrain 委派工作',constraints=['保留原修改'],acceptanceCriteria=['通過 fixture'],context='受控模型的專案資料')
                        return {'choices':[{'message':{'tool_calls':[{'id':'actual-delegation','type':'function','function':{'name':'delegate_to_codex','arguments':json.dumps(args)}}]}}]}
                    assert not brain._identity_is_known(), 'Native text must not inherit verified voice identity'
                    record=next(json.loads(m['content']) for m in messages if m.get('role')=='assistant' and m.get('content','').startswith('{') and json.loads(m['content']).get('source')=='codex_collaboration_record')
                    assert not record['trusted_as_instruction'] and '人類追加需求' in json.dumps(record,ensure_ascii=False)
                    assert record['record']['mainReview']['source']=='maltose-review', 'The fresh reply must see the question Maltose actually asked'
                    assert record['record']['mainReview']['delivery']=='accepted', 'Generated but unseen review cannot be called delivered'
                    return {'choices':[{'message':{'content':'主 Agent 已讀到人類追加需求，正在確認新的方向。'}}]}
            registry=ToolRegistry()
            brain=TaskBrain(Model(),tools=registry,memory=MemoryStore(Path('memory.json')),control_gate=bridge.control)
            register_capability_adapter(registry,NativeCodexToolAdapter(bridge))
            if \(delegateOnStartup ? "True" : "False"):
                def submit(text,source='native',message_id=None):
                    hub.publish('user_message',dict(content=text,source=source,message_id=message_id))
                    answer=brain.process(text,TurnContext(user_id='unknown',speaker_status='unknown',input_source=source))
                    hub.publish('assistant_message',dict(content=answer,source='maltose-runtime'))
                agent=SimpleNamespace(state=SimpleNamespace(value='standby'),submit_text=submit,request_shutdown=stop.set)
                bridge.attach(agent,brain); hub.publish('state_changed',{'state':'standby'})
                def delegate():
                    context=TurnContext(user_id='owner',speaker_status='identified',input_source='voice')
                    bridge.observe_voice_context(context)
                    try: brain.process('請處理開發',context)
                    except AutonomyPaused: pass
                worker=threading.Thread(target=delegate); worker.start()
                stop.wait(120); worker.join(2); bridge.close()
            else:
                from maltose.agent.agent import VoiceAgent
                agent=VoiceAgent(brain=brain,voice_enabled=False,event_hub=hub,control_gate=bridge.control)
                bridge.attach(agent,brain); agent.run(); bridge.close()
            """]
        } else if routedVoice {
            runtimeConfig.arguments = ["-u", "-c", """
            import os,threading,time
            from pathlib import Path
            from maltose.agent.agent import VoiceAgent
            from maltose.agent.brain import EchoBrain,TurnContext
            from maltose.codex.native_service import NativeCollaborationService,CONTROL_OWNER
            from maltose.runtime import EventHub
            from maltose.ui.native import NativeRuntimeBridge
            if os.getpgrp()!=os.getpid(): os.setsid()
            hub=EventHub()
            service=NativeCollaborationService(Path(\(String(reflecting: config.path))),Path(\(String(reflecting: repo.path))))
            bridge=NativeRuntimeBridge(hub,collaboration=service)
            class Brain(EchoBrain):
                def process(self,text,context=None):
                    assert (context.user_id,context.speaker_status,context.input_source)==('owner','identified','voice')
                    return '已保留語音來源與當次驗證身分：'+text
            brain=Brain(); agent=VoiceAgent(brain=brain,voice_enabled=False,event_hub=hub,control_gate=bridge.control)
            bridge.attach(agent,brain); bridge.start(); bridge.wait_for_initialize(); bridge.control.pause(CONTROL_OWNER)
            def inject():
                while not bridge._ready: time.sleep(.01)
                bridge.route_input('@maltose 新的語音方向',TurnContext(user_id='owner',speaker_status='identified',input_source='voice'),
                    'voice',bridge.control.epoch,'runtime-voice')
            threading.Thread(target=inject,daemon=True).start()
            agent.run(); bridge.close()
            """]
        } else if rerouteNative {
            runtimeConfig.arguments = ["-u", "-c", """
            import os,threading
            from pathlib import Path
            from types import SimpleNamespace
            from maltose.agent.brain import TurnContext
            from maltose.codex.native_service import NativeCollaborationService,CONTROL_OWNER
            from maltose.runtime import EventHub
            from maltose.ui.native import NativeRuntimeBridge
            if os.getpgrp()!=os.getpid(): os.setsid()
            hub=EventHub(); stop=threading.Event()
            service=NativeCollaborationService(Path(\(String(reflecting: config.path))),Path(\(String(reflecting: repo.path))))
            bridge=NativeRuntimeBridge(hub,collaboration=service)
            def submit(text,source='native',message_id=None):
                # Queue acceptance races with closing the runtime's admission gate.
                bridge.control.pause(CONTROL_OWNER)
                bridge.route_input(text,TurnContext(user_id='unknown',speaker_status='unknown'),source,bridge.control.epoch,message_id)
            bridge.start(); bridge.wait_for_initialize()
            agent=SimpleNamespace(state=SimpleNamespace(value='standby'),submit_text=submit,request_shutdown=stop.set)
            bridge.attach(agent,None); hub.publish('state_changed',{'state':'standby'})
            stop.wait(60); bridge.close()
            """]
        }
        let program = """
        import json,sys,time,subprocess,atexit
        from pathlib import Path
        base=Path(\(String(reflecting: directory.path)))
        saved=base/'codex-state.json'
        state=json.loads(saved.read_text()) if saved.exists() else dict(count=0,cwd=None,turns=[])
        thread='session-thread'
        background_process=None
        def stop_background():
            if background_process is not None and background_process.poll() is None:
                background_process.kill(); background_process.wait(timeout=3)
        atexit.register(stop_background)
        def send(v): print(json.dumps(v),flush=True)
        def response(r,v): send(dict(id=r['id'],result=v))
        def event(m,**p): send(dict(method=m,params=dict(threadId=thread,**p)))
        def snapshot(): return dict(id=thread,cwd=state['cwd'],turns=state['turns'])
        for line in sys.stdin:
            r=json.loads(line); m=r.get('method'); p=r.get('params',{})
            if m=='initialize': response(r,{})
            elif m=='initialized': pass
            elif m=='account/read': response(r,dict(requiresOpenaiAuth=False,account=None))
            elif m=='model/list': response(r,dict(data=[dict(id='fixture-model',model='fixture-model',displayName='Fixture',isDefault=True)],nextCursor=None))
            elif m=='thread/backgroundTerminals/list':
                assert p['threadId']==thread
                alive=\(stubbornBackground ? "True" : "False") or background_process is not None and background_process.poll() is None
                data=[dict(processId='fixture-background',itemId='background-item',command='fixture sleep',cwd=state['cwd'],
                    osPid=background_process.pid if background_process is not None else None)] if alive else []
                response(r,dict(data=data,nextCursor=None))
            elif m=='thread/backgroundTerminals/clean':
                assert p['threadId']==thread
                if not \(stubbornBackground ? "True" : "False"): stop_background()
                (base/'background-cleaned').touch(); response(r,{})
            elif m=='thread/start':
                assert state['cwd'] is None, 'must not create a replacement thread'
                if \(panelCalls ? "True" : "False"):
                    assert len(p['dynamicTools'])==36 and all(t['type']=='function' for t in p['dynamicTools'])
                state['cwd']=p['cwd']; saved.write_text(json.dumps(state)); response(r,dict(thread=snapshot()))
            elif m in ('thread/read','thread/resume'): response(r,dict(thread=snapshot()))
            elif m=='turn/start':
                assert p['threadId']==thread and p['outputSchema']['type']=='object'
                state['count']+=1; turn='turn-'+str(state['count']); text=p['input'][0]['text']
                with (base/'received.jsonl').open('a') as f: f.write(json.dumps(p)+'\\n')
                event('turn/started',turn=dict(id=turn,status='inProgress',items=[]))
                if \(background ? "True" : "False") and background_process is None:
                    background_process=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(300)'],
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                    (base/'background.pid').write_text(str(background_process.pid))
                if \(panelCalls ? "True" : "False"):
                    def panel(name,args,call_id,wire_id,wrong_turn=False):
                        send(dict(id=wire_id,method='item/tool/call',params=dict(threadId=thread,turnId='wrong-turn' if wrong_turn else turn,
                            callId=call_id,tool='maltose_'+name,arguments=args)))
                        reply=json.loads(next(sys.stdin)); assert reply['id']==wire_id
                        return reply
                    def content(reply):
                        assert reply['result']['success'],reply
                        return json.loads(reply['result']['contentItems'][0]['text'])
                    content(panel('get_user_view',{},'read-view','view-rpc'))
                    created=content(panel('create_panel',dict(kind='notes'),'create-notes','create-rpc'))
                    panel_id=created['result']['panelID']
                    duplicate=content(panel('create_panel',dict(kind='notes'),'create-notes','duplicate-rpc'))
                    assert duplicate['result']['panelID']==panel_id
                    content(panel('notes_set_text',dict(panelID=panel_id,text='Codex shared panel fixture'),'write-note','write-rpc'))
                    read=content(panel('read_panel',dict(panelID=panel_id),'read-note','read-rpc'))
                    assert 'Codex shared panel fixture' in json.dumps(read)
                    assert 'error' in panel('notes_set_text',dict(panelID=panel_id,text='must not run'),'write-note','conflict-rpc')
                    assert 'error' in panel('notes_set_text',dict(panelID=panel_id,text='stale must not run'),'stale','stale-rpc',wrong_turn=True)
                if \(holdTurn ? "True" : "False"):
                    state['turns'].append(dict(id=turn,status='inProgress',items=[])); saved.write_text(json.dumps(state))
                    time.sleep(.2); response(r,dict(turn=dict(id=turn))); continue
                if \(questionKind != nil ? "True" : "False"):
                    response(r,dict(turn=dict(id=turn)))
                    send(dict(id='human-question',method='item/tool/requestUserInput',params=dict(threadId=thread,turnId=turn,
                        questions=[dict(id='answer',question='Fixture answer?',header='Fixture',isSecret=\(questionKind == "secret" ? "True" : "False"),options=None)])))
                    while True:
                        reply=json.loads(sys.stdin.readline())
                        if reply.get('id')=='human-question': break
                        # Authentication reads are valid while a user question is open.
                        assert reply.get('method')=='account/read',reply
                        response(reply,dict(requiresOpenaiAuth=False,account=None))
                    assert 'result' in reply,reply
                    answers=reply['result']['answers']['answer']['answers']
                    assert answers==['fixture-secret-sentinel' if \(questionKind == "secret" ? "True" : "False") else '公開問題的回答'], 'unexpected answer'
                    (base/'question-answered').touch()
                Path(state['cwd'],'fixture.txt').write_text(text+'\\n')
                report=dict(kind=\(String(reflecting: reportKind)),summary='完成 '+text,nextQuestion='',tests=['fixture check'],
                    remaining=[] if \(String(reflecting: reportKind))=='completed' else ['尚有工作'])
                item=dict(type='agentMessage',id='result',text=json.dumps(report,ensure_ascii=False))
                terminal=dict(id=turn,status='completed',items=[dict(type='userMessage',id='user',clientId=p['clientUserMessageId'],content=[]),item])
                if \(failedTurn ? "True" : "False") and state['count']==1:
                    terminal.update(status='failed',error=dict(message='fixture provider unavailable'))
                    terminal['items']=terminal['items'][:1]
                state['turns'].append(terminal); saved.write_text(json.dumps(state))
                # No item/completed notification, and completion precedes the RPC acknowledgement.
                event('turn/completed',turn=terminal)
                if \(questionKind == nil ? "True" : "False"): response(r,dict(turn=dict(id=turn)))
            elif m=='turn/interrupt':
                turn=state['turns'][-1]; turn['status']='interrupted'; saved.write_text(json.dumps(state))
                response(r,{}); event('turn/completed',turn=turn)
            else: send(dict(id=r['id'],error=dict(code=-32601,message='unsupported fixture request')))
        """
        var codexConfig = CodexLaunchConfiguration(executable: python, arguments: ["-u", "-c", program], directory: directory,
            logURL: directory.appendingPathComponent("codex.log"), startupTimeout: .seconds(3), requestTimeout: .seconds(3), shutdownGrace: .milliseconds(50))
        if liveCodex {
            let executable = ProcessInfo.processInfo.environment["MALTOSE_CODEX_EXECUTABLE"] ?? "/opt/homebrew/bin/codex"
            guard FileManager.default.isExecutableFile(atPath: executable) else { throw XCTSkip("Requires installed Codex") }
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONPATH"] = project.appendingPathComponent("runtime").path
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            codexConfig = .init(executable: python, arguments: ["-m", "maltose.codex.runner", executable, "app-server"], directory: directory,
                logURL: directory.appendingPathComponent("codex.log"), environment: environment, startupTimeout: .seconds(20),
                requestTimeout: .seconds(30), shutdownGrace: .seconds(2), ownsProcessGroup: true)
        }
        if let codexLaunch { codexConfig = try codexLaunch(directory) }
        let launchConfiguration = codexConfig
        let store = CodexTaskStore(url: directory.appendingPathComponent("tasks.json"))
        let adapter = try CodexAdapter(connection: CodexConnection(), store: store)
        let runtime = RuntimeSupervisor()
        let coordinator = try AgentSessionCoordinator(runtime: runtime, codex: adapter, launchCodex: { launchConfiguration })
        let history = ConversationHistoryModel()
        try history.enableLiveStorage(at: directory.appendingPathComponent("history.jsonl"))
        coordinator.emit = { try history.applyRuntimeEvent($0) }
        runtime.onEvent = { [weak coordinator] data in
            do { try coordinator?.receiveRuntime(data) } catch { coordinator?.eventFailed(error.localizedDescription) }
        }
        runtime.onStateChange = { [weak coordinator] state in if state == .ready { coordinator?.runtimeReady() } }
        addTeardownBlock { @MainActor in
            await withCheckedContinuation { continuation in coordinator.shutdown { continuation.resume() } }
            await withCheckedContinuation { continuation in runtime.stop { continuation.resume() } }
            history.closeLiveStorage(); store.close()
            if !persistent { try? FileManager.default.removeItem(at: directory) }
        }
        return .init(directory: directory, runtimeConfig: runtimeConfig, codexConfig: codexConfig, store: store,
                     runtime: runtime, adapter: adapter, coordinator: coordinator, history: history)
    }

    private func waitFor(seconds: Double = 10, _ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(seconds)
        while !condition(), Date() < deadline { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(condition(), file: file, line: line)
        if !condition() { throw CodexTaskStoreError.invalid("Session fixture did not reach expected state") }
    }
    private func stop(_ f: Fixture) async throws {
        await withCheckedContinuation { continuation in f.coordinator.shutdown { continuation.resume() } }
        f.runtime.stop(); try await waitFor { f.runtime.processID == nil }
        f.store.close(); f.history.closeLiveStorage()
    }

    func testInstalledUnauthenticatedCodexPreservesQueuedInputAndMainPauseWithoutStartingTask() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_CODEX_TESTS"] == "1" else {
            throw XCTSkip("Opt in to installed Codex app-server integration")
        }
        let f = try fixture(codexLaunch: { directory in
            let executable = ProcessInfo.processInfo.environment["MALTOSE_CODEX_EXECUTABLE"] ?? "/opt/homebrew/bin/codex"
            guard FileManager.default.isExecutableFile(atPath: executable) else { throw XCTSkip("Requires installed Codex") }
            let home = directory.appendingPathComponent("isolated-codex-home")
            try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            // File-only auth in a fresh home cannot consume the user's keyring.
            // Keep only OS/runtime essentials; no API key or access token is inherited.
            let allowed = Set(["PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "SHELL"])
            var environment = ProcessInfo.processInfo.environment.filter { allowed.contains($0.key) }
            environment["CODEX_HOME"] = home.path
            environment["PYTHONPATH"] = self.project.appendingPathComponent("runtime").path
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            return .init(executable: self.project.appendingPathComponent("runtime/.venv/bin/python"),
                arguments: ["-m", "maltose.codex.runner", executable,
                    "-c", "cli_auth_credentials_store=\"file\"", "-c", "model_provider=\"openai\"",
                    "-c", "features.plugins=false", "-c", "features.apps=false", "app-server"],
                directory: directory, logURL: directory.appendingPathComponent("unauthenticated-codex.log"),
                environment: environment, startupTimeout: .seconds(20), requestTimeout: .seconds(10),
                shutdownGrace: .seconds(2), ownsProcessGroup: true)
        })
        // Verify isolation before sending any development request. Managed
        // authentication requirements must never cause this test to use an account.
        try await f.adapter.connection.start(configuration: f.codexConfig)
        let isolated = try await f.adapter.connection.request("account/read", params: .object(["refreshToken": .boolean(false)]))
        guard isolated["requiresOpenaiAuth"] == .boolean(true), isolated["account"] == .null else {
            XCTFail("Temporary Codex must have no account before any user request is sent")
            return
        }
        f.adapter.connection.stop(); try await waitFor { f.adapter.connection.processID == nil }
        var issues: [String] = []
        f.coordinator.onIssue = { issues.append($0) }
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 未登入時保留的開發要求", identity: "unauthenticated-input"))
        try await waitFor(seconds: 25) { f.coordinator.conversation.issue?.contains("尚未登入") == true }
        let account = try await f.adapter.connection.request("account/read", params: .object(["refreshToken": .boolean(false)]))
        XCTAssertEqual(account["requiresOpenaiAuth"], .boolean(true)); XCTAssertEqual(account["account"], .null)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.coordinator.conversation.recipient, .codex)
        XCTAssertNil(f.coordinator.conversation.activeTaskID); XCTAssertNil(f.coordinator.conversation.workspaceTaskID)
        XCTAssertTrue(f.store.tasks.isEmpty)
        XCTAssertEqual(f.coordinator.conversation.inputs.first?.delivery, .queued)
        XCTAssertEqual(f.coordinator.conversation.inputs.first?.text, "未登入時保留的開發要求")
        XCTAssertFalse(FileManager.default.fileExists(atPath: f.directory.appendingPathComponent("isolated-codex-home/auth.json").path))
        f.coordinator.retry()
        try await waitFor { issues.filter { $0.contains("尚未登入") }.count >= 2 }
        XCTAssertEqual(f.coordinator.conversation.inputs.map(\.id), ["unauthenticated-input"])
        XCTAssertTrue(f.store.tasks.isEmpty); XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.speaker == .user }.count, 1)
        XCTAssertNil(f.coordinator.conversation.pendingQuestionID)
        try await stop(f)
        XCTAssertTrue(f.adapter.connection.ownedCleanupConfirmed)
    }

    func testUnavailableCodexKeepsInputAndAllowsExplicitFreshMainIntent() async throws {
        let f = try fixture(codexLaunch: { directory in
            .init(executable: directory.appendingPathComponent("missing-codex"), directory: directory,
                logURL: directory.appendingPathComponent("missing-codex.log"))
        })
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 尚未送出的開發要求", identity: "unavailable-input"))
        try await waitFor { f.coordinator.conversation.issue?.contains("執行檔不可用") == true }
        XCTAssertEqual(f.runtime.autonomy?.state, .paused); XCTAssertTrue(f.store.tasks.isEmpty)
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertEqual(f.coordinator.conversation.inputs.first?.delivery, .queued)
        XCTAssertTrue(f.coordinator.submit("@maltose 先討論新的方向", identity: "fresh-main-intent"))
        try await waitFor { f.coordinator.conversation.inputs.first { $0.id == "fresh-main-intent" }?.delivery == .accepted }
        XCTAssertEqual(f.runtime.autonomy?.state, .active)
        XCTAssertEqual(f.coordinator.conversation.recipient, .maltose)
        XCTAssertEqual(f.coordinator.conversation.inputs.first { $0.id == "unavailable-input" }?.delivery, .deferred)
        XCTAssertTrue(f.store.tasks.isEmpty)
        let original = f.directory.appendingPathComponent("repository/fixture.txt")
        XCTAssertEqual(try String(contentsOf: original, encoding: .utf8), "baseline\n")
        try await stop(f)
    }

    func testNativeQueueAcknowledgementCannotEraseReroutedInputOrResendItToCodex() async throws {
        let f = try fixture(rerouteNative: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("交接時還沒被接納的文字", identity: "admission-race"))
        try await waitFor { f.coordinator.conversation.inputs.first?.delivery == .deferred }
        let pending = try await f.runtime.call("pending_inputs")
        XCTAssertEqual(pending["inputs"]?.arrayValue?.count, 0)
        let input = try XCTUnwrap(f.coordinator.conversation.inputs.first)
        XCTAssertEqual(input.id, "admission-race")
        XCTAssertNil(input.speakerID); XCTAssertNil(input.speakerStatus); XCTAssertNil(input.runtimeSessionID)
        XCTAssertEqual(input.origin, .native); XCTAssertEqual(input.recipient, .maltose)
        XCTAssertNil(f.coordinator.conversation.issue)
        XCTAssertNil(f.adapter.connection.processID); XCTAssertEqual(f.store.tasks.count, 0)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.speaker == .user }.count, 1)
        try await stop(f)
    }

    func testVoiceHandbackUsesRuntimeVerificationWithoutReclassifyingItAsNativeText() async throws {
        let f = try fixture(routedVoice: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.history.sessions.first?.messages.contains { $0.text.contains("已保留語音來源與當次驗證身分") } == true }
        let input = try XCTUnwrap(f.coordinator.conversation.inputs.first { $0.id == "runtime-voice" })
        XCTAssertEqual(input.delivery, .accepted)
        XCTAssertEqual(input.origin, .voice); XCTAssertEqual(input.speakerID, "owner"); XCTAssertEqual(input.speakerStatus, "identified")
        XCTAssertNotNil(input.runtimeSessionID)
        XCTAssertEqual(f.runtime.autonomy?.state, .active)
        XCTAssertEqual(f.coordinator.conversation.recipient, .maltose)
        XCTAssertNil(f.adapter.connection.processID); XCTAssertEqual(f.store.tasks.count, 0)
        XCTAssertNil(f.coordinator.conversation.issue)
        try await stop(f)
    }

    func testCodexDynamicToolsUseSharedNativePanelsAndDeduplicateMutations() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native desktop panels") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize(); defer { manager.stop() }
        let original = try XCTUnwrap(manager.panels["notes"])
        let initial = Set(manager.catalog.map(\.id))
        let f = try fixture(delegatedBrain: true, panelCalls: true)
        f.runtime.onPanelCommand = { request, transfer in
            await manager.agentInterface.handle(request, fileTransfer: transfer, requiresFileTransfer: true)
        }
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        let added = manager.catalog.filter { !initial.contains($0.id) }
        XCTAssertEqual(added.count, 1)
        let panel = try XCTUnwrap(added.first)
        XCTAssertEqual(manager.panels[panel.id]?.sampleContentModel?.note, "Codex shared panel fixture")
        XCTAssertTrue(manager.panels["notes"] === original)
        let task = try XCTUnwrap(f.store.tasks.first)
        XCTAssertEqual(task.panelToolsRegistered, true)
        let responses = task.messages.filter { $0.id.hasPrefix("panel:") && $0.author == .tool }
        XCTAssertEqual(responses.count, 4)
        XCTAssertTrue(responses.allSatisfy { $0.origin == .synchronization && $0.delivery == .accepted })
        XCTAssertTrue(f.adapter.activePanelCalls.isEmpty)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        try await stop(f)
    }

    func testNativePanelConsentIsBoundToTaskRuntimeAndPausedLeaseAndNeverCreatesSpeakerIdentity() async throws {
        let f = try fixture(holdTurn: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 等待面板授權的任務", identity: "panel-consent-task"))
        try await waitFor { f.store.tasks.first?.activeTurnID != nil && f.store.tasks.first?.pendingOperation == nil }
        let id = try XCTUnwrap(f.coordinator.conversation.activeTaskID)
        let runtimeID = try XCTUnwrap(f.runtime.sessionID), lease = try XCTUnwrap(f.runtime.autonomy?.leaseID)
        XCTAssertFalse(f.coordinator.hasPanelContextConsent(for: id, lease: lease))
        XCTAssertThrowsError(try f.coordinator.setPanelContextConsent(for: UUID(), runtimeSessionID: runtimeID, leaseID: lease, allowed: true))
        XCTAssertThrowsError(try f.coordinator.setPanelContextConsent(for: id, runtimeSessionID: "old-runtime", leaseID: lease, allowed: true))
        XCTAssertThrowsError(try f.coordinator.setPanelContextConsent(for: id, runtimeSessionID: runtimeID, leaseID: "old-lease", allowed: true))
        try f.coordinator.setPanelContextConsent(for: id, runtimeSessionID: runtimeID, leaseID: lease, allowed: true)
        XCTAssertTrue(f.coordinator.hasPanelContextConsent(for: id, lease: lease))
        XCTAssertNil(f.store.task(id)?.ownerSpeakerID)
        try f.coordinator.setPanelContextConsent(for: id, runtimeSessionID: runtimeID, leaseID: lease, allowed: false)
        XCTAssertFalse(f.coordinator.hasPanelContextConsent(for: id, lease: lease))
        try f.coordinator.setPanelContextConsent(for: id, runtimeSessionID: runtimeID, leaseID: lease, allowed: true)
        f.coordinator.stopTask()
        try await waitFor { f.coordinator.conversation.stopRequested == false }
        XCTAssertTrue(f.coordinator.submit("@maltose 先交回討論", identity: "panel-consent-handback"))
        try await waitFor { f.runtime.autonomy?.state == .active }
        XCTAssertFalse(f.coordinator.hasPanelContextConsent(for: id, lease: f.runtime.autonomy?.leaseID))
        XCTAssertThrowsError(try f.coordinator.setPanelContextConsent(for: id, runtimeSessionID: runtimeID, leaseID: lease, allowed: true))
        try await stop(f)
    }

    func testHandbackStopsDetachedCodexBackgroundProcessBeforeResumingMain() async throws {
        let f = try fixture(background: true)
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 背景程序清理 fixture", identity: "background-task"))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        let text = try String(contentsOf: f.directory.appendingPathComponent("background.pid"), encoding: .utf8)
        let pid = try XCTUnwrap(Int32(text))
        XCTAssertEqual(Darwin.kill(pid, 0), 0)
        XCTAssertNotEqual(Darwin.getpgid(pid), f.adapter.connection.processID, "Fixture must escape ordinary process-group cleanup")
        XCTAssertTrue(f.coordinator.submit("@maltose 已確認，交回主 Agent", identity: "background-handback"))
        try await waitFor { f.runtime.autonomy?.state == .active && f.coordinator.conversation.phase == .maltoseActive }
        XCTAssertNotEqual(Darwin.kill(pid, 0), 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.directory.appendingPathComponent("background-cleaned").path))
        XCTAssertTrue(f.store.tasks.first?.messages.contains { $0.id.hasPrefix("background-clean:") && $0.origin == .synchronization } == true)
        XCTAssertNil(f.adapter.connection.processID)
        try await stop(f)
    }

    func testApplicationShutdownCleansDetachedBackgroundProcessInItsOwnedThread() async throws {
        let f = try fixture(background: true)
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 退出清理 fixture", identity: "shutdown-background-task"))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        let pid = try XCTUnwrap(Int32(try String(contentsOf: f.directory.appendingPathComponent("background.pid"), encoding: .utf8)))
        XCTAssertEqual(Darwin.kill(pid, 0), 0)
        await withCheckedContinuation { continuation in f.coordinator.shutdown { continuation.resume() } }
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertNotEqual(Darwin.kill(pid, 0), 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.directory.appendingPathComponent("background-cleaned").path))
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        try await stop(f)
    }

    func testCleanupAcknowledgementCannotResumeMainWhileBackgroundProcessIsStillListed() async throws {
        let f = try fixture(stubbornBackground: true)
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 無法確認清理的 fixture", identity: "stubborn-background-task"))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertTrue(f.coordinator.submit("@maltose 不能先恢復的意圖", identity: "stubborn-handback"))
        try await waitFor { f.coordinator.conversation.issue != nil }
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertNotNil(f.adapter.connection.processID)
        XCTAssertEqual(f.coordinator.conversation.inputs.first { $0.id == "stubborn-handback" }?.delivery, .queued)
        XCTAssertFalse(f.store.tasks.first?.messages.contains { $0.id.hasPrefix("background-clean:") } == true)
        try await stop(f)
    }

    func testAuthenticatedCodexBackgroundTerminalIsStoppedBeforeMainHandback() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_CODEX_LIVE_TESTS"] == "1" else { throw XCTSkip("Requires explicit live Codex opt-in") }
        let f = try fixture(liveCodex: true)
        var interactions: [String] = []
        f.coordinator.onInteraction = { _, request in interactions.append(request.method) }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("""
        @codex 這是背景終端清理驗收，僅操作目前隔離 worktree。用支援短時間 yield 的終端工具啟動一個 Python 程序，
        將自己的 PID 寫入 background.pid，再 sleep 300 秒。讓該程序繼續執行並立即回報；不要等待五分鐘，也不要自行停止它。
        主機會在你的回報後驗證它仍存活，再測試交回 Maltose 時清理。不要修改其他檔案，不要用 shell 的 & 脫離工具的程序管理。
        確認工具回傳一個仍在執行的 session/process ID 後，就可回報 kind=completed，summary 說明這次只驗收背景程序啟動。
        """, identity: "live-background-task"))
        try await waitFor(seconds: 180) { f.coordinator.conversation.phase == .awaitingUserIntent || f.coordinator.conversation.issue != nil || !interactions.isEmpty }
        XCTAssertTrue(interactions.isEmpty, "Fixture must not automatically approve requests")
        XCTAssertNil(f.coordinator.conversation.issue)
        let task = try XCTUnwrap(f.store.tasks.first)
        let terminals = try await f.adapter.backgroundTerminals(task.id)
        XCTAssertFalse(terminals.isEmpty, "A reported running process must be tracked by the installed app-server")
        let rawPID = try String(contentsOf: URL(fileURLWithPath: task.worktreePath).appendingPathComponent("background.pid"), encoding: .utf8)
        let pid = try XCTUnwrap(Int32(rawPID.trimmingCharacters(in: .whitespacesAndNewlines)))
        XCTAssertEqual(Darwin.kill(pid, 0), 0)
        XCTAssertTrue(f.coordinator.submit("@maltose 停止本次背景驗收程序並交回", identity: "live-background-handback"))
        try await waitFor(seconds: 30) { f.coordinator.conversation.phase == .maltoseActive || f.coordinator.conversation.issue != nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        XCTAssertEqual(f.runtime.autonomy?.state, .active)
        XCTAssertNotEqual(Darwin.kill(pid, 0), 0)
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertTrue(f.store.task(task.id)?.messages.contains { $0.id.hasPrefix("background-clean:") } == true)
        try await waitFor { f.history.sessions.first?.messages.contains { $0.speaker == .assistant && $0.text.contains("停止本次背景驗收程序並交回") } == true }
        let previousTurn = f.coordinator.conversation.lastReportedTurnID
        XCTAssertTrue(f.coordinator.submit("@codex 再次以相同方式啟動新的背景 Python 程序，覆寫 background.pid 為新 PID，仍 sleep 300 秒並保持由終端工具管理。這次主機要驗證 App 退出時清理；啟動成功後立即回報 completed，不要自行停止或等待。", identity: "live-background-restart"))
        try await waitFor(seconds: 180) {
            f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.lastReportedTurnID != previousTurn
                || f.coordinator.conversation.issue != nil || !interactions.isEmpty
        }
        XCTAssertNil(f.coordinator.conversation.issue); XCTAssertTrue(interactions.isEmpty)
        XCTAssertEqual(f.store.tasks.count, 1)
        XCTAssertEqual(f.store.task(task.id)?.worktreePath, task.worktreePath)
        XCTAssertEqual(f.store.task(task.id)?.threadID, task.threadID)
        let nextPID = try XCTUnwrap(Int32(try String(contentsOf: URL(fileURLWithPath: task.worktreePath).appendingPathComponent("background.pid"), encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)))
        XCTAssertNotEqual(nextPID, pid); XCTAssertEqual(Darwin.kill(nextPID, 0), 0)
        let nextTerminals = try await f.adapter.backgroundTerminals(task.id)
        XCTAssertFalse(nextTerminals.isEmpty)
        await withCheckedContinuation { continuation in f.coordinator.shutdown { continuation.resume() } }
        XCTAssertNotEqual(Darwin.kill(nextPID, 0), 0)
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertEqual(f.store.task(task.id)?.messages.filter { $0.id.hasPrefix("background-clean:") }.count, 2)
        try await stop(f)
    }

    func testAuthenticatedCodexActuallyCallsSharedPanelToolsWithoutChangingRepository() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1",
              ProcessInfo.processInfo.environment["MALTOSE_CODEX_LIVE_TESTS"] == "1" else {
            throw XCTSkip("Requires native desktop and explicit live Codex opt-in")
        }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize(); defer { manager.stop() }
        let initial = Set(manager.catalog.map(\.id)), marker = "Live Codex panel " + UUID().uuidString
        let f = try fixture(liveCodex: true)
        var interactions: [String] = []
        f.coordinator.onInteraction = { _, request in interactions.append(request.method) }
        f.runtime.onPanelCommand = { request, transfer in
            await manager.agentInterface.handle(request, fileTransfer: transfer, requiresFileTransfer: true)
        }
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("""
        @codex 這次只驗證 Maltose 共用面板工具。必須實際呼叫 maltose_create_panel，kind=notes；
        再用回傳的 panelID 呼叫 maltose_notes_set_text，文字精確設定為「\(marker)」。
        不要修改任何專案檔案，也不要用 shell 代替面板工具。只有兩項工具都成功才回報 completed；
        若工具不可用，回報 needs_input 並說明，不能宣稱已完成。
        """, identity: "live-panel-input"))
        try await waitFor(seconds: 180) {
            f.coordinator.conversation.phase == .awaitingUserIntent || f.coordinator.conversation.issue != nil || !interactions.isEmpty
        }
        XCTAssertTrue(interactions.isEmpty, "Live fixture must not silently approve human requests")
        XCTAssertNil(f.coordinator.conversation.issue)
        XCTAssertEqual(f.coordinator.conversation.phase, .awaitingUserIntent)
        let added = manager.catalog.filter { !initial.contains($0.id) }
        XCTAssertEqual(added.count, 1)
        let panel = try XCTUnwrap(added.first)
        XCTAssertEqual(manager.panels[panel.id]?.sampleContentModel?.note, marker)
        let task = try XCTUnwrap(f.store.tasks.first)
        XCTAssertEqual(task.panelToolsRegistered, true)
        let responses = task.messages.filter { $0.id.hasPrefix("panel:") && $0.author == .tool }
        XCTAssertEqual(responses.count, 2)
        for response in responses {
            let value = try JSONDecoder().decode(UserViewValue.self, from: Data(response.content.utf8))
            XCTAssertEqual(value["success"], .boolean(true)); XCTAssertEqual(response.delivery, .accepted)
        }
        XCTAssertEqual(task.workspaceChanges?["changes"]?.arrayValue?.count, 0)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        try await stop(f)
    }

    func testSharedConversationHandoffFollowupCompletionAndFreshIntentUseSameThreadAndWorktree() async throws {
        let f = try fixture(); defer { try? FileManager.default.removeItem(at: f.directory) }
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("先聊天", identity: "main-input"))
        try await waitFor { f.history.sessions.first?.messages.contains { $0.speaker == .assistant && $0.text.contains("先聊天") } == true }
        XCTAssertTrue(f.coordinator.submit("@codex 第一項要求", identity: "codex-first"))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        let id = try XCTUnwrap(f.coordinator.conversation.activeTaskID), task = try XCTUnwrap(f.store.task(id))
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(task.status, .awaitingReview)
        XCTAssertEqual(task.threadID, "session-thread")
        XCTAssertNotEqual(task.worktreePath, task.repositoryPath)
        XCTAssertNotNil(task.workspaceChanges)
        XCTAssertTrue(f.history.sessions.first?.messages.contains { $0.speaker == .codex && $0.text == "完成 第一項要求" } == true)
        XCTAssertTrue(f.coordinator.submit("追加要求", identity: "codex-followup"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.store.tasks.count, 1)
        XCTAssertEqual(f.store.task(id)?.worktreePath, task.worktreePath)
        XCTAssertEqual(f.store.task(id)?.messages.filter { $0.author == .user }.map(\.content), ["第一項要求", "追加要求"])
        let messages = try XCTUnwrap(f.history.sessions.first?.messages)
        XCTAssertEqual(f.history.sessions.count, 1)
        XCTAssertEqual(messages.filter { $0.origin == "maltose-coordination" }.count, 2)
        XCTAssertEqual(messages.filter { $0.speaker == .user }.count, 3)
        XCTAssertEqual(try String(contentsOf: URL(fileURLWithPath: task.repositoryPath).appendingPathComponent("fixture.txt"), encoding: .utf8), "baseline\n")
        XCTAssertTrue(f.coordinator.submit("@maltose 新的方向", identity: "fresh-main"))
        try await waitFor { f.coordinator.conversation.phase == .maltoseActive && f.runtime.autonomy?.state == .active }
        try await waitFor { f.history.sessions.first?.messages.contains { $0.speaker == .assistant && $0.text.contains("新的方向") } == true }
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertEqual(f.store.task(id)?.status, .completed)
        // Replayed outbox input cannot switch the recipient back or execute the task twice.
        XCTAssertTrue(f.coordinator.submit("@codex 第一項要求", identity: "codex-first"))
        XCTAssertEqual(f.coordinator.conversation.recipient, .maltose)
        XCTAssertEqual(f.coordinator.conversation.inputs.count, 4)
        try await stop(f)
    }

    func testUnidentifiedVoiceAndOldOutboxInputsRemainReviewableWithoutChangingControl() async throws {
        let f = try fixture(); defer { try? FileManager.default.removeItem(at: f.directory) }
        XCTAssertTrue(f.coordinator.submit("@codex 未辨識的聲音", origin: .voice, identity: "unknown-voice", speakerStatus: "unknown"))
        XCTAssertEqual(f.coordinator.conversation.recipient, .maltose)
        XCTAssertEqual(f.coordinator.conversation.phase, .maltoseActive)
        XCTAssertEqual(f.coordinator.deferredInputs.map(\.id), ["unknown-voice"])
        XCTAssertTrue(f.coordinator.submit("@codex 舊的輸入", identity: "old-input", deferred: true))
        XCTAssertEqual(f.coordinator.conversation.recipient, .maltose)
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertFalse(f.coordinator.submit("@codex 不同內容", identity: "old-input", deferred: true))
        XCTAssertEqual(f.coordinator.conversation.inputs.count, 2)
        XCTAssertTrue(f.coordinator.submit("@codex 缺少身分的標記", origin: .voice, identity: "missing-voice-id", speakerStatus: "identified"))
        XCTAssertEqual(f.coordinator.conversation.recipient, .maltose)
        XCTAssertEqual(f.coordinator.deferredInputs.last?.id, "missing-voice-id")
        try await stop(f)
    }

    func testSecretQuestionRejectsComposerBeforePersistenceAndSecureResponseIsRedacted() async throws {
        let f = try fixture(questionKind: "secret")
        var request: CodexServerRequest?, issues: [String] = []
        f.coordinator.onInteraction = { _, value in request = value }
        f.coordinator.onIssue = { issues.append($0) }
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 開始秘密問題 fixture", identity: "secret-task"))
        try await waitFor { request != nil }
        let taskID = try XCTUnwrap(f.coordinator.conversation.activeTaskID)
        XCTAssertFalse(f.coordinator.submit("fixture-secret-sentinel", identity: "unsafe-secret"))
        XCTAssertFalse(f.coordinator.conversation.inputs.contains { $0.id == "unsafe-secret" })
        XCTAssertFalse(f.history.sessions.flatMap(\.messages).contains { $0.text.contains("fixture-secret-sentinel") })
        XCTAssertTrue(issues.last?.contains("安全輸入欄") == true)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.store.task(taskID)?.status, .waitingForUser)
        XCTAssertTrue(f.coordinator.respond(to: try XCTUnwrap(request), result: .success(.object([
            "answers": .object(["answer": .object(["answers": .strings(["fixture-secret-sentinel"])])])]))))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.directory.appendingPathComponent("question-answered").path))
        let task = try XCTUnwrap(f.store.task(taskID))
        XCTAssertTrue(task.messages.contains { $0.content.contains("已隱藏的回答") })
        XCTAssertFalse(task.messages.contains { $0.content.contains("fixture-secret-sentinel") })
        let files = try XCTUnwrap(FileManager.default.enumerator(at: f.directory, includingPropertiesForKeys: [.isRegularFileKey]))
        for case let file as URL in files.allObjects where (try? file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true {
            XCTAssertFalse((try Data(contentsOf: file)).range(of: Data("fixture-secret-sentinel".utf8)) != nil, file.lastPathComponent)
        }
    }

    func testPublicQuestionAcceptsComposerAnswerInSameTurnWithoutStartingAnotherTurn() async throws {
        let f = try fixture(questionKind: "public")
        var asked = false
        f.coordinator.onInteraction = { _, _ in asked = true }
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 開始公開問題 fixture", identity: "public-task"))
        try await waitFor { asked }
        XCTAssertTrue(f.coordinator.submit("公開問題的回答", identity: "public-answer"))
        try await waitFor { f.coordinator.conversation.issue != nil || f.coordinator.conversation.phase == .awaitingUserIntent }
        XCTAssertNil(f.coordinator.conversation.issue, (try? String(contentsOf: f.directory.appendingPathComponent("codex.log"), encoding: .utf8)) ?? "")
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.store.tasks.count, 1)
        XCTAssertEqual(f.coordinator.conversation.lastReportedTurnID, "turn-1")
        XCTAssertTrue(f.coordinator.conversation.inputs.contains { $0.id == "public-answer" && $0.delivery == .accepted })
        XCTAssertTrue(f.store.tasks.first?.messages.contains { $0.id == "public-answer" && $0.content == "公開問題的回答" } == true)
    }

    func testFailedTurnSynchronizesActualCauseWithoutCompletionQuestionOrAutomaticResume() async throws {
        let f = try fixture(failedTurn: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 失敗 fixture", identity: "failed-task"))
        let observation = f.directory.appendingPathComponent("config/collaboration/observation.json")
        try await waitFor {
            guard let data = try? Data(contentsOf: observation), let record = try? JSONDecoder().decode(UserViewValue.self, from: data) else { return false }
            return record["failure"] == .string("fixture provider unavailable")
        }
        XCTAssertEqual(f.store.tasks.first?.status, .failed)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertNil(f.coordinator.conversation.pendingQuestionID)
        XCTAssertFalse(f.history.sessions.flatMap(\.messages).contains { $0.origin == "maltose-coordination" })
        XCTAssertTrue(f.coordinator.submit("重試已失敗的工作", identity: "failure-retry"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertNil(f.store.tasks.first?.failureMessage)
        let successful = try JSONDecoder().decode(UserViewValue.self, from: Data(contentsOf: observation))
        XCTAssertEqual(successful["failure"], .null)
        XCTAssertEqual(successful["status"], .string("awaitingReview"))
    }

    func testExplicitTaskSelectionKeepsThreadWorktreeAndDoesNotInventACompletionOrSend() throws {
        let f = try fixture()
        let conversationID = f.coordinator.conversation.id
        let first = CodexTaskRecord(conversationID: conversationID, repositoryPath: "/tmp/first-repository", worktreePath: "/tmp/first-worktree",
            delegation: .init(objective: "第一項要求", constraints: [], acceptanceCriteria: ["第一項驗收"]))
        let second = CodexTaskRecord(conversationID: conversationID, repositoryPath: "/tmp/second-repository", worktreePath: "/tmp/second-worktree",
            delegation: .init(objective: "第二項要求", constraints: [], acceptanceCriteria: ["第二項驗收"]))
        let foreign = CodexTaskRecord(conversationID: "another-conversation", repositoryPath: "/tmp/foreign", worktreePath: "/tmp/foreign-worktree",
            delegation: .init(objective: "另一個對話的要求", constraints: [], acceptanceCriteria: []))
        for record in [first, second, foreign] { try f.store.create(record) }
        try f.store.update(first.id) { $0.threadID = "first-thread"; $0.lastFinishedTurnID = "first-result"; $0.status = .awaitingReview }
        try f.store.update(second.id) { $0.threadID = "second-thread"; $0.lastFinishedTurnID = "second-result"; $0.status = .awaitingReview }
        XCTAssertEqual(Set(f.coordinator.taskChoices.map(\.id)), Set([first.id, second.id]))
        f.coordinator.selectTask(second.id)
        XCTAssertEqual(f.coordinator.conversation.activeTaskID, second.id)
        XCTAssertEqual(f.coordinator.conversation.worktreePath, second.worktreePath)
        XCTAssertEqual(f.coordinator.conversation.lastReportedTurnID, "second-result")
        XCTAssertNil(f.coordinator.conversation.pendingQuestionID)
        XCTAssertTrue(f.coordinator.conversation.inputs.isEmpty)
        XCTAssertNil(f.adapter.connection.processID)
        f.coordinator.selectTask(foreign.id)
        XCTAssertEqual(f.coordinator.conversation.activeTaskID, second.id)
        XCTAssertNotNil(f.coordinator.conversation.issue)
        try f.store.update(second.id) { $0.activeTurnID = "active-second"; $0.status = .running }
        f.coordinator.selectTask(first.id)
        XCTAssertEqual(f.coordinator.conversation.activeTaskID, second.id)
        try f.store.update(second.id) { $0.activeTurnID = nil; $0.status = .interrupted }
        f.coordinator.selectTask(first.id)
        XCTAssertEqual(f.coordinator.conversation.activeTaskID, first.id)
        XCTAssertEqual(f.coordinator.conversation.worktreePath, first.worktreePath)
        XCTAssertEqual(f.store.task(second.id)?.threadID, "second-thread")
        XCTAssertTrue(f.store.tasks.allSatisfy { $0.messages.isEmpty })
    }

    func testSavedCompletionQuestionReplaysAsOneMessageAndNeverResumesAutonomy() async throws {
        let f = try fixture(); defer { try? FileManager.default.removeItem(at: f.directory) }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 可恢復成果", identity: "recovery-input"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-1" && f.coordinator.conversation.pendingQuestionID == nil }
        let id = try XCTUnwrap(f.coordinator.conversation.activeTaskID)
        let promptID = "maltose-intent:\(id.uuidString):turn-1"
        try f.store.updateConversation(f.coordinator.conversation.id) { $0.pendingQuestionID = promptID; $0.issue = "Fixture lost acknowledgement" }
        f.coordinator.retry()
        try await waitFor { f.coordinator.conversation.pendingQuestionID == nil && f.coordinator.conversation.issue == nil }
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 1)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.coordinator.conversation.phase, .awaitingUserIntent)
        XCTAssertEqual(f.store.task(id)?.messages.filter { $0.author == .user }.count, 1)
        try await stop(f)
    }

    func testDelegationAndUserDirectFollowupPreserveAuthorAndUseOneTask() async throws {
        let f = try fixture(); defer { try? FileManager.default.removeItem(at: f.directory) }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        let id = UUID(), messageID = "delegation-input"
        let delegation = CodexDelegation(objective: "模型委派要求", constraints: ["保留修改"], acceptanceCriteria: ["通過測試"], context: "專案現況")
        let raw = try JSONSerialization.jsonObject(with: JSONEncoder().encode(delegation))
        let event: [String: Any] = ["schemaVersion": 1, "sessionID": "delegation-fixture", "sequence": 1,
            "event": ["type": "input_routed", "timestamp": "fixture", "payload": ["kind": "codex_delegation", "messageID": messageID,
                "taskID": id.uuidString, "conversationID": f.coordinator.conversation.id, "runtimeSessionID": "delegation-fixture",
                "source": "delegation", "author": "maltose", "content": String(decoding: try JSONEncoder().encode(delegation), as: UTF8.self),
                "speaker": ["userID": "owner", "status": "identified"], "delegation": raw]]]
        try f.coordinator.receiveRuntime(JSONSerialization.data(withJSONObject: event))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.coordinator.conversation.activeTaskID, id)
        XCTAssertEqual(f.store.task(id)?.delegation, delegation)
        XCTAssertEqual(f.store.task(id)?.ownerSpeakerID, "owner")
        XCTAssertEqual(f.store.task(id)?.messages.first?.author, .maltose)
        XCTAssertEqual(f.store.task(id)?.messages.first?.origin, .delegation)
        XCTAssertTrue(f.coordinator.submit("@codex 人類追加要求", identity: "human-followup"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.store.tasks.count, 1)
        XCTAssertEqual(f.store.task(id)?.messages.filter { $0.author == .user }.map(\.content), ["人類追加要求"])
        try await stop(f)
    }

    func testThreadCreationBindingCrashGapRecoversWithoutAnotherThreadOrWorkspace() async throws {
        let f = try fixture(); defer { try? FileManager.default.removeItem(at: f.directory) }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 原任務", identity: "before-gap"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-1" && f.coordinator.conversation.pendingQuestionID == nil }
        let id = try XCTUnwrap(f.coordinator.conversation.activeTaskID), task = try XCTUnwrap(f.store.task(id))
        // Simulate the durable thread result preceding the conversation binding write.
        try f.store.updateConversation(f.coordinator.conversation.id) { $0.activeTaskID = nil; $0.issue = "fixture crash gap" }
        f.coordinator.retry()
        try await waitFor { f.coordinator.conversation.activeTaskID == id && f.coordinator.conversation.issue == nil }
        XCTAssertTrue(f.coordinator.submit("續做原任務", identity: "after-gap"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.store.tasks.count, 1); XCTAssertEqual(f.store.task(id)?.threadID, task.threadID)
        XCTAssertEqual(f.store.task(id)?.worktreePath, task.worktreePath)
        try await stop(f)
    }

    func testFullProcessAndStoreRestartPreservesRecipientAndReattachesBeforeFollowup() async throws {
        let f = try fixture()
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 重啟前要求", identity: "before-restart"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-1" && f.coordinator.conversation.pendingQuestionID == nil }
        let conversationID = f.coordinator.conversation.id
        let id = try XCTUnwrap(f.coordinator.conversation.activeTaskID), original = try XCTUnwrap(f.store.task(id))
        try await stop(f)
        let store = CodexTaskStore(url: f.directory.appendingPathComponent("tasks.json"))
        let runtime = RuntimeSupervisor(), adapter = try CodexAdapter(connection: CodexConnection(), store: store)
        let coordinator = try AgentSessionCoordinator(runtime: runtime, codex: adapter, launchCodex: { f.codexConfig })
        try f.history.enableLiveStorage(at: f.directory.appendingPathComponent("history.jsonl"))
        coordinator.emit = { try f.history.applyRuntimeEvent($0) }
        runtime.onEvent = { [weak coordinator] data in try? coordinator?.receiveRuntime(data) }
        runtime.onStateChange = { [weak coordinator] state in if state == .ready { coordinator?.runtimeReady() } }
        addTeardownBlock { @MainActor in
            await withCheckedContinuation { continuation in coordinator.shutdown { continuation.resume() } }
            await withCheckedContinuation { continuation in runtime.stop { continuation.resume() } }
            store.close(); f.history.closeLiveStorage()
        }
        try runtime.start(configuration: f.runtimeConfig)
        try await waitFor { runtime.state == .ready && runtime.autonomy?.state == .paused }
        XCTAssertEqual(coordinator.conversation.id, conversationID)
        XCTAssertEqual(coordinator.conversation.recipient, .codex)
        XCTAssertNil(adapter.connection.processID)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 1)
        XCTAssertTrue(coordinator.submit("重啟後追加", identity: "after-restart"))
        try await waitFor { coordinator.conversation.lastReportedTurnID == "turn-2" && coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(store.tasks.count, 1)
        XCTAssertEqual(store.task(id)?.threadID, original.threadID)
        XCTAssertEqual(store.task(id)?.worktreePath, original.worktreePath)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 2)
        XCTAssertEqual(runtime.autonomy?.state, .paused)
        let journal = try String(contentsOf: f.directory.appendingPathComponent("history.jsonl"), encoding: .utf8)
        let sequences = try journal.split(separator: "\n").compactMap { line -> Int? in
            let event = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
            return event?["sessionID"] as? String == "coordination:\(conversationID)" ? event?["sequence"] as? Int : nil
        }
        XCTAssertGreaterThan(sequences.count, 2)
        XCTAssertTrue(zip(sequences, sequences.dropFirst()).allSatisfy { $0 < $1 }, "Coordination sequence must increase across process/store restart")
        XCTAssertGreaterThanOrEqual(coordinator.conversation.sequence, try XCTUnwrap(sequences.last))
    }

    func testStopDuringPendingStartWaitsForAcknowledgementAndNeverDispatchesQueuedFollowup() async throws {
        let f = try fixture(holdTurn: true)
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 正在開始的工作", identity: "starting-input"))
        try await waitFor { f.store.tasks.first?.activeTurnID != nil && f.store.tasks.first?.pendingOperation?.kind == .startTurn }
        XCTAssertTrue(f.coordinator.submit("停止時不能繼續送出的追加", identity: "queued-followup"))
        f.coordinator.stopTask()
        XCTAssertEqual(f.coordinator.conversation.stopRequested, true)
        try await waitFor { f.store.tasks.first?.status == .interrupted && f.coordinator.conversation.stopRequested == false }
        XCTAssertEqual(f.store.tasks.first?.messages.filter { $0.author == .user }.count, 1)
        XCTAssertEqual(f.coordinator.deferredInputs.map(\.id), ["queued-followup"])
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 0)
        XCTAssertTrue(f.coordinator.submit("@maltose 停止後的新方向", identity: "after-stop"))
        try await waitFor { f.coordinator.conversation.phase == .maltoseActive && f.runtime.autonomy?.state == .active }
        XCTAssertEqual(f.store.tasks.first?.status, .interrupted)
    }

    func testTranscriptFailureAfterDurableInputDoesNotInviteDuplicateSendAndRetryRepairsProjection() async throws {
        let f = try fixture()
        f.coordinator.emit = { _ in throw CodexTaskStoreError.unavailable("fixture transcript unavailable") }
        XCTAssertTrue(f.coordinator.submit("@codex 已保存但尚未顯示", identity: "saved-before-projection"))
        XCTAssertEqual(f.coordinator.conversation.inputs.count, 1)
        XCTAssertNotNil(f.coordinator.conversation.issue)
        f.coordinator.emit = { try f.history.applyRuntimeEvent($0) }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        f.coordinator.retry()
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.speaker == .user }.map(\.text), ["已保存但尚未顯示"])
        XCTAssertEqual(f.store.tasks.first?.messages.filter { $0.author == .user }.count, 1)
    }

    func testCompletionRPCReplyCannotAcknowledgeQuestionBeforeTranscriptIsSaved() async throws {
        let f = try fixture()
        f.coordinator.emit = { data in
            let envelope = try JSONDecoder().decode(ConversationHistoryModel.RuntimeEnvelope.self, from: data)
            if envelope.event.payload["source"] == .string("maltose-coordination") {
                throw CodexTaskStoreError.unavailable("fixture question persistence failure")
            }
            try f.history.applyRuntimeEvent(data)
        }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 成果確認必須保存", identity: "question-recovery"))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.issue != nil }
        XCTAssertNotNil(f.coordinator.conversation.pendingQuestionID)
        XCTAssertNil(f.coordinator.conversation.lastDeliveredQuestionID)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 0)
        f.coordinator.emit = { try f.history.applyRuntimeEvent($0) }
        f.coordinator.retry()
        try await waitFor { f.coordinator.conversation.pendingQuestionID == nil && f.coordinator.conversation.issue == nil }
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 1)
        XCTAssertNotNil(f.coordinator.conversation.lastDeliveredQuestionID)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
    }

    func testNewHumanRequirementDuringReviewSuppressesStaleQuestionAndReviewsLatestTurn() async throws {
        let f = try fixture(delegatedBrain: true, holdReview: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { FileManager.default.fileExists(atPath: f.directory.appendingPathComponent("review-entered").path) }
        XCTAssertNotNil(f.coordinator.conversation.pendingQuestionID)
        XCTAssertTrue(f.coordinator.submit("@codex 人類追加需求：改用 TSV", identity: "during-review"))
        XCTAssertNil(f.coordinator.conversation.pendingQuestionID)
        XCTAssertTrue(FileManager.default.createFile(atPath: f.directory.appendingPathComponent("review-release").path, contents: Data()))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil }
        let questions = f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" } ?? []
        XCTAssertEqual(questions.count, 1)
        XCTAssertFalse(questions.contains { $0.text.contains("第一次過期確認") })
        XCTAssertTrue(questions.first?.text.contains("主 Agent 已檢查協作成果") == true)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(try String(contentsOf: f.directory.appendingPathComponent("review-count"), encoding: .utf8), "2")
        try await stop(f)
    }

    func testConfiguredMainModelReviewsHumanCodexRequirementChangesAndAsksWithoutResuming() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_MAIN_LIVE_TESTS"] == "1" else { throw XCTSkip("Requires explicit configured Main model opt-in") }
        let f = try fixture(delegatedBrain: true, liveMain: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor(seconds: 120) { f.coordinator.conversation.lastReportedTurnID == "turn-1" && f.coordinator.conversation.pendingQuestionID == nil || f.coordinator.conversation.issue != nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        XCTAssertTrue(f.coordinator.submit("@codex 人類追加需求：匯出格式改為 TSV，保留時區 UTC+08:00，而且不要自動合併。", identity: "main-live-added-intent"))
        try await waitFor(seconds: 120) { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil || f.coordinator.conversation.issue != nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        let questions = f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" } ?? []
        XCTAssertEqual(questions.count, 2)
        let latest = try XCTUnwrap(questions.last?.text)
        XCTAssertTrue(latest.contains("TSV")); XCTAssertTrue(latest.contains("UTC+08:00")); XCTAssertTrue(latest.contains("合併"))
        XCTAssertTrue(latest.contains("？") || latest.contains("?"))
        let reviews = try FileManager.default.contentsOfDirectory(at: f.runtimeConfig.directory.appendingPathComponent("collaboration/reviews"), includingPropertiesForKeys: nil)
        XCTAssertEqual(reviews.count, 2)
        let values = try reviews.map { try JSONDecoder().decode(UserViewValue.self, from: Data(contentsOf: $0)) }
        XCTAssertTrue(values.allSatisfy { $0["status"] == .string("complete") && $0["result"]?["mode"] == .string("model") })
        XCTAssertTrue(values.contains { value in
            let requirements = value["result"]?["review"]?["newRequirements"]?.arrayValue?.compactMap(\.stringValue).joined(separator: " ") ?? ""
            return requirements.contains("TSV") && requirements.contains("UTC+08:00") && requirements.contains("合併")
        })
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.store.tasks.first?.status, .awaitingReview)
        XCTAssertEqual(f.coordinator.conversation.phase, .awaitingUserIntent)
        try await stop(f)
    }

    func testNativeComposerCanAskMainToDelegateWithoutClaimingVoiceIdentity() async throws {
        let f = try fixture(delegatedBrain: true, delegateOnStartup: false)
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("請委派這項開發工作", identity: "native-delegation-request"))
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        let task = try XCTUnwrap(f.store.tasks.first)
        XCTAssertNil(task.ownerSpeakerID)
        XCTAssertEqual(task.messages.first?.author, .maltose)
        XCTAssertEqual(task.messages.first?.origin, .delegation)
        let input = try XCTUnwrap(f.coordinator.conversation.inputs.first { $0.origin == .delegation })
        XCTAssertNil(input.speakerID); XCTAssertEqual(input.speakerStatus, "unknown")
        XCTAssertEqual(f.coordinator.conversation.inputs.first { $0.id == "native-delegation-request" }?.delivery, .accepted)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        try await stop(f)
    }

    func testConfiguredMainModelActuallyDelegatesTypedDevelopmentRequestToAuthorizedRepository() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_MAIN_LIVE_TESTS"] == "1" else { throw XCTSkip("Requires explicit configured Main model opt-in") }
        let f = try fixture(delegatedBrain: true, liveMain: true, delegateOnStartup: false, liveDelegation: true)
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("請立即把這項開發工作交給 Codex：在已授權的隔離 fixture 專案加入 TSV 匯出驗證。限制是保留既有修改、不自動合併；驗收條件是執行相關測試並回報結果。我已確認此範圍並授權立即委派，不需要再詢問，也不需要個人記憶或聲紋身分。", identity: "live-native-delegation"))
        try await waitFor(seconds: 120) { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil || f.coordinator.conversation.issue != nil }
        XCTAssertNil(f.coordinator.conversation.issue)
        let task = try XCTUnwrap(f.store.tasks.first)
        XCTAssertTrue(task.delegation.objective.contains("TSV"))
        XCTAssertFalse(task.delegation.constraints.isEmpty); XCTAssertFalse(task.delegation.acceptanceCriteria.isEmpty)
        XCTAssertNil(task.ownerSpeakerID)
        XCTAssertEqual(task.messages.first?.author, .maltose)
        XCTAssertEqual(task.messages.first?.origin, .delegation)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        let questions = f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" } ?? []
        XCTAssertEqual(questions.count, 1)
        XCTAssertTrue(questions.first?.text.contains("TSV") == true)
        try await stop(f)
    }

    func testRealMainAndCodexCompleteNativeDelegationDirectFollowupReviewAndFreshIntent() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_MAIN_LIVE_TESTS"] == "1",
              ProcessInfo.processInfo.environment["MALTOSE_CODEX_LIVE_TESTS"] == "1" else {
            throw XCTSkip("Requires explicit Main and Codex live-model opt-in")
        }
        let f = try fixture(liveCodex: true, delegatedBrain: true, liveMain: true, delegateOnStartup: false, liveDelegation: true)
        var interactions: [String] = []
        f.coordinator.onInteraction = { _, request in interactions.append(request.method) }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("請立即將已授權隔離專案的這項開發工作委派給 Codex：修正 calculator.py 裡 add 的加法錯誤，執行 python3 -m unittest test_calculator 的三項測試。限制為只修正這項功能、保留 fixture.txt、不改測試、不合併回原專案。我已確認並授權這次委派，無須再次確認，這不需要個人資料或聲紋。", identity: "real-chain-main-request"))
        try await waitFor(seconds: 180) {
            f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil
                || f.coordinator.conversation.issue != nil || !interactions.isEmpty
        }
        XCTAssertNil(f.coordinator.conversation.issue); XCTAssertTrue(interactions.isEmpty)
        let task = try XCTUnwrap(f.store.tasks.first), firstTurn = task.lastFinishedTurnID
        XCTAssertNil(task.ownerSpeakerID)
        XCTAssertEqual(task.messages.first?.author, .maltose); XCTAssertEqual(task.messages.first?.origin, .delegation)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertTrue(f.coordinator.submit("@codex 人類追加需求：替 add 補上函式說明（docstring），保持原先三項測試通過，不修改測試，也不要自動合併。", identity: "real-chain-codex-followup"))
        try await waitFor(seconds: 180) {
            f.store.task(task.id)?.lastFinishedTurnID != firstTurn && f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil
                || f.coordinator.conversation.issue != nil || !interactions.isEmpty
        }
        XCTAssertNil(f.coordinator.conversation.issue); XCTAssertTrue(interactions.isEmpty)
        XCTAssertEqual(f.store.tasks.count, 1); XCTAssertEqual(f.store.task(task.id)?.threadID, task.threadID)
        XCTAssertEqual(f.store.task(task.id)?.worktreePath, task.worktreePath)
        XCTAssertEqual(f.store.task(task.id)?.messages.filter { $0.author == .user }.count, 1)
        let check = Process(); check.executableURL = f.runtimeConfig.executable
        check.arguments = ["-c", "import ast,unittest; from pathlib import Path; tree=ast.parse(Path('calculator.py').read_text()); fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='add'); assert ast.get_docstring(fn); result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName('test_calculator')); assert result.wasSuccessful()"]
        check.currentDirectoryURL = URL(fileURLWithPath: task.worktreePath)
        check.standardOutput = FileHandle.nullDevice; check.standardError = FileHandle.nullDevice
        try check.run(); check.waitUntilExit(); XCTAssertEqual(check.terminationStatus, 0)
        XCTAssertEqual(try String(contentsOf: URL(fileURLWithPath: task.repositoryPath).appendingPathComponent("calculator.py"), encoding: .utf8), "def add(a, b):\n    return a - b\n")
        let questions = f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" } ?? []
        XCTAssertEqual(questions.count, 2)
        let latest = try XCTUnwrap(questions.last?.text)
        XCTAssertTrue(latest.lowercased().contains("docstring") || latest.contains("說明") || latest.contains("文件字串"))
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        let answerCount = f.history.sessions.first?.messages.filter { $0.origin == "maltose-runtime" && $0.speaker == .assistant }.count ?? 0
        XCTAssertTrue(f.coordinator.submit("@maltose 成果已確認；請先與我討論後續規劃，先不要執行任何工具或開發動作。", identity: "real-chain-fresh-intent"))
        try await waitFor(seconds: 120) {
            (f.history.sessions.first?.messages.filter { $0.origin == "maltose-runtime" && $0.speaker == .assistant }.count ?? 0) > answerCount
                || f.coordinator.conversation.issue != nil
        }
        XCTAssertNil(f.coordinator.conversation.issue)
        XCTAssertEqual(f.runtime.autonomy?.state, .active)
        XCTAssertEqual(f.store.task(task.id)?.status, .completed)
        XCTAssertNil(f.adapter.connection.processID)
        try await stop(f)
    }

    func testIncompleteTurnStillSynchronizesLatestCodexReplyWithoutCompletionQuestion() async throws {
        let f = try fixture(reportKind: "in_progress")
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 尚未完成的回覆", identity: "in-progress-input"))
        let observation = f.runtimeConfig.directory.appendingPathComponent("collaboration/observation.json")
        try await waitFor {
            guard let data = try? Data(contentsOf: observation), let text = String(data: data, encoding: .utf8) else { return false }
            return text.contains("in_progress") && text.contains("尚未完成的回覆")
        }
        XCTAssertEqual(f.coordinator.conversation.phase, .codexDirect)
        XCTAssertEqual(f.store.tasks.first?.status, .awaitingReview)
        XCTAssertNil(f.store.tasks.first?.outcomeSummary)
        XCTAssertNil(f.coordinator.conversation.pendingQuestionID)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.history.sessions.first?.messages.filter { $0.origin == "maltose-coordination" }.count, 0)
    }

    func testAuthenticatedCodexFixesIsolatedProjectRunsTestsAndHandsBackFreshIntent() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_CODEX_LIVE_TESTS"] == "1" else { throw XCTSkip("Opt in to authenticated live Codex fixture development") }
        let f = try fixture(liveCodex: true)
        try await f.adapter.connection.start(configuration: f.codexConfig)
        guard try await f.adapter.authenticationAvailable() else { throw XCTSkip("Codex requires interactive authentication") }
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        var interactionRequired = false
        f.coordinator.onInteraction = { _, _ in interactionRequired = true }
        XCTAssertTrue(f.coordinator.submit("@codex 修正 calculator.py 的 add 函式，讓它正確相加。請實際執行 python3 -m unittest test_calculator 驗證正數、負數與零；保留測試斷言，不更動 fixture.txt，不提交 Git，不使用外部服務或安裝套件。所有要求與測試通過後才回報 completed，列出實際測試證據。", identity: "live-development"))
        try await waitFor(seconds: 180) {
            (f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil)
                || f.coordinator.conversation.issue != nil || interactionRequired || f.store.tasks.first?.status == .failed
        }
        XCTAssertFalse(interactionRequired, "Live fixture requested human interaction; no automatic approval was sent")
        XCTAssertTrue(f.coordinator.conversation.issue == nil, "Live fixture requires diagnostic review")
        XCTAssertEqual(f.coordinator.conversation.phase, .awaitingUserIntent)
        guard f.coordinator.conversation.phase == .awaitingUserIntent else { throw CodexTaskStoreError.unavailable("Live fixture did not finish; private evidence retained under .cache/codex-live") }
        let task = try XCTUnwrap(f.store.tasks.first)
        XCTAssertEqual(task.model, f.store.preferredModel)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertNotNil(task.outcomeSummary)
        XCTAssertTrue(task.messages.contains { $0.author == .tool && $0.content.contains("commandExecution") && $0.content.contains("unittest") })
        let check = Process(); check.executableURL = f.runtimeConfig.executable
        check.arguments = ["-m", "unittest", "test_calculator"]; check.currentDirectoryURL = URL(fileURLWithPath: task.worktreePath)
        check.standardOutput = FileHandle.nullDevice; check.standardError = FileHandle.nullDevice
        try check.run(); check.waitUntilExit(); XCTAssertEqual(check.terminationStatus, 0)
        XCTAssertEqual(try String(contentsOf: URL(fileURLWithPath: task.repositoryPath).appendingPathComponent("calculator.py"), encoding: .utf8), "def add(a, b):\n    return a - b\n")
        XCTAssertEqual(try String(contentsOf: URL(fileURLWithPath: task.worktreePath).appendingPathComponent("fixture.txt"), encoding: .utf8), "baseline\n")
        XCTAssertTrue(f.coordinator.submit("@maltose 已確認這次成果，接下來先討論新的方向", identity: "live-fresh-intent"))
        try await waitFor { f.coordinator.conversation.phase == .maltoseActive && f.runtime.autonomy?.state == .active }
        XCTAssertNil(f.adapter.connection.processID)
        XCTAssertEqual(f.store.task(task.id)?.status, .completed)
    }

    func testActualTaskBrainDelegatesThroughToolAndReadsHumanCodexRequirementsAfterHandback() async throws {
        let f = try fixture(delegatedBrain: true)
        try f.runtime.start(configuration: f.runtimeConfig)
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        let id = try XCTUnwrap(f.coordinator.conversation.activeTaskID)
        XCTAssertEqual(f.store.task(id)?.delegation.objective, "TaskBrain 委派工作")
        XCTAssertEqual(f.store.task(id)?.messages.first?.author, .maltose)
        XCTAssertEqual(f.store.task(id)?.ownerSpeakerID, "owner")
        XCTAssertEqual(f.runtime.autonomy?.inFlight, 0)
        XCTAssertTrue(f.coordinator.submit("@codex 其他已辨識者的指令", origin: .voice, identity: "other-voice-owner", speakerID: "other", speakerStatus: "identified"))
        XCTAssertEqual(f.coordinator.deferredInputs.map(\.id), ["other-voice-owner"])
        XCTAssertTrue(f.coordinator.submit("@maltose 其他說話者嘗試交回", origin: .voice, identity: "other-voice-handback", speakerID: "other", speakerStatus: "identified"))
        XCTAssertEqual(f.coordinator.deferredInputs.map(\.id), ["other-voice-owner", "other-voice-handback"])
        XCTAssertEqual(f.coordinator.conversation.recipient, .codex)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        XCTAssertEqual(f.store.task(id)?.messages.filter { $0.author == .user }.count, 0)
        XCTAssertTrue(f.coordinator.submit("@codex 人類追加需求", identity: "actual-brain-followup"))
        try await waitFor { f.coordinator.conversation.lastReportedTurnID == "turn-2" && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.store.tasks.count, 1)
        XCTAssertTrue(f.coordinator.submit("@maltose 請根據最新協作確認方向", identity: "actual-brain-handback"))
        try await waitFor { f.history.sessions.first?.messages.contains { $0.speaker == .assistant && $0.text.contains("主 Agent 已讀到人類追加需求") } == true }
        XCTAssertEqual(f.runtime.autonomy?.state, .active)
        XCTAssertEqual(f.store.task(id)?.status, .completed)
    }

    func testUnavailableExplicitModelIsNotSilentlyReplacedAndHumanSelectionSendsSavedInputOnce() async throws {
        let f = try fixture()
        try f.store.setPreferredModel("unavailable-explicit-model")
        try f.runtime.start(configuration: f.runtimeConfig); try await waitFor { f.runtime.state == .ready }
        XCTAssertTrue(f.coordinator.submit("@codex 等待正確模型", identity: "model-recovery-input"))
        try await waitFor { f.coordinator.conversation.issue != nil }
        XCTAssertEqual(f.store.preferredModel, "unavailable-explicit-model")
        XCTAssertTrue(f.store.tasks.isEmpty)
        XCTAssertEqual(f.runtime.autonomy?.state, .paused)
        let choices = try await f.coordinator.modelChoices(forceRefresh: true)
        XCTAssertEqual(choices.map(\.model), ["fixture-model"])
        XCTAssertThrowsError(try f.coordinator.selectModel("invented-model"))
        try f.coordinator.selectModel("fixture-model"); f.coordinator.retry()
        try await waitFor { f.coordinator.conversation.phase == .awaitingUserIntent && f.coordinator.conversation.pendingQuestionID == nil }
        XCTAssertEqual(f.store.tasks.count, 1)
        XCTAssertEqual(f.store.tasks.first?.model, "fixture-model")
        XCTAssertEqual(f.store.tasks.first?.messages.filter { $0.author == .user }.map(\.content), ["等待正確模型"])
    }
}
