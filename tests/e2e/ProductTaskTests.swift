import XCTest
@testable import MaltoseApp

@MainActor final class ProductTaskTests: XCTestCase {
    private func fixture() throws -> (CodexTaskStore, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-product-task-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = CodexTaskStore(url: directory.appendingPathComponent("tasks.json")); try store.open()
        _ = try store.ensureConversation("conversation")
        return (store, directory)
    }
    private func input(_ id: String, text: String = "完成原始需求", product: UUID? = nil) -> AgentInputRecord {
        .init(id: id, text: text, author: .user, origin: .native, speakerID: nil, speakerStatus: nil,
              runtimeSessionID: nil, recipient: .maltose, delivery: .accepted, productTaskID: product)
    }
    private func create(_ store: CodexTaskStore, id: String = "input", text: String = "完成原始需求") throws -> ProductTask {
        let source = input(id, text: text)
        try store.enqueue(source, conversationID: "conversation")
        return try store.beginProductTask(conversationID: "conversation", inputID: id,
            plan: .init(sourceInputID: id, criteria: ["實際檢查通過"], steps: [.init(id: "work", title: "執行與核對")]))
    }
    private func report(_ store: CodexTaskStore, task: ProductTask, remaining: [String] = []) throws {
        try store.recordProductExecution(task.id, .init(id: "execution", engine: .codex, externalID: "engine-task",
            inputID: task.requirements[0].inputID, requirementsRevision: task.requirementsRevision, planVersion: task.planVersion, state: .succeeded))
        try store.recordProductOutcome(task.id, .init(id: "outcome", executionID: "execution",
            requirementsRevision: task.requirementsRevision, planVersion: task.planVersion, reportedState: .completed,
            summary: "執行端回報完成", remaining: remaining))
    }
    private func review(_ task: ProductTask, evidence: String, resolved: [String: String] = [:]) -> ProductCompletionReview {
        .init(checks: task.completionCriteria.map { .init(criterion: $0, evidenceIDs: [evidence]) }, resolvedFailures: resolved,
              explanation: "核對目前版本的每一條要求與實際觀察。")
    }

    func testStandaloneInputLeavesOriginalRequirementsIntactAndClassificationSurvivesRestart() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        try store.enqueue(input("question", text: "只討論另一件事"), conversationID: "conversation")
        try store.relateProductInput(conversationID: "conversation", inputID: "question", relation: .standalone, taskID: task.id, expectedRequirementsRevision: 1)
        XCTAssertEqual(store.productTask(task.id), task)
        let revision = store.revision
        try store.relateProductInput(conversationID: "conversation", inputID: "question", relation: .standalone, taskID: task.id, expectedRequirementsRevision: 1)
        XCTAssertEqual(store.revision, revision)
        XCTAssertThrowsError(try store.beginProductTask(conversationID: "conversation", inputID: "question",
            plan: .init(sourceInputID: "question", criteria: ["其他工作"], steps: [.init(id: "work", title: "不可執行") ])))
        XCTAssertThrowsError(try store.relateProductInput(conversationID: "conversation", inputID: "question", relation: .continueTask, taskID: task.id, expectedRequirementsRevision: 1))
        store.close(); let restored = CodexTaskStore(url: directory.appendingPathComponent("tasks.json")); try restored.open(); defer { restored.close() }
        XCTAssertEqual(restored.productTask(task.id), task)
        XCTAssertEqual(restored.conversations.first?.inputs.last?.productRelation, .standalone)
        XCTAssertNil(restored.conversations.first?.inputs.last?.productTaskID)
    }

    func testExplicitContinuationAppendsSavedHumanTextOnceAndRejectsStaleScope() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        try store.enqueue(input("followup", text: "增加比較期間"), conversationID: "conversation")
        let revision = store.revision
        XCTAssertThrowsError(try store.relateProductInput(conversationID: "conversation", inputID: "followup", relation: .continueTask, taskID: task.id, expectedRequirementsRevision: 0))
        XCTAssertEqual(store.revision, revision)
        try store.relateProductInput(conversationID: "conversation", inputID: "followup", relation: .continueTask, taskID: task.id, expectedRequirementsRevision: 1)
        try store.relateProductInput(conversationID: "conversation", inputID: "followup", relation: .continueTask, taskID: task.id, expectedRequirementsRevision: 1)
        XCTAssertEqual(store.productTask(task.id)?.requirements.map(\.text), [task.objective, "增加比較期間"])
        XCTAssertEqual(store.conversations.first?.inputs.last?.productTaskID, task.id)
        XCTAssertEqual(store.productTask(task.id)?.planVersion, 1)
    }

    func testNewTaskAndLaterUnclassifiedInputsCannotContaminateOriginalGoal() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let original = try create(store)
        try store.enqueue(input("new", text: "寫另一份計畫"), conversationID: "conversation")
        try store.relateProductInput(conversationID: "conversation", inputID: "new", relation: .newTask, taskID: original.id, expectedRequirementsRevision: 1)
        try store.enqueue(input("later", text: "另一個尚未分類的問題"), conversationID: "conversation")
        let created = try store.beginProductTask(conversationID: "conversation", inputID: "new",
            plan: .init(sourceInputID: "new", criteria: ["只交付計畫"], steps: [.init(id: "plan", title: "規劃")]))
        XCTAssertNotEqual(created.id, original.id); XCTAssertEqual(store.productTask(original.id), original)
        XCTAssertEqual(created.requirements.map(\.inputID), ["new"])
        XCTAssertNil(store.conversations.first?.inputs.last?.productTaskID)
        XCTAssertEqual(store.conversations.first?.activeProductTaskID, created.id)
        XCTAssertTrue(created.executions.isEmpty, "A new plan is not permission to execute its steps")
    }

    func testScopeClassificationCannotResumeHeldTaskOrMoveCommittedInput() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        try store.setProductHeld(task.id, held: true)
        try store.enqueue(input("next", text: "討論下一步"), conversationID: "conversation")
        XCTAssertThrowsError(try store.relateProductInput(conversationID: "conversation", inputID: "next", relation: .continueTask, taskID: task.id, expectedRequirementsRevision: 1))
        _ = try store.beginProductTask(conversationID: "conversation", inputID: "input", plan: task.plan)
        XCTAssertEqual(store.productTask(task.id)?.held, true)
        XCTAssertThrowsError(try store.relateProductInput(conversationID: "conversation", inputID: "input", relation: .newTask, taskID: task.id, expectedRequirementsRevision: 1))
        XCTAssertThrowsError(try store.beginProductTask(conversationID: "conversation", inputID: "input", plan: task.plan, forceNew: true))
        XCTAssertEqual(store.productTasks.count, 1)
    }

    func testWorkerAttemptAdmissionIsAtomicIdempotentAndNeverUpgradesOriginalRequirementsOnRetry() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store), worker = UUID().uuidString, attempt = String(repeating: "a", count: 32)
        try store.recordProductExecution(task.id, .init(id: "python:\(worker)", engine: .python, externalID: worker,
            inputID: "input", requirementsRevision: 1, planVersion: 1, state: .prepared))
        let first = try store.recordProductWorkerAttempt(task.id, workerID: worker, attemptID: attempt, inputID: "input", requirementsRevision: 1, planVersion: 1)
        XCTAssertEqual(first.state, .running); XCTAssertEqual(store.productTask(task.id)?.executions.count, 2)
        XCTAssertEqual(store.productTask(task.id)?.executions.first?.state, .succeeded)
        XCTAssertEqual(try store.recordProductWorkerAttempt(task.id, workerID: worker, attemptID: attempt, inputID: "input", requirementsRevision: 1, planVersion: 1), first)
        XCTAssertThrowsError(try store.recordProductWorkerAttempt(task.id, workerID: worker, attemptID: String(repeating: "b", count: 32), inputID: "input", requirementsRevision: 1, planVersion: 1))
        XCTAssertEqual(store.productTask(task.id)?.executions.count, 2)
        var ended = first; ended.state = .failed
        try store.recordProductReport(task.id, execution: ended, outcome: .init(id: "failed-attempt", executionID: first.id,
            requirementsRevision: 1, planVersion: 1, reportedState: .failed, summary: "實際第一次執行失敗", remaining: ["修正失敗"]))
        try store.enqueue(input("new-human", text: "增加新要求", product: task.id), conversationID: "conversation")
        XCTAssertThrowsError(try store.recordProductWorkerAttempt(task.id, workerID: worker, attemptID: String(repeating: "b", count: 32), inputID: "new-human", requirementsRevision: 2, planVersion: 1))
        let retry = try store.recordProductWorkerAttempt(task.id, workerID: worker, attemptID: String(repeating: "b", count: 32), inputID: "input", requirementsRevision: 1, planVersion: 1)
        XCTAssertNotEqual(retry.id, first.id); XCTAssertEqual(retry.requirementsRevision, 1)
        XCTAssertEqual(store.productTask(task.id)?.requirementsRevision, 2)
        XCTAssertEqual(store.productTask(task.id)?.executions.first { $0.id == first.id }?.state, .failed)
    }

    func testReportedCompletionAndWorkerSuccessAreInsufficientButObservedCriterionProofCanComplete() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try report(store, task: task)
        XCTAssertEqual(store.productTask(task.id)?.state, .awaitingEvidence)
        for (id, kind, source) in [("reported", ProductEvidence.Kind.report, ProductEvidence.Source.reported), ("worker", .execution, .observed)] {
            try store.recordProductEvidence(task.id, .init(id: id, executionID: "execution", kind: kind, source: source, verdict: .passed, detail: "回報成功"))
            XCTAssertThrowsError(try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: id), expectedRequirementsRevision: 1, expectedPlanVersion: 1))
        }
        try store.recordProductEvidence(task.id, .init(id: "verified", executionID: "execution", kind: .verification, source: .observed, verdict: .passed, detail: "實際執行檢查並讀回正確結果。"))
        try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "verified"), expectedRequirementsRevision: 1, expectedPlanVersion: 1)
        XCTAssertEqual(store.productTask(task.id)?.state, .completed)
    }

    func testLaterCodexFileChangeInvalidatesEarlierTestProofUntilTestsRunAgain() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try report(store, task: task)
        try store.recordProductEvidence(task.id, .init(id: "before-edit", executionID: "execution", kind: .verification,
            source: .observed, verdict: .passed, detail: "Tests passed before the edit", checkKey: "tests", scopeID: "codex:worktree"))
        try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "before-edit"), expectedRequirementsRevision: 1, expectedPlanVersion: 1)
        XCTAssertEqual(store.productTask(task.id)?.state, .completed)
        try store.recordProductEvidence(task.id, .init(id: "edit", executionID: "execution", kind: .execution, source: .observed,
            verdict: .unknown, detail: "SDK file change after tests", scopeID: "codex:worktree", invalidatesVerification: true))
        XCTAssertNotEqual(store.productTask(task.id)?.state, .completed)
        XCTAssertThrowsError(try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "before-edit"), expectedRequirementsRevision: 1, expectedPlanVersion: 1))
        try store.recordProductEvidence(task.id, .init(id: "after-edit", executionID: "execution", kind: .verification,
            source: .observed, verdict: .passed, detail: "Tests passed after the edit", checkKey: "tests", scopeID: "codex:worktree"))
        try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "after-edit"), expectedRequirementsRevision: 1, expectedPlanVersion: 1)
        XCTAssertEqual(store.productTask(task.id)?.state, .completed)
    }

    func testNewHumanRequirementInvalidatesOldClosureAtomicallyAndPreservesOriginalGoalAndEvidence() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try report(store, task: task)
        try store.recordProductEvidence(task.id, .init(id: "verified", executionID: "execution", kind: .verification, source: .observed, verdict: .passed, detail: "版本一通過"))
        try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "verified"), expectedRequirementsRevision: 1, expectedPlanVersion: 1)
        try store.enqueue(input("followup", text: "追加要求也必須完成", product: task.id), conversationID: "conversation")
        let amended = try XCTUnwrap(store.productTask(task.id))
        XCTAssertEqual(amended.requirementsRevision, 2); XCTAssertEqual(amended.objective, task.objective)
        XCTAssertEqual(amended.state, .partial); XCTAssertEqual(amended.evidence.count, 1); XCTAssertEqual(amended.outcomes.count, 1)
        XCTAssertThrowsError(try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(amended, evidence: "verified"), expectedRequirementsRevision: 1, expectedPlanVersion: 1))
        store.close(); let restored = CodexTaskStore(url: directory.appendingPathComponent("tasks.json")); try restored.open(); defer { restored.close() }
        XCTAssertEqual(restored.productTask(task.id), amended)
    }

    func testFailedCheckNeedsMatchingLaterPassingProofAndRemainingWorkBlocksClosure() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try report(store, task: task)
        try store.recordProductEvidence(task.id, .init(id: "old-pass", executionID: "execution", kind: .verification, source: .observed, verdict: .passed, detail: "先前通過", checkKey: "fixture-check"))
        try store.recordProductEvidence(task.id, .init(id: "failure", executionID: "execution", kind: .verification, source: .observed, verdict: .failed, detail: "之後失敗", blocksCompletion: true, checkKey: "fixture-check"))
        XCTAssertThrowsError(try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "old-pass", resolved: ["failure": "old-pass"]), expectedRequirementsRevision: 1, expectedPlanVersion: 1))
        try store.recordProductEvidence(task.id, .init(id: "new-pass", executionID: "execution", kind: .verification, source: .observed, verdict: .passed, detail: "修復後重新通過", checkKey: "fixture-check"))
        try store.verifyProductOutcome(task.id, outcomeID: "outcome", review: review(task, evidence: "new-pass", resolved: ["failure": "new-pass"]), expectedRequirementsRevision: 1, expectedPlanVersion: 1)
        XCTAssertEqual(store.productTask(task.id)?.state, .completed)
        let unfinished = ProductTaskOutcome(id: "partial-outcome", executionID: "execution", requirementsRevision: 1, planVersion: 1,
            reportedState: .completed, summary: "仍有待辦", remaining: ["必要驗收尚未執行"])
        try store.recordProductOutcome(task.id, unfinished)
        XCTAssertEqual(store.productTask(task.id)?.state, .awaitingEvidence, "A newer incomplete report invalidates earlier closure in the same version")
        XCTAssertThrowsError(try store.verifyProductOutcome(task.id, outcomeID: unfinished.id, review: review(task, evidence: "new-pass", resolved: ["failure": "new-pass"]), expectedRequirementsRevision: 1, expectedPlanVersion: 1))
    }

    func testInvalidPlanOrForeignExecutionCannotMutateCanonicalState() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        try store.enqueue(input("input"), conversationID: "conversation")
        let before = store.revision
        XCTAssertThrowsError(try store.beginProductTask(conversationID: "conversation", inputID: "input", plan: .init(sourceInputID: "input",
            criteria: ["通過"], steps: [.init(id: "a", title: "一", dependencies: ["b"]), .init(id: "b", title: "二", dependencies: ["a"])])))
        XCTAssertEqual(store.revision, before); XCTAssertTrue(store.productTasks.isEmpty)
        let task = try store.beginProductTask(conversationID: "conversation", inputID: "input", plan: .init(sourceInputID: "input", criteria: ["通過"], steps: [.init(id: "a", title: "一")]))
        XCTAssertThrowsError(try store.recordProductExecution(task.id, .init(id: "foreign", engine: .python, externalID: "job", inputID: "other-input", requirementsRevision: 1, planVersion: 1, state: .running)))
        XCTAssertTrue(store.productTask(task.id)!.executions.isEmpty)
    }

    func testSelectingHistoricalTaskDoesNotAppendAnotherTasksHumanRequirements() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let first = try create(store)
        try store.updateConversation("conversation") { $0.activeProductTaskID = nil }
        let second = try create(store, id: "second", text: "另一個獨立需求")
        try store.enqueue(input("second-followup", text: "只追加到第二個任務", product: second.id), conversationID: "conversation")
        try store.updateConversation("conversation") { $0.activeProductTaskID = first.id }
        XCTAssertEqual(store.productTask(first.id)?.requirementsRevision, 1)
        XCTAssertEqual(store.productTask(second.id)?.requirementsRevision, 2)
    }

    func testVersionTwoMigrationKeepsExactPrivateBackupBeforeFirstVersionThreeWrite() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("tasks.json"); store.close()
        var old = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        old["schemaVersion"] = 2; old.removeValue(forKey: "productTasks")
        let bytes = try JSONSerialization.data(withJSONObject: old, options: .sortedKeys)
        try bytes.write(to: url)
        let migrated = CodexTaskStore(url: url); try migrated.open(); defer { migrated.close() }
        XCTAssertNil(migrated.migrationBackupURL)
        try migrated.updateConversation("conversation") { $0.issue = "fixture" }
        let backup = try XCTUnwrap(migrated.migrationBackupURL)
        XCTAssertEqual(try Data(contentsOf: backup), bytes)
        XCTAssertEqual((try FileManager.default.attributesOfItem(atPath: backup.path)[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        XCTAssertEqual((try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])?["schemaVersion"] as? Int, 3)
    }

    func testConflictingEngineReplayCannotPartiallyChangeExecutionOrEvidence() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        let execution = ProductExecution(id: "python:job", engine: .python, externalID: "job", inputID: "input", requirementsRevision: 1, planVersion: 1, state: .succeeded)
        let evidence = ProductEvidence(id: "receipt", executionID: execution.id, kind: .execution, source: .observed, verdict: .passed, detail: "實際工作返回")
        let outcome = ProductTaskOutcome(id: "result", executionID: execution.id, requirementsRevision: 1, planVersion: 1,
            reportedState: .partial, summary: "保留完整回報", remaining: ["待核對需求"])
        try store.recordProductReport(task.id, execution: execution, evidence: [evidence], outcome: outcome)
        let revision = store.revision, saved = store.productTask(task.id)
        try store.recordProductReport(task.id, execution: execution, evidence: [evidence], outcome: outcome)
        XCTAssertEqual(store.revision, revision, "Identical replay should not append another report")
        var changed = execution; changed.state = .failed
        XCTAssertThrowsError(try store.recordProductReport(task.id, execution: changed, evidence: [evidence], outcome: outcome))
        let otherOutcome = ProductTaskOutcome(id: "new-result", executionID: execution.id, requirementsRevision: 1, planVersion: 1,
            reportedState: .failed, summary: "不同回報", remaining: ["失敗"])
        let conflicting = ProductEvidence(id: "receipt", executionID: execution.id, kind: .execution, source: .observed, verdict: .failed, detail: "衝突來源")
        XCTAssertThrowsError(try store.recordProductReport(task.id, execution: changed, evidence: [conflicting], outcome: otherOutcome))
        XCTAssertEqual(store.productTask(task.id), saved)
        XCTAssertEqual(store.revision, revision)
    }

    func testLaterRequirementCannotBeStampedAsAnEarlierExecutionAndHistoricalPlansAreValidated() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        try store.enqueue(input("later", text: "追加要求", product: task.id), conversationID: "conversation")
        let revision = store.revision
        XCTAssertThrowsError(try store.recordProductExecution(task.id, .init(id: "wrong-version", engine: .main, externalID: "runtime",
            inputID: "later", requirementsRevision: 1, planVersion: 1, state: .succeeded)))
        XCTAssertEqual(store.revision, revision)
        var corrupted = try XCTUnwrap(store.productTask(task.id))
        corrupted.planVersion = 2
        corrupted.previousPlans = [.init(sourceInputID: "input", criteria: ["舊條件"], steps: [.init(id: "old", title: "舊計畫", dependencies: ["missing"])])]
        XCTAssertThrowsError(try corrupted.validate())
    }

    func testAddingRequirementsDoesNotEraseUnresolvedFailedVerification() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try report(store, task: task)
        try store.recordProductEvidence(task.id, .init(id: "old-failure", executionID: "execution", kind: .verification,
            source: .observed, verdict: .failed, detail: "原本的必要測試失敗", blocksCompletion: true, checkKey: "regression"))
        try store.enqueue(input("additional", text: "另加一項要求", product: task.id), conversationID: "conversation")
        let amended = try XCTUnwrap(store.productTask(task.id))
        let execution = ProductExecution(id: "current", engine: .main, externalID: "runtime", inputID: "additional", requirementsRevision: 2, planVersion: 1, state: .succeeded)
        let outcome = ProductTaskOutcome(id: "current-result", executionID: execution.id, requirementsRevision: 2, planVersion: 1,
            reportedState: .completed, summary: "已處理追加要求", remaining: [])
        try store.recordProductReport(task.id, execution: execution, outcome: outcome)
        try store.recordProductEvidence(task.id, .init(id: "unrelated-pass", executionID: execution.id, kind: .verification,
            source: .observed, verdict: .passed, detail: "另一項檢查通過", checkKey: "other-check"))
        XCTAssertThrowsError(try store.verifyProductOutcome(task.id, outcomeID: outcome.id,
            review: review(amended, evidence: "unrelated-pass", resolved: ["old-failure": "unrelated-pass"]), expectedRequirementsRevision: 2, expectedPlanVersion: 1))
        try store.recordProductEvidence(task.id, .init(id: "fixed-pass", executionID: execution.id, kind: .verification,
            source: .observed, verdict: .passed, detail: "同一回歸檢查實際重驗通過", checkKey: "regression"))
        try store.verifyProductOutcome(task.id, outcomeID: outcome.id,
            review: review(amended, evidence: "fixed-pass", resolved: ["old-failure": "fixed-pass"]), expectedRequirementsRevision: 2, expectedPlanVersion: 1)
        XCTAssertEqual(store.productTask(task.id)?.state, .completed)
    }
}
