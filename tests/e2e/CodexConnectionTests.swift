import XCTest
import Darwin
@testable import MaltoseApp

@MainActor final class CodexConnectionTests: XCTestCase {
    private var project: URL { URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent() }
    func testManagedRunnerStopsOwnedChildAfterServerExitsWithoutClosingInheritedOutput() async throws {
        var config = try configuration("""
        import json,sys,subprocess,os,signal
        from pathlib import Path
        child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'])
        Path('owned-child.pid').write_text(str(child.pid))
        r=json.loads(input()); print(json.dumps({'id':r['id'],'result':{}}),flush=True)
        assert json.loads(input())['method']=='initialized'
        # Exit on stdin EOF while the child still holds the protocol's stdout open.
        for line in sys.stdin: pass
        os._exit(0)
        """)
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let original = config.arguments
        config.arguments = ["-m", "maltose.codex.runner", config.executable.path] + original
        var environment = ProcessInfo.processInfo.environment; environment["PYTHONPATH"] = project.appendingPathComponent("runtime").path
        config.environment = environment; config.ownsProcessGroup = true
        let connection = CodexConnection()
        defer { connection.stop() }
        try await connection.start(configuration: config)
        let pid = try XCTUnwrap(Int32(String(contentsOf: config.directory.appendingPathComponent("owned-child.pid"), encoding: .utf8)))
        XCTAssertEqual(Darwin.getpgid(pid), connection.processID)
        try await stop(connection)
        try await waitFor { Darwin.getpgid(pid) == -1 }
    }
    private func configuration(_ program: String, timeout: Duration = .seconds(2)) throws -> CodexLaunchConfiguration {
        let python = project.appendingPathComponent("runtime/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Requires the locked runtime test environment") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-codex-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return .init(executable: python, arguments: ["-u", "-c", program], directory: directory,
                     logURL: directory.appendingPathComponent("codex.log"), startupTimeout: timeout,
                     requestTimeout: timeout, shutdownGrace: .milliseconds(50))
    }
    private func waitFor(_ condition: () -> Bool, seconds: Double = 6, file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(seconds)
        while !condition(), Date() < deadline { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(condition(), file: file, line: line)
    }
    private func stop(_ connection: CodexConnection) async throws {
        connection.stop(); try await waitFor { connection.processID == nil }
    }

    func testFragmentedStreamConcurrentResponsesNullAndRealHandshakeOrdering() async throws {
        let config = try configuration("""
        import sys,json,os
        def send(value):
            data=(json.dumps(value)+'\\n').encode()
            for offset in range(0,len(data),3): os.write(1,data[offset:offset+3])
        init=json.loads(input()); assert init['method']=='initialize'
        assert init['params']['clientInfo']['name']=='maltose'
        send({'id':init['id'],'result':{'userAgent':'fixture'}})
        assert json.loads(input())['method']=='initialized'
        first=json.loads(input()); second=json.loads(input())
        send({'id':second['id'],'result':None})
        send({'method':'item/agentMessage/delta','params':{'delta':'麥芽糖'}})
        send({'id':first['id'],'result':{'received':first['method']}})
        for line in sys.stdin: pass
        """)
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection()
        var deltas: [String] = []
        connection.onNotification = { method, value in
            if method == "item/agentMessage/delta", let delta = value["delta"]?.stringValue { deltas.append(delta) }
        }
        try await connection.start(configuration: config)
        XCTAssertEqual(connection.state, .ready)
        let originalPID = connection.processID
        try await connection.start(configuration: config)
        XCTAssertEqual(connection.processID, originalPID)
        let first = Task { try await connection.request("first") }
        // Allow the first request to enter the serial writer before launching another.
        await Task.yield()
        let second = Task { try await connection.request("second") }
        let firstResult = try await first.value, secondResult = try await second.value
        XCTAssertEqual(firstResult["received"]?.stringValue, "first")
        XCTAssertEqual(secondResult, .null)
        XCTAssertEqual(deltas, ["麥芽糖"])
        try await stop(connection)
        XCTAssertEqual(connection.state, .stopped)
    }

    func testServerApprovalDeduplicatesScopesAndRejectsStaleReplyAcrossRestart() async throws {
        let config = try configuration("""
        import sys,json
        def send(v): print(json.dumps(v),flush=True)
        init=json.loads(input()); send({'id':init['id'],'result':{}})
        assert json.loads(input())['method']=='initialized'
        request={'id':7,'method':'item/commandExecution/requestApproval','params':{'threadId':'fixture-thread','turnId':'fixture-turn'}}
        send(request); send(request)
        response=json.loads(input()); assert response['id']==7 and response['result']['decision']=='decline'
        send(request)
        assert json.loads(input())==response
        # String and integer IDs are independent.
        request['id']='7'; send(request)
        response=json.loads(input()); assert response['id']=='7'
        send({'method':'fixture/done','params':{}})
        for line in sys.stdin: pass
        """)
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection()
        var requests: [CodexServerRequest] = [], done = false
        connection.onNotification = { method, _ in if method == "fixture/done" { done = true } }
        connection.onServerRequest = { request in
            requests.append(request)
            Task { @MainActor in
                try await Task.sleep(for: .milliseconds(20))
                XCTAssertTrue(connection.respond(to: request, result: .success(.object(["decision": .string("decline")]))))
                XCTAssertFalse(connection.respond(to: request, result: .success(.object([:]))))
            }
        }
        try await connection.start(configuration: config)
        try await waitFor { done }
        XCTAssertEqual(requests.count, 2)
        let stale = try XCTUnwrap(requests.first)
        try await stop(connection)
        done = false; requests.removeAll()
        try await connection.start(configuration: config)
        XCTAssertFalse(connection.respond(to: stale, result: .success(.object(["decision": .string("accept")]))))
        try await waitFor { done }
        try await stop(connection)
    }

    func testTimeoutAndCancellationDoNotRetryOrClaimCancelledExecution() async throws {
        let config = try configuration("""
        import sys,json
        init=json.loads(input()); print(json.dumps({'id':init['id'],'result':{}}),flush=True)
        assert json.loads(input())['method']=='initialized'
        requests=[]
        for line in sys.stdin:
            request=json.loads(line); requests.append(request['method'])
            if request['method']=='inspect':
                print(json.dumps({'id':request['id'],'result':{'methods':requests}}),flush=True)
        """, timeout: .milliseconds(120))
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection()
        try await connection.start(configuration: config)
        do { _ = try await connection.request("write"); XCTFail("Must time out") }
        catch CodexConnectionError.outcomeUnknown(let method) { XCTAssertEqual(method, "write") }
        let task = Task { try await connection.request("another-write", timeout: .seconds(10)) }
        try await Task.sleep(for: .milliseconds(30)); task.cancel()
        do { _ = try await task.value; XCTFail("Must stop observing") }
        catch CodexConnectionError.outcomeUnknown(let method) { XCTAssertEqual(method, "another-write") }
        let inspected = try await connection.request("inspect")
        XCTAssertEqual(inspected["methods"], .strings(["write", "another-write", "inspect"]))
        XCTAssertEqual(connection.state, .ready)
        try await stop(connection)
    }

    func testMalformedAndTruncatedFramesFailAndReapChild() async throws {
        for output in ["b'not-json\\n'", "b'{\\\"id\\\":'", "b'{}\\n'"] {
            let config = try configuration("""
            import os,sys,json,time
            init=json.loads(input()); print(json.dumps({'id':init['id'],'result':{}}),flush=True)
            assert json.loads(input())['method']=='initialized'
            os.write(1,\(output)); sys.stdout.close(); os.close(1)
            time.sleep(30)
            """)
            let connection = CodexConnection()
            try await connection.start(configuration: config)
            try await waitFor { connection.processID == nil }
            if case .failed = connection.state {} else { XCTFail("Invalid protocol must fail") }
            try? FileManager.default.removeItem(at: config.directory)
        }
    }

    func testConflictingApprovalRequestCannotReplacePendingHumanDecision() async throws {
        let config = try configuration("""
        import sys,json,time
        init=json.loads(input()); print(json.dumps({'id':init['id'],'result':{}}),flush=True)
        assert json.loads(input())['method']=='initialized'
        for thread in ['one','two']:
            print(json.dumps({'id':'approval','method':'item/fileChange/requestApproval','params':{'threadId':thread}}),flush=True)
        time.sleep(30)
        """)
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection()
        var requests: [CodexServerRequest] = []
        connection.onServerRequest = { requests.append($0) }
        try await connection.start(configuration: config)
        try await waitFor { connection.processID == nil }
        XCTAssertEqual(requests.count, 1)
        XCTAssertFalse(connection.respond(to: try XCTUnwrap(requests.first), result: .success(.object([:]))))
        if case .failed = connection.state {} else { XCTFail("Conflicting IDs must fail") }
    }

    func testStartupTimeoutReapsBeforeAnotherProcessCanStart() async throws {
        let config = try configuration("import time; time.sleep(30)", timeout: .milliseconds(80))
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection()
        do { try await connection.start(configuration: config); XCTFail("No handshake") } catch {}
        try await waitFor { connection.processID == nil }
        if case .failed = connection.state {} else { XCTFail("Startup timeout must fail") }
    }

    func testResolvedServerRequestInvalidatesPendingHumanReplyAndDoesNotReopen() async throws {
        let config = try configuration("""
        import sys,json,time
        def send(v): print(json.dumps(v),flush=True)
        init=json.loads(input()); send({'id':init['id'],'result':{}})
        assert json.loads(input())['method']=='initialized'
        request={'id':9,'method':'item/fileChange/requestApproval','params':{'threadId':'thread','turnId':'turn'}}
        send(request)
        send({'method':'serverRequest/resolved','params':{'threadId':'thread','requestId':9}})
        send(request)
        send({'method':'fixture/done','params':{}})
        for line in sys.stdin: pass
        """)
        defer { try? FileManager.default.removeItem(at: config.directory) }
        let connection = CodexConnection()
        var requests: [CodexServerRequest] = [], done = false
        connection.onServerRequest = { requests.append($0) }
        connection.onNotification = { method, _ in if method == "fixture/done" { done = true } }
        try await connection.start(configuration: config)
        try await waitFor { done }
        XCTAssertEqual(requests.count, 1)
        XCTAssertFalse(connection.respond(to: try XCTUnwrap(requests.first), result: .success(.object(["decision": .string("accept")]))))
        try await stop(connection)
    }
    func testLifetimeFailureOrForeignTokenCannotClaimCleanupOrSilentlyRestart() async throws {
        for mode in ["failed", "foreign-token"] {
            var config = try configuration("""
            import json,sys,os,uuid
            if os.getpgrp()!=os.getpid(): os.setsid()
            token=str(uuid.uuid4())
            def send(v): print(json.dumps(v),flush=True)
            def lifecycle(method,value): send(dict(method='maltose/lifetime/'+method,params=dict(rootPID=os.getpid(),token=value)))
            lifecycle('started',token)
            r=json.loads(input()); send(dict(id=r['id'],result={}))
            assert json.loads(input())['method']=='initialized'
            r=json.loads(input()); send(dict(id=r['id'],result={}))
            lifecycle('failed' if \(String(reflecting: mode))=='failed' else 'cleaned',token if \(String(reflecting: mode))=='failed' else str(uuid.uuid4()))
            for line in sys.stdin: pass
            """)
            config.ownsProcessGroup = true
            let connection = CodexConnection()
            defer { connection.stop(); try? FileManager.default.removeItem(at: config.directory) }
            try await connection.start(configuration: config)
            _ = try await connection.request("fixture/fail")
            try await waitFor { connection.processID == nil }
            XCTAssertFalse(connection.ownedCleanupConfirmed)
            if case .failed = connection.state {} else { XCTFail("Unconfirmed cleanup must stay visible") }
            do { try await connection.start(configuration: config); XCTFail("Do not replace an unconfirmed process scope") }
            catch { XCTAssertFalse(connection.ownedCleanupConfirmed) }
        }
    }

    func testTruncatedOwnedServerStillDrainsGuardianConfirmationBeforeRetry() async throws {
        for mode in ["partial", "oversized"] {
            var config = try configuration("""
            import os,json,sys
            r=json.loads(input()); print(json.dumps(dict(id=r['id'],result={})),flush=True)
            assert json.loads(input())['method']=='initialized'
            json.loads(input())
            os.write(1,b'{partial' if \(String(reflecting: mode))=='partial' else b'x'*(17*1024*1024)); os._exit(3)
            """)
            let original = config.arguments
            config.arguments = ["-m", "maltose.codex.runner", config.executable.path] + original
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONPATH"] = project.appendingPathComponent("runtime").path
            config.environment = environment; config.ownsProcessGroup = true
            let connection = CodexConnection()
            defer { connection.stop(); try? FileManager.default.removeItem(at: config.directory) }
            try await connection.start(configuration: config)
            do { _ = try await connection.request("fixture/partial"); XCTFail("Missing result cannot be called success") } catch {}
            try await waitFor { connection.processID == nil }
            XCTAssertTrue(connection.ownedCleanupConfirmed, "A malformed server frame cannot discard the separate guardian receipt")
            if case .failed = connection.state {} else { XCTFail("Retain the original protocol failure") }
            let retry = try configuration("""
            import json,sys
            r=json.loads(input()); print(json.dumps(dict(id=r['id'],result={})),flush=True)
            assert json.loads(input())['method']=='initialized'
            for line in sys.stdin: pass
            """)
            defer { try? FileManager.default.removeItem(at: retry.directory) }
            try await connection.start(configuration: retry)
            XCTAssertEqual(connection.state,.ready)
            try await stop(connection)
        }
    }

    func testRunnerFailureBeforeExecutingCodexConfirmsNoWorkersAndAllowsRepairRetry() async throws {
        var config = try configuration("unused")
        config.arguments = ["-m", "maltose.codex.runner", "/not-present/codex"]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = project.appendingPathComponent("runtime").path
        config.environment = environment; config.ownsProcessGroup = true
        let connection = CodexConnection()
        defer { connection.stop(); try? FileManager.default.removeItem(at: config.directory) }
        do { try await connection.start(configuration: config); XCTFail("Missing CLI must fail") } catch {}
        try await waitFor { connection.processID == nil }
        XCTAssertTrue(connection.ownedCleanupConfirmed, "No Codex was executed, so a dependency repair must remain retryable")
        let repaired = try configuration("""
        import json,sys
        r=json.loads(input()); print(json.dumps(dict(id=r['id'],result={})),flush=True)
        assert json.loads(input())['method']=='initialized'
        for line in sys.stdin: pass
        """)
        defer { try? FileManager.default.removeItem(at: repaired.directory) }
        try await connection.start(configuration: repaired)
        XCTAssertEqual(connection.state,.ready)
        try await stop(connection)
    }

}
