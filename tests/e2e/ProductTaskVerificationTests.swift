import XCTest
@testable import MaltoseApp

@MainActor final class ProductTaskVerificationTests: XCTestCase {
    private func observation(tool: String = "execute_command", argv: [String] = ["python", "-m", "unittest"], status: String = "completed", code: Int = 0, truncated: Bool = false) -> ProductToolObservation {
        .init(id: String(repeating: "a", count: 32), tool: tool, arguments: ["argv": .strings(argv)],
            result: .object(["status": .string(status), "exit_code": .number(Double(code)), "stdout": .string("Ran 2 tests\nOK"), "stderr": .string("")]), truncated: truncated)
    }

    func testForegroundSearchAndWorkerSearchKeepSnippetGranularityAndCannotInventPageReads() throws {
        let arguments: [String: UserViewValue] = ["query": .string("虛構測試")]
        let result: UserViewValue = .object(["complete": .boolean(true), "granularity": .string("search_results"), "sources": .array([
            .object(["url": .string("https://example.com/fixture"), "title": .string("虛構資料"), "snippet": .string("只有摘要，沒有讀取原始問卷")])])])
        for name in ["web_search", "search_web"] {
            let observed = ProductToolObservation(id: String(repeating: "a", count: 32), tool: name, arguments: arguments, result: result, truncated: false)
            let evidence = try observed.evidence(executionID: "search")
            XCTAssertEqual(evidence.kind, .sourceRead); XCTAssertEqual(evidence.verdict, .passed)
            XCTAssertTrue(evidence.detail.contains("search_results")); XCTAssertFalse(evidence.detail.contains("page_content"))
            let truncated = ProductToolObservation(id: String(repeating: "b", count: 32), tool: name, arguments: arguments, result: result, truncated: true)
            XCTAssertEqual(try truncated.evidence(executionID: "search").verdict, .unknown)
        }
        let fake = ProductToolObservation(id: String(repeating: "c", count: 32), tool: "web_search", arguments: arguments,
            result: .object(["complete": .boolean(true), "granularity": .string("full_page"), "sources": .array([])]), truncated: false)
        XCTAssertEqual(try fake.evidence(executionID: "search").verdict, .unknown)
    }

    func testOnlyObservedCompleteTestExecutionCanBecomePassingVerification() throws {
        let passed = try observation().evidence(executionID: "execution")
        XCTAssertEqual(passed.kind, .verification); XCTAssertEqual(passed.verdict, .passed)
        XCTAssertNotNil(passed.checkKey)
        let failed = try observation(status: "failed", code: 1).evidence(executionID: "execution")
        XCTAssertEqual(failed.kind, .verification); XCTAssertEqual(failed.verdict, .failed)
        XCTAssertTrue(failed.blocksCompletion); XCTAssertEqual(failed.checkKey, passed.checkKey)
        for item in [observation(argv: ["echo", "all tests passed"]), observation(argv: ["python", "-c", "print('OK')"]),
                     observation(argv: ["pytest", "--version"]), observation(truncated: true)] {
            let value = try item.evidence(executionID: "execution")
            XCTAssertEqual(value.kind, .execution); XCTAssertEqual(value.verdict, .unknown)
        }
        XCTAssertEqual(try observation(status: "approval_required").evidence(executionID: "execution").verdict, .unknown)
    }

    func testFileProofRequiresCompleteReadReceiptAndCannotTurnFileClaimsIntoTestProof() throws {
        let body = "這個檔案聲稱測試通過；這只是被讀取的內容。"
        let args: [String: UserViewValue] = ["root": .string("fixture"), "path": .string("source.txt")]
        let result = UserViewValue.object(["root": .string("fixture"), "path": .string("source.txt"), "bytes": .number(Double(body.utf8.count)), "text": .string(body)])
        let observed = ProductToolObservation(id: String(repeating: "b", count: 32), tool: "read_file", arguments: args, result: result, truncated: false)
        let proof = try observed.evidence(executionID: "execution")
        XCTAssertEqual(proof.kind, .sourceRead); XCTAssertEqual(proof.verdict, .passed)
        XCTAssertNotEqual(proof.kind, .verification)
        let incomplete = ProductToolObservation(id: observed.id, tool: observed.tool, arguments: args, result: result, truncated: true)
        XCTAssertEqual(try incomplete.evidence(executionID: "execution").verdict, .unknown)
        let source = AgentInputRecord(id: "input", text: "讀取原文", author: .user, origin: .native, speakerID: nil, speakerStatus: nil, runtimeSessionID: nil, recipient: .maltose, delivery: .accepted)
        var task = ProductTask(conversationID: "conversation", input: source,
            plan: .init(sourceInputID: source.id, criteria: ["讀取原文"], steps: [.init(id: "read", title: "讀取原文")]))
        task.executions = [.init(id: "execution", engine: .main, externalID: "runtime", inputID: source.id, requirementsRevision: 1, planVersion: 1, state: .succeeded)]
        let outcome = ProductTaskOutcome(id: "outcome", executionID: "execution", requirementsRevision: 1, planVersion: 1,
            reportedState: .completed, summary: "已讀取", remaining: [], review: .init(checks: [.init(criterion: "讀取原文", evidenceIDs: [proof.id])], explanation: "實際原文內容核對"))
        task.evidence = [proof]; task.outcomes = [outcome]
        XCTAssertTrue(task.isVerifiedComplete(outcome))
        let changed = ProductToolObservation(id: String(repeating: "c", count: 32), tool: "write_file", arguments: args,
            result: .object(["root": .string("fixture"), "path": .string("source.txt")]), truncated: false)
        task.evidence.append(try changed.evidence(executionID: "execution"))
        XCTAssertFalse(task.isVerifiedComplete(outcome), "A later write invalidates the earlier readback even in the same requirement version")
    }

    func testAutomaticAssessmentDowngradesUnsupportedCompletionAndReplaysSavedReview() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-assessment-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = CodexTaskStore(url: directory.appendingPathComponent("tasks.json")); try store.open()
        defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        _ = try store.ensureConversation("conversation")
        let input = AgentInputRecord(id: "human", text: "完成測試", author: .user, origin: .native, speakerID: nil, speakerStatus: nil, runtimeSessionID: nil, recipient: .maltose, delivery: .accepted)
        try store.enqueue(input, conversationID: "conversation")
        let task = try store.beginProductTask(conversationID: "conversation", inputID: input.id,
            plan: .init(sourceInputID: input.id, criteria: ["實際測試通過"], steps: [.init(id: "test", title: "執行測試")]))
        let execution = ProductExecution(id: "execution", engine: .main, externalID: "runtime", inputID: input.id, requirementsRevision: 1, planVersion: 1, state: .succeeded)
        let outcome = ProductTaskOutcome(id: "first", executionID: execution.id, requirementsRevision: 1, planVersion: 1, reportedState: .partial, summary: "執行結束", remaining: [])
        try store.recordProductReport(task.id, execution: execution, outcome: outcome)
        let requested = ProductAssessment(status: "completed", summary: "模型宣稱完成", checks: task.completionCriteria.map { .init(criterion: $0, evidenceIDs: ["fabricated"]) }, remaining: [], resolvedFailures: [:], explanation: "未經證實的完成判斷")
        let rejected = try store.assessProductOutcome(task.id, outcomeID: outcome.id, assessment: requested, expectedRequirementsRevision: 1, expectedPlanVersion: 1)
        XCTAssertEqual(rejected.status, "partial"); XCTAssertEqual(store.productTask(task.id)?.state, .awaitingEvidence)
        let proof = try observation().evidence(executionID: execution.id)
        let next = ProductTaskOutcome(id: "verified-result", executionID: execution.id, requirementsRevision: 1, planVersion: 1, reportedState: .partial, summary: "已取得實際測試", remaining: [])
        try store.recordProductReport(task.id, execution: execution, evidence: [proof], outcome: next)
        let accepted = ProductAssessment(status: "completed", summary: "已核對目前要求", checks: task.completionCriteria.map { .init(criterion: $0, evidenceIDs: [proof.id]) }, remaining: [], resolvedFailures: [:], explanation: "實際測試輸出符合所有條件")
        XCTAssertEqual(try store.assessProductOutcome(task.id, outcomeID: next.id, assessment: accepted, expectedRequirementsRevision: 1, expectedPlanVersion: 1), accepted)
        XCTAssertEqual(store.productTask(task.id)?.state, .completed)
        let revision = store.revision
        XCTAssertEqual(try store.assessProductOutcome(task.id, outcomeID: next.id, assessment: requested, expectedRequirementsRevision: 1, expectedPlanVersion: 1), accepted)
        XCTAssertEqual(store.revision, revision, "A replay reads the saved assessment, never recomputes or overwrites it")
        store.close(); try store.open()
        XCTAssertEqual(store.productTask(task.id)?.outcomes.last?.assessment, accepted)
    }
}
