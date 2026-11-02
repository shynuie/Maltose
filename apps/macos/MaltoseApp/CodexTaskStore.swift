import Foundation
import Darwin

enum CodexTaskStatus: String, Codable {
    case prepared, running, waitingForUser, awaitingReview, completed, failed, interrupted, needsReconciliation
}
enum AgentControlState: String, Codable {
    case maltoseActive, handingOff, codexDirect, reportingToMaltose, awaitingUserIntent
}
enum CodexMessageAuthor: String, Codable { case user, maltose, codex, tool, integration }
enum CodexMessageOrigin: String, Codable { case native, voice, delegation, codex, synchronization }

struct CodexTaskMessage: Codable, Equatable, Identifiable {
    enum Delivery: String, Codable { case prepared, accepted, rejected, uncertain }
    let id: String
    let author: CodexMessageAuthor
    let origin: CodexMessageOrigin
    let content: String
    let threadID: String?
    var turnID: String?
    var delivery: Delivery? = nil
}

struct CodexDelegation: Codable, Equatable {
    var objective: String
    var constraints: [String]
    var acceptanceCriteria: [String]
    var context: String? = nil
}

struct CodexTaskRecord: Codable, Equatable, Identifiable {
    let id: UUID
    let conversationID: String
    let repositoryPath: String
    let worktreePath: String
    let delegation: CodexDelegation
    let createdAt: Date
    var updatedAt: Date
    var threadID: String?
    var activeTurnID: String?
    var lastFinishedTurnID: String?
    var status: CodexTaskStatus = .prepared
    var control: AgentControlState = .maltoseActive
    var messages: [CodexTaskMessage] = []
    var outcomeSummary: String?
    var failureMessage: String?
    var ownerSpeakerID: String?
    var workspaceChanges: UserViewValue?
    var model: String?
    var panelToolsRegistered: Bool?
    var productTaskID: UUID?
    /// Durable intent precedes RPC. An uncertain mutation is reconciled, never replayed blindly.
    var pendingOperation: Operation?

    struct Operation: Codable, Equatable {
        enum Kind: String, Codable { case startThread, startTurn, steerTurn, interruptTurn }
        enum Phase: String, Codable { case prepared, acknowledged, uncertain }
        let id: UUID
        let kind: Kind
        let clientMessageID: String?
        var phase: Phase
    }

    init(id: UUID = UUID(), conversationID: String, repositoryPath: String, worktreePath: String, delegation: CodexDelegation) {
        self.id = id; self.conversationID = conversationID
        self.repositoryPath = repositoryPath; self.worktreePath = worktreePath; self.delegation = delegation
        createdAt = Date(); updatedAt = createdAt
    }
}

enum CodexTaskStoreError: Error, LocalizedError {
    case invalid(String), conflict, unavailable(String)
    var errorDescription: String? {
        switch self {
        case let .invalid(message), let .unavailable(message): message
        case .conflict: "Codex 任務紀錄已變更，請重新讀取。"
        }
    }
}

/// Product task mapping only; Codex remains the authority for its conversation/runtime.
/// One owner, versioned snapshots, atomic replacement, explicit corruption errors.
@MainActor final class CodexTaskStore {
    private struct Document: Codable {
        var schemaVersion = 3
        var revision: Int = 0
        var tasks: [CodexTaskRecord] = []
        var conversations: [AgentConversationState]?
        var activeConversationID: String?
        var preferredModel: String?
        var productTasks: [ProductTask]?
    }
    private let url: URL
    private var lease: Int32 = -1
    private var document = Document()
    private var isOpen = false
    private var migrationSource: Data?
    private(set) var migrationBackupURL: URL?
    var onCommit: (() -> Void)?
    var revision: Int { document.revision }
    var tasks: [CodexTaskRecord] { document.tasks }
    var productTasks: [ProductTask] { document.productTasks ?? [] }
    func productTask(_ id: UUID) -> ProductTask? { productTasks.first { $0.id == id } }
    var conversations: [AgentConversationState] { document.conversations ?? [] }
    var activeConversation: AgentConversationState? { conversations.first { $0.id == document.activeConversationID } }
    var preferredModel: String? { document.preferredModel }
    func setPreferredModel(_ model: String) throws {
        guard !model.isEmpty, model.count <= 200 else { throw CodexTaskStoreError.invalid("Codex 模型識別碼不正確。") }
        var next = document; next.preferredModel = model; try commit(next)
    }

    init(url: URL) { self.url = url }
    deinit { if lease >= 0 { _ = Darwin.close(lease) } }

    func open() throws {
        guard !isOpen else { return }
        let directory = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        guard (try directory.resourceValues(forKeys: [.isSymbolicLinkKey])).isSymbolicLink != true else {
            throw CodexTaskStoreError.unavailable("Codex 任務目錄不能是符號連結。")
        }
        let fd = Darwin.open(url.appendingPathExtension("lock").path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw CodexTaskStoreError.unavailable("無法取得 Codex 任務紀錄鎖。") }
        do {
            try validatePrivateFile(fd)
            guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
                throw CodexTaskStoreError.unavailable("另一個 Maltose 正在使用 Codex 任務紀錄。")
            }
            var loaded = Document()
            let dataFD = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            if dataFD >= 0 {
                let file = FileHandle(fileDescriptor: dataFD, closeOnDealloc: true)
                defer { try? file.close() }
                try validatePrivateFile(dataFD)
                var info = stat(); guard fstat(dataFD, &info) == 0, info.st_size <= 64 * 1024 * 1024 else {
                    throw CodexTaskStoreError.invalid("Codex 任務紀錄超過大小限制。")
                }
                let source = try file.readToEnd() ?? Data()
                var restored = try JSONDecoder().decode(Document.self, from: source)
                let legacy = restored.schemaVersion == 1 || restored.schemaVersion == 2
                if legacy { restored.schemaVersion = 3 }
                try validate(restored, restoringSnapshot: true); loaded = restored
                migrationSource = legacy ? source : nil
            } else if errno != ENOENT { throw CodexTaskStoreError.unavailable("無法安全開啟 Codex 任務紀錄。") }
            document = loaded; lease = fd; isOpen = true
        } catch { _ = Darwin.close(fd); throw error }
    }

    func close() { if lease >= 0 { _ = Darwin.close(lease) }; lease = -1; isOpen = false }
    func task(_ id: UUID) -> CodexTaskRecord? { document.tasks.first { $0.id == id } }

    @discardableResult func ensureConversation(_ id: String? = nil) throws -> AgentConversationState {
        if let id, let existing = conversations.first(where: { $0.id == id }) { return existing }
        if id == nil, let activeConversation { return activeConversation }
        let conversation = AgentConversationState(id: id ?? UUID().uuidString)
        var next = document
        next.conversations = conversations + [conversation]; next.activeConversationID = conversation.id
        try commit(next); return conversation
    }

    func selectConversation(_ id: String) throws {
        guard conversations.contains(where: { $0.id == id }) else { throw CodexTaskStoreError.invalid("找不到協作對話。") }
        var next = document; next.activeConversationID = id; try commit(next)
    }

    func saveForegroundPublication(_ source: ForegroundPublication, conversationID: String) throws {
        try source.validate()
        try updateConversation(conversationID) { record in
            var sources = record.foregroundPublications ?? []
            if let index = sources.firstIndex(where: { $0.publicationID == source.publicationID }) {
                let previous = sources[index]
                guard previous.sameSource(as: source), previous.answerKind == source.answerKind, previous.assessment == nil || previous.assessment == source.assessment,
                      previous.state != "superseded" || source.state == "superseded",
                      previous.state != "delivered" || source.state == "delivered" else { throw CodexTaskStoreError.conflict }
                sources[index] = source
            } else { sources.append(source) }
            record.foregroundPublications = sources
            // A generated answer proves this input was actually admitted even if
            // its earlier user_message or submit_text ACK was lost.
            if let inputIndex = record.inputs.firstIndex(where: { $0.id == source.inputID }),
               [.dispatching, .uncertain].contains(record.inputs[inputIndex].delivery) {
                record.inputs[inputIndex].delivery = .accepted
            }
        }
    }

    func updateConversation(_ id: String, _ change: (inout AgentConversationState) throws -> Void) throws {
        guard let index = conversations.firstIndex(where: { $0.id == id }) else { throw CodexTaskStoreError.invalid("找不到協作對話。") }
        var next = document; var records = conversations
        try change(&records[index])
        guard records[index].id == id else { throw CodexTaskStoreError.invalid("對話識別碼不可替換。") }
        next.conversations = records; try commit(next)
    }

    @discardableResult func beginProductTask(conversationID: String, inputID: String, plan: ProductTaskPlan,
                                            parentID: UUID? = nil, forceNew: Bool = false) throws -> ProductTask {
        guard let conversation = conversations.first(where: { $0.id == conversationID }),
              let input = conversation.inputs.first(where: { $0.id == inputID }), input.delivery != .deferred,
              input.author == .user || input.origin == .delegation, plan.sourceInputID == inputID else {
            throw CodexTaskStoreError.invalid("共同任務必須綁定已保存且可處理的原始輸入。")
        }
        guard input.productRelation != .standalone else { throw CodexTaskStoreError.invalid("獨立問答不能寫入產品任務計畫。") }
        guard !forceNew || input.productTaskID == nil else { throw CodexTaskStoreError.conflict }
        let requestedNew = input.productRelation == .newTask && input.productTaskID == nil
        if !forceNew, !requestedNew, let id = input.productTaskID ?? conversation.activeProductTaskID, let existing = productTask(id), !existing.cancelled,
           existing.state != .completed || input.productTaskID == id {
            try mutateProductTask(id) { task in
                try task.append(input)
                if task.plan != plan { task.previousPlans.append(task.plan); task.plan = plan; task.planVersion += 1; task.stepProgress = nil }
            }
            try bindProductInput(conversationID: conversationID, inputID: inputID, taskID: id)
            return productTask(id)!
        }
        let task = ProductTask(conversationID: conversationID, parentID: parentID, input: input, plan: plan)
        var next = document
        next.productTasks = productTasks + [task]
        let index = next.conversations!.firstIndex { $0.id == conversationID }!
        next.conversations![index].activeProductTaskID = task.id
        let start = next.conversations![index].inputs.firstIndex { $0.id == inputID }!
        next.conversations![index].inputs[start].productTaskID = task.id
        try commit(next); return productTask(task.id)!
    }

    /// A model may classify the saved human input; it cannot manufacture one,
    /// move a committed requirement, or resume a held task with this operation.
    func relateProductInput(conversationID: String, inputID: String, relation: AgentInputRecord.ProductRelation,
                            taskID: UUID?, expectedRequirementsRevision: Int?) throws {
        guard let conversation = conversations.first(where: { $0.id == conversationID }),
              let input = conversation.inputs.first(where: { $0.id == inputID }), input.author == .user,
              input.recipient == .maltose, input.delivery != .deferred else { throw CodexTaskStoreError.conflict }
        if let previous = input.productRelation {
            guard previous == relation, relation != .continueTask || input.productTaskID == taskID else { throw CodexTaskStoreError.conflict }
            return
        }
        guard input.productTaskID == nil || (relation == .continueTask && input.productTaskID == taskID) else { throw CodexTaskStoreError.conflict }
        if relation == .continueTask {
            guard let id = taskID, id == conversation.activeProductTaskID, let task = productTask(id),
                  !task.held, !task.cancelled, task.requirementsRevision == expectedRequirementsRevision else { throw CodexTaskStoreError.conflict }
        } else if let id = taskID {
            guard id == conversation.activeProductTaskID, productTask(id)?.requirementsRevision == expectedRequirementsRevision else { throw CodexTaskStoreError.conflict }
        }
        try updateConversation(conversationID) { record in
            let index = record.inputs.firstIndex { $0.id == inputID }!
            record.inputs[index].productRelation = relation
            if relation == .standalone, let id = taskID, let task = productTask(id) {
                record.inputs[index].interlude = .init(taskID: id, requirementsRevision: task.requirementsRevision, planVersion: task.planVersion)
            }
            if relation == .continueTask { record.inputs[index].productTaskID = taskID }
            if relation == .newTask { record.activeProductTaskID = nil }
        }
    }

    func bindProductInput(conversationID: String, inputID: String, taskID: UUID) throws {
        guard productTask(taskID)?.conversationID == conversationID else { throw CodexTaskStoreError.invalid("輸入與共同任務不屬於同一對話。") }
        try updateConversation(conversationID) { conversation in
            guard let index = conversation.inputs.firstIndex(where: { $0.id == inputID }) else { throw CodexTaskStoreError.invalid("找不到原始輸入。") }
            if let existing = conversation.inputs[index].productTaskID, existing != taskID { throw CodexTaskStoreError.invalid("輸入已綁定另一個共同任務。") }
            conversation.inputs[index].productTaskID = taskID
        }
    }

    func recordProductExecution(_ taskID: UUID, _ execution: ProductExecution) throws {
        try mutateProductTask(taskID) { task in
            if let index = task.executions.firstIndex(where: { $0.id == execution.id }) {
                let previous = task.executions[index]
                guard previous.engine == execution.engine, previous.externalID == execution.externalID,
                      previous.inputID == execution.inputID, previous.requirementsRevision == execution.requirementsRevision,
                      previous.planVersion == execution.planVersion, previous.threadID == nil || previous.threadID == execution.threadID,
                      previous.turnID == nil || previous.turnID == execution.turnID else { throw CodexTaskStoreError.invalid("既有執行引用不可替換來源或要求版本。") }
                task.executions[index] = execution
            } else { task.executions.append(execution) }
        }
    }

    func recordProductWorkerAttempt(_ taskID: UUID, workerID: String, attemptID: String, inputID: String,
                                    requirementsRevision: Int, planVersion: Int) throws -> ProductExecution {
        let identity = "python:\(workerID):\(attemptID)"
        var saved: ProductExecution!
        try mutateProductTask(taskID) { task in
            guard !task.held, !task.cancelled, let index = task.executions.firstIndex(where: { $0.id == "python:\(workerID)" }),
                  task.executions[index].engine == .python, task.executions[index].externalID == workerID,
                  task.executions[index].inputID == inputID, task.executions[index].requirementsRevision == requirementsRevision,
                  task.executions[index].planVersion == planVersion else { throw CodexTaskStoreError.invalid("背景執行來源與已保存工作不符。") }
            if let existing = task.executions.first(where: { $0.id == identity }) {
                guard existing.engine == .python, existing.externalID == workerID, existing.inputID == inputID,
                      existing.requirementsRevision == requirementsRevision, existing.planVersion == planVersion,
                      existing.turnID == attemptID else { throw CodexTaskStoreError.invalid("背景執行識別碼不可替換來源。") }
                saved = existing; return
            }
            guard !task.executions.contains(where: { $0.engine == .python && $0.externalID == workerID && $0.id != "python:\(workerID)" && [.prepared, .running, .uncertain].contains($0.state) }) else {
                throw CodexTaskStoreError.invalid("前一次背景執行仍待確認，不能重複派發。")
            }
            // The original binding is a dispatch placeholder. Its accepted
            // attempt now owns running/terminal state, in the same transaction.
            task.executions[index].state = .succeeded
            saved = .init(id: identity, engine: .python, externalID: workerID, inputID: inputID,
                requirementsRevision: requirementsRevision, planVersion: planVersion, state: .running, turnID: attemptID)
            task.executions.append(saved)
        }
        return saved
    }

    func beginProductContinuation(_ taskID: UUID, scope: ProductContinuation, recoveredPhase: String? = nil) throws {
        try mutateProductTask(taskID) { task in
            if let index = task.continuations?.firstIndex(where: { $0.id == scope.id }) {
                let previous = task.continuations![index]
                guard previous.sourceOutcomeID == scope.sourceOutcomeID, previous.inputID == scope.inputID,
                      previous.requirementsRevision == scope.requirementsRevision, previous.planVersion == scope.planVersion,
                      previous.mode == scope.mode, previous.foregroundID == scope.foregroundID, previous.resumeAfterID == scope.resumeAfterID, ["running", "stored", "delivered"].contains(previous.state) || (scope.foregroundID != nil && previous.recoveryState == "uncertain" && ["admitting", "generated"].contains(recoveredPhase ?? "")) else { throw CodexTaskStoreError.conflict }
                task.continuations![index].runtimeSessionID = scope.runtimeSessionID
                if previous.recoveryState == "uncertain", recoveredPhase == "admitting" {
                    task.continuations![index].state = "running"
                    task.continuations![index].recoveryState = nil
                    if let execution = task.executions.firstIndex(where: { $0.id == "continue:\(scope.id)" }) { task.executions[execution].state = .running }
                }
                return
            }
            let count = (task.continuations ?? []).filter({ $0.requirementsRevision == scope.requirementsRevision }).count
            guard count < 8 || (count == 8 && scope.mode == "clarify") else {
                throw CodexTaskStoreError.unavailable("本次需求已達有界接續上限，請查看剩餘事項後決定下一步。")
            }
            task.continuations = (task.continuations ?? []) + [scope]
            if scope.mode == "work" {
                task.executions.append(.init(id: "continue:\(scope.id)", engine: .main, externalID: scope.id, inputID: scope.inputID,
                    requirementsRevision: scope.requirementsRevision, planVersion: scope.planVersion, state: .running, turnID: scope.id))
            }
        }
    }

    func reconcileForegroundContinuations(conversationID: String, runtimeSessionID: String) throws {
        for product in productTasks where product.conversationID == conversationID {
            guard (product.continuations ?? []).contains(where: { $0.foregroundID != nil && $0.mode == "work" && $0.state == "running" && $0.runtimeSessionID != runtimeSessionID }) else { continue }
            try mutateProductTask(product.id) { task in
                for index in (task.continuations ?? []).indices {
                    let scope = task.continuations![index]
                    if scope.foregroundID != nil && scope.mode == "work" && scope.state == "running" && scope.runtimeSessionID != runtimeSessionID {
                        task.continuations![index].state = "interrupted"
                        task.continuations![index].recoveryState = "uncertain"
                        if let execution = task.executions.firstIndex(where: { $0.id == "continue:\(scope.id)" && $0.state == .running }) { task.executions[execution].state = .uncertain }
                    }
                }
            }
        }
    }

    func setProductContinuationState(_ taskID: UUID, identity: String, state: String) throws {
        try mutateProductTask(taskID) { task in
            guard let index = task.continuations?.firstIndex(where: { $0.id == identity }) else { throw CodexTaskStoreError.conflict }
            if task.continuations![index].state == "delivered", state == "stored" { return }
            task.continuations![index].state = state
            task.continuations![index].recoveryState = nil
        }
    }

    func recordProductEvidence(_ taskID: UUID, _ evidence: ProductEvidence) throws {
        try mutateProductTask(taskID) { task in
            if let previous = task.evidence.first(where: { $0.id == evidence.id }) {
                guard previous == evidence else { throw CodexTaskStoreError.invalid("證據識別碼不可改寫。") }
            } else { task.evidence.append(evidence) }
        }
    }

    func recordProductOutcome(_ taskID: UUID, _ outcome: ProductTaskOutcome) throws {
        guard outcome.review == nil, outcome.assessment == nil else { throw CodexTaskStoreError.invalid("執行回報不能自行宣告已通過核對。") }
        try mutateProductTask(taskID) { task in
            if let previous = task.outcomes.first(where: { $0.id == outcome.id }) {
                var reported = previous; reported.review = nil
                guard reported == outcome else { throw CodexTaskStoreError.invalid("成果識別碼不可改寫來源或內容。") }
            } else { task.outcomes.append(outcome) }
        }
    }

    /// One durable engine report. Conflicting replay must not change execution
    /// state before discovering that its outcome/evidence already exists.
    func recordProductReport(_ taskID: UUID, execution: ProductExecution, evidence: [ProductEvidence] = [], outcome: ProductTaskOutcome) throws {
        guard outcome.review == nil, outcome.assessment == nil, outcome.executionID == execution.id,
              evidence.allSatisfy({ $0.executionID == execution.id }) else { throw CodexTaskStoreError.invalid("執行回報的來源不符。") }
        try mutateProductTask(taskID) { task in
            if let previous = task.outcomes.first(where: { $0.id == outcome.id }) {
                var reported = previous; reported.review = nil
                guard reported == outcome, task.executions.first(where: { $0.id == execution.id }) == execution,
                      evidence.allSatisfy({ item in task.evidence.contains(item) }) else { throw CodexTaskStoreError.invalid("成果重送不可替換既有回報。") }
                return
            }
            if let index = task.executions.firstIndex(where: { $0.id == execution.id }) {
                let previous = task.executions[index]
                guard previous.engine == execution.engine, previous.externalID == execution.externalID,
                      previous.inputID == execution.inputID, previous.requirementsRevision == execution.requirementsRevision,
                      previous.planVersion == execution.planVersion, previous.threadID == nil || previous.threadID == execution.threadID,
                      previous.turnID == nil || previous.turnID == execution.turnID else { throw CodexTaskStoreError.invalid("執行回報不可替換原始要求版本。") }
                task.executions[index] = execution
            } else { task.executions.append(execution) }
            for item in evidence {
                if let previous = task.evidence.first(where: { $0.id == item.id }) {
                    guard previous == item else { throw CodexTaskStoreError.invalid("回報證據識別碼不可改寫。") }
                } else { task.evidence.append(item) }
            }
            task.outcomes.append(outcome)
        }
    }

    /// Host verifier only. No model-facing or private transport operation can
    /// fabricate this review; it must cite already observed evidence.
    func verifyProductOutcome(_ taskID: UUID, outcomeID: String, review: ProductCompletionReview,
                              expectedRequirementsRevision: Int, expectedPlanVersion: Int) throws {
        try mutateProductTask(taskID) { task in
            guard task.requirementsRevision == expectedRequirementsRevision, task.planVersion == expectedPlanVersion,
                  let index = task.outcomes.firstIndex(where: { $0.id == outcomeID }) else { throw CodexTaskStoreError.conflict }
            task.outcomes[index].review = review
            guard task.isVerifiedComplete(task.outcomes[index]) else { throw CodexTaskStoreError.invalid("最新需求的完成條件尚無足夠實際證據。") }
        }
    }

    func setProductHeld(_ id: UUID, held: Bool) throws { try mutateProductTask(id) { $0.held = held } }

    func markProductCancelled(_ id: UUID) throws {
        try mutateProductTask(id) { $0.cancelled = true; $0.held = true }
    }

    func assessProductOutcome(_ taskID: UUID, outcomeID: String, assessment: ProductAssessment,
                              expectedRequirementsRevision: Int, expectedPlanVersion: Int) throws -> ProductAssessment {
        try assessment.validate()
        var saved = assessment
        try mutateProductTask(taskID) { task in
            guard task.requirementsRevision == expectedRequirementsRevision, task.planVersion == expectedPlanVersion,
                  !task.held, !task.cancelled,
                  let source = task.outcomes.first(where: { $0.id == outcomeID }),
                  source.requirementsRevision == expectedRequirementsRevision, source.planVersion == expectedPlanVersion else { throw CodexTaskStoreError.conflict }
            let identity = "assessment:\(outcomeID)"
            if let existing = task.outcomes.first(where: { $0.id == identity }) {
                if existing.reportedState == .completed && !task.isVerifiedComplete(existing) {
                    saved = .init(status: "partial", summary: "原有核對已不適用目前成果。", checks: [], remaining: ["成果或證據已改變，需要重新核對。"], resolvedFailures: [:], explanation: "保留舊核對歷史，不把過期結案套用到目前成果。")
                    return
                }
                saved = Self.assessment(from: existing); return
            }
            guard task.outcomes.last?.id == outcomeID else { throw CodexTaskStoreError.conflict }
            let state: ProductTaskOutcome.ReportedState = assessment.status == "completed" ? .completed : assessment.status == "needs_input" ? .needsInput : .partial
            var outcome = ProductTaskOutcome(id: identity, executionID: source.executionID,
                requirementsRevision: source.requirementsRevision, planVersion: source.planVersion, reportedState: state,
                summary: assessment.summary, remaining: assessment.remaining, artifactID: source.artifactID,
                review: assessment.status == "completed" ? assessment.completionReview : nil)
            task.outcomes.append(outcome)
            if assessment.status == "completed", !task.isVerifiedComplete(outcome) {
                saved = .init(status: "partial", summary: "成果已保存，完成核對仍未通過。", checks: [],
                    remaining: ["目前要求缺少足夠實際證據，仍有失敗或尚未確認的執行。"], resolvedFailures: [:], explanation: "原生完成條件核對未通過，沒有採納模型的完成宣告。")
                outcome = .init(id: identity, executionID: source.executionID, requirementsRevision: source.requirementsRevision,
                    planVersion: source.planVersion, reportedState: .partial, summary: saved.summary, remaining: saved.remaining, artifactID: source.artifactID)
                task.outcomes[task.outcomes.count - 1] = outcome
            }
            task.outcomes[task.outcomes.count - 1].assessment = saved
        }
        return saved
    }

    static func assessment(from outcome: ProductTaskOutcome) -> ProductAssessment {
        if let saved = outcome.assessment { return saved }
        return .init(status: outcome.reportedState == .completed ? "completed" : outcome.reportedState == .needsInput ? "needs_input" : "partial",
              summary: outcome.summary, checks: outcome.review?.checks.map { .init(criterion: $0.criterion, evidenceIDs: $0.evidenceIDs) } ?? [],
              remaining: outcome.remaining, resolvedFailures: outcome.review?.resolvedFailures ?? [:], explanation: outcome.review?.explanation ?? outcome.summary)
    }

    func requestConversationStop(_ conversationID: String) throws {
        guard let index = conversations.firstIndex(where: { $0.id == conversationID }) else { throw CodexTaskStoreError.invalid("找不到要停止的對話。") }
        var next = document; next.conversations = conversations; next.productTasks = productTasks
        next.conversations![index].stopRequested = true; next.conversations![index].issue = nil
        for inputIndex in next.conversations![index].inputs.indices where next.conversations![index].inputs[inputIndex].delivery == .queued && next.conversations![index].inputs[inputIndex].recipient == .codex {
            next.conversations![index].inputs[inputIndex].delivery = .deferred
        }
        if let id = next.conversations![index].activeProductTaskID, let productIndex = next.productTasks!.firstIndex(where: { $0.id == id }) {
            next.productTasks![productIndex].held = true; next.productTasks![productIndex].updatedAt = Date()
        }
        try commit(next)
    }

    func recordStepProgress(_ id: UUID, stepID: String, state: ProductStepProgress.State, detail: String) throws {
        try mutateProductTask(id) { task in
            var progress = task.stepProgress ?? []
            progress.removeAll { $0.stepID == stepID }
            progress.append(.init(stepID: stepID, state: state, detail: detail,
                                  requirementsRevision: task.requirementsRevision, planVersion: task.planVersion))
            task.stepProgress = progress
        }
    }

    private func mutateProductTask(_ id: UUID, _ change: (inout ProductTask) throws -> Void) throws {
        guard let index = productTasks.firstIndex(where: { $0.id == id }) else { throw CodexTaskStoreError.invalid("找不到共同產品任務。") }
        var next = document; next.productTasks = productTasks
        let original = next.productTasks![index]
        try change(&next.productTasks![index])
        guard next.productTasks![index].id == original.id, next.productTasks![index].conversationID == original.conversationID,
              next.productTasks![index].objective == original.objective, next.productTasks![index].parentID == original.parentID else {
            throw CodexTaskStoreError.invalid("共同任務的原始目標與來源不可替換。")
        }
        if next.productTasks![index] == original { return }
        next.productTasks![index].updatedAt = Date()
        try commit(next)
    }

    @discardableResult func enqueue(_ input: AgentInputRecord, conversationID: String) throws -> Bool {
        guard let conversation = conversations.first(where: { $0.id == conversationID }) else { throw CodexTaskStoreError.invalid("找不到協作對話。") }
        if let previous = conversation.inputs.first(where: { $0.id == input.id }) {
            guard previous.text == input.text, previous.author == input.author, previous.origin == input.origin,
                  previous.speakerID == input.speakerID, previous.speakerStatus == input.speakerStatus,
                  previous.runtimeSessionID == input.runtimeSessionID else {
                throw CodexTaskStoreError.invalid("協作訊息來源或內容衝突。")
            }
            return false
        }
        try updateConversation(conversationID) { $0.inputs.append(input) }; return true
    }

    func create(_ task: CodexTaskRecord) throws {
        guard !document.tasks.contains(where: { $0.id == task.id }) else { throw CodexTaskStoreError.conflict }
        var next = document; next.tasks.append(task); try commit(next)
    }

    func update(_ id: UUID, expectedRevision: Int? = nil, _ change: (inout CodexTaskRecord) throws -> Void) throws {
        if let expectedRevision, expectedRevision != document.revision { throw CodexTaskStoreError.conflict }
        guard let index = document.tasks.firstIndex(where: { $0.id == id }) else {
            throw CodexTaskStoreError.invalid("找不到 Codex 任務。")
        }
        var next = document
        let old = next.tasks[index]
        try change(&next.tasks[index])
        guard next.tasks[index].id == old.id, next.tasks[index].conversationID == old.conversationID,
              next.tasks[index].repositoryPath == old.repositoryPath, next.tasks[index].worktreePath == old.worktreePath,
              next.tasks[index].delegation == old.delegation,
              old.model == nil || next.tasks[index].model == old.model,
              next.tasks[index].panelToolsRegistered == old.panelToolsRegistered,
              old.productTaskID == nil || next.tasks[index].productTaskID == old.productTaskID,
              old.threadID == nil || next.tasks[index].threadID == old.threadID else {
            throw CodexTaskStoreError.invalid("既有 Codex 任務的對話與工作位置不可替換。")
        }
        next.tasks[index].updatedAt = Date()
        try commit(next)
    }

    /// Stable source IDs deduplicate delivery without erasing provenance.
    @discardableResult func append(_ message: CodexTaskMessage, to id: UUID) throws -> Bool {
        guard let task = task(id) else { throw CodexTaskStoreError.invalid("找不到 Codex 任務。") }
        if let existing = task.messages.first(where: { $0.id == message.id }) {
            guard existing.author == message.author, existing.origin == message.origin, existing.content == message.content,
                  existing.threadID == message.threadID, message.turnID == nil || existing.turnID == message.turnID else {
                throw CodexTaskStoreError.invalid("重複訊息的內容或來源不一致。")
            }
            return false
        }
        try update(id) { $0.messages.append(message) }
        return true
    }

    private func commit(_ candidate: Document) throws {
        guard isOpen else { throw CodexTaskStoreError.unavailable("Codex 任務紀錄尚未開啟。") }
        var next = candidate; next.revision += 1
        // Only captured input associations can amend a task. Selecting/viewing a
        // historical task never pulls other conversations' later messages in.
        var products = next.productTasks ?? []
        for conversation in next.conversations ?? [] {
            for input in conversation.inputs where (input.author == .user || input.origin == .delegation) && input.delivery != .deferred && input.reviewDisposition != .dismissed {
                guard let id = input.productTaskID, let index = products.firstIndex(where: { $0.id == id && $0.conversationID == conversation.id }) else { continue }
                try products[index].append(input)
            }
        }
        next.productTasks = products
        try validate(next)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(next)
        guard data.count <= 64 * 1024 * 1024 else { throw CodexTaskStoreError.invalid("Codex 任務紀錄超過大小限制。") }
        let temporary = url.deletingLastPathComponent().appendingPathComponent(".codex-tasks-\(UUID().uuidString).tmp")
        let directoryFD = Darwin.open(url.deletingLastPathComponent().path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard directoryFD >= 0 else { throw CodexTaskStoreError.unavailable("Codex 任務目錄不可用。") }
        defer { _ = Darwin.close(directoryFD) }
        if let source = migrationSource {
            let backup = url.deletingLastPathComponent().appendingPathComponent("tasks-pre-workflow-v3-\(UUID().uuidString).json")
            let backupFD = Darwin.open(backup.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
            guard backupFD >= 0 else { throw CodexTaskStoreError.unavailable("無法備份舊版任務紀錄。") }
            let saved = FileHandle(fileDescriptor: backupFD, closeOnDealloc: true)
            do { try saved.write(contentsOf: source); try saved.synchronize(); try saved.close() }
            catch { try? saved.close(); throw error }
            guard fsync(directoryFD) == 0 else { throw CodexTaskStoreError.unavailable("舊版任務備份尚未同步。") }
            migrationBackupURL = backup; migrationSource = nil
        }
        let fd = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw CodexTaskStoreError.unavailable("無法儲存 Codex 任務紀錄。") }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close(); try? FileManager.default.removeItem(at: temporary) }
        try handle.write(contentsOf: data); try handle.synchronize(); try handle.close()
        guard Darwin.rename(temporary.path, url.path) == 0 else {
            throw CodexTaskStoreError.unavailable("無法完成 Codex 任務紀錄寫入。")
        }
        document = next
        guard fsync(directoryFD) == 0 else {
            throw CodexTaskStoreError.unavailable("任務紀錄已寫入，但無法確認目錄同步；請核對狀態。")
        }
        onCommit?()
    }

    private func validatePrivateFile(_ fd: Int32) throws {
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_mode & 0o077 == 0, info.st_nlink == 1 else {
            throw CodexTaskStoreError.unavailable("Codex 任務紀錄必須是目前使用者專用的普通檔案。")
        }
    }
    private func validate(_ candidate: Document, restoringSnapshot: Bool = false) throws {
        if let model = candidate.preferredModel, model.isEmpty || model.count > 200 { throw CodexTaskStoreError.invalid("Codex 模型設定不正確。") }
        guard candidate.schemaVersion == 3, candidate.revision >= 0,
              Set(candidate.tasks.map(\.id)).count == candidate.tasks.count else {
            throw CodexTaskStoreError.invalid("Codex 任務紀錄版本或識別碼不正確。")
        }
        let conversations = candidate.conversations ?? []
        let products = candidate.productTasks ?? []
        guard products.count <= 4096, Set(products.map(\.id)).count == products.count else { throw CodexTaskStoreError.invalid("共同任務數量或識別碼不正確。") }
        for product in products {
            try product.validate()
            if document.productTasks?.first(where: { $0.id == product.id })?.cancelled == true, !product.cancelled { throw CodexTaskStoreError.conflict }
            guard let conversation = conversations.first(where: { $0.id == product.conversationID }),
                  product.requirements.allSatisfy({ requirement in conversation.inputs.contains { $0.id == requirement.inputID && $0.text == requirement.text && $0.author == requirement.author && $0.origin == requirement.origin } }) else {
                throw CodexTaskStoreError.invalid("共同任務要求不屬於原始對話輸入。")
            }
            var seen: Set<UUID> = [product.id]; var parent = product.parentID
            while let id = parent {
                guard seen.insert(id).inserted, let record = products.first(where: { $0.id == id }), record.conversationID == product.conversationID else { throw CodexTaskStoreError.invalid("父任務不存在、跨對話或構成循環。") }
                parent = record.parentID
            }
            if product.state == .completed && products.contains(where: { $0.parentID == product.id && $0.state != .completed }) {
                throw CodexTaskStoreError.invalid("必要子任務仍未完成。")
            }
        }
        guard Set(conversations.map(\.id)).count == conversations.count,
              candidate.activeConversationID == nil || conversations.contains(where: { $0.id == candidate.activeConversationID }) else {
            throw CodexTaskStoreError.invalid("協作對話識別碼不正確。")
        }
        for conversation in conversations {
            let claims = conversation.panelMutationClaims ?? []
            let oldClaims = document.conversations?.first(where: { $0.id == conversation.id })?.panelMutationClaims ?? []
            guard claims.count <= 1024, Array(claims.prefix(oldClaims.count)) == oldClaims,
                  Set(claims.map { "\($0.inputID)\u{0}\($0.targetID)\u{0}\($0.category)\u{0}\($0.source.runtimeSessionID)\u{0}\($0.source.scopeID)" }).count == claims.count,
                  claims.allSatisfy({ claim in
                      !claim.targetID.isEmpty && claim.targetID.utf8.count <= 256 && !claim.targetID.contains("\u{0}") &&
                      ["content", "view", "close", "focus", "layout", "save", "identity"].contains(claim.category) &&
                      !claim.source.scopeID.isEmpty && claim.source.scopeID.utf8.count <= 128 &&
                      (claim.operationVersion == nil || claim.operationVersion == 1) &&
                      (claim.autonomous != true || claim.category != "save") &&
                      conversation.inputs.contains(where: { $0.id == claim.inputID && $0.author == .user }) &&
                      conversation.inputs.contains(where: { $0.id == claim.source.inputID })
                  }) else { throw CodexTaskStoreError.conflict }
            let operations = conversation.panelOperations ?? []
            // Loading validates the saved snapshot; only a new transaction must append prepared rows.
            let oldOperations = restoringSnapshot ? operations : document.conversations?.first(where: { $0.id == conversation.id })?.panelOperations ?? []
            guard operations.count <= 4096, operations.count >= oldOperations.count,
                  Set(operations.map(\.id)).count == operations.count else { throw CodexTaskStoreError.conflict }
            for (index, operation) in operations.enumerated() {
                guard !operation.id.isEmpty, operation.id.utf8.count <= 128, !operation.acknowledgementToken.isEmpty,
                      operation.acknowledgementToken.utf8.count <= 128, operation.commandDigest.count == 64,
                      operation.beforeStamp.count == 64, !operation.instanceID.isEmpty,
                      !operation.targets.isEmpty, operation.targets.count <= 64, Set(operation.targets).count == operation.targets.count,
                      operation.targets.allSatisfy({ target in claims.contains(where: { $0.operationVersion == 1 && $0.source == operation.source && $0.inputID == operation.inputID && $0.category == operation.category && $0.targetID == target }) }) else { throw CodexTaskStoreError.conflict }
                if operation.phase == .prepared {
                    guard operation.afterStamp == nil, operation.responseData == nil, !operation.acknowledged else { throw CodexTaskStoreError.conflict }
                } else {
                    guard let data = operation.responseData, data.count <= 64 * 1024,
                          let response = try? JSONDecoder().decode(WorkspaceAgentResponse.self, from: data), response.operationReceipts == nil,
                          operation.afterStamp?.count == 64,
                          !operation.acknowledged || [.completed, .failedNoChange].contains(operation.phase) else { throw CodexTaskStoreError.conflict }
                    if operation.phase == .completed { guard response.ok else { throw CodexTaskStoreError.conflict } }
                    if operation.phase == .failedNoChange {
                        guard !response.ok, operation.beforeStamp == operation.afterStamp, operation.category != "save" else { throw CodexTaskStoreError.conflict }
                    }
                }
                if index < oldOperations.count {
                    let old = oldOperations[index]
                    guard operation.hasSameOrigin(as: old), !old.acknowledged || operation.acknowledged else { throw CodexTaskStoreError.conflict }
                    if old.phase != .prepared {
                        guard operation.phase == old.phase, operation.afterStamp == old.afterStamp, operation.responseData == old.responseData else { throw CodexTaskStoreError.conflict }
                    }
                } else {
                    guard operation.phase == .prepared else { throw CodexTaskStoreError.conflict }
                }
            }
            for (index, claim) in claims.enumerated() {
                if claim.autonomous != true, let previous = claims.prefix(index).last(where: { $0.inputID == claim.inputID && $0.targetID == claim.targetID && $0.category == claim.category }), previous.source != claim.source {
                    guard NativePanelOperationJournal.retryLineage(previous, claim),
                          NativePanelOperationJournal.noEffectProof(previous, operations: oldOperations) else { throw CodexTaskStoreError.conflict }
                }
            }
            let workerPublications=conversation.workerPublications ?? []
            let oldWorkers=restoringSnapshot ? workerPublications:document.conversations?.first(where:{$0.id==conversation.id})?.workerPublications ?? []
            guard workerPublications.count<=2048,workerPublications.count>=oldWorkers.count,Set(workerPublications.map(\.publicationID)).count==workerPublications.count else {throw CodexTaskStoreError.conflict}
            for (index,source) in workerPublications.enumerated() {
                try source.validate()
                guard let task=products.first(where:{$0.id==source.taskID && $0.conversationID==conversation.id}),
                      let execution=task.executions.first(where:{$0.id=="python:\(source.workerID):\(source.attemptID)"}),
                      execution.inputID==source.inputID,execution.requirementsRevision==source.requirementsRevision,execution.planVersion==source.planVersion,
                      task.outcomes.contains(where:{$0.id==source.publicationID && $0.executionID==execution.id}) else {throw CodexTaskStoreError.conflict}
                if index<oldWorkers.count {
                    let old=oldWorkers[index]
                    guard old.sameSource(as:source),old.state != "delivered" || source.state=="delivered",old.assessment==nil || old.assessment==source.assessment else {throw CodexTaskStoreError.conflict}
                } else {guard source.state=="prepared",source.assessment==nil else {throw CodexTaskStoreError.conflict}}
                if let resume=source.resumeAfterID {
                    guard let answer=conversation.foregroundPublications?.first(where:{$0.publicationID==resume && $0.state=="delivered" && $0.taskID==nil && $0.answerKind=="answer"}),
                          conversation.inputs.contains(where:{$0.id==answer.inputID && $0.productRelation == .standalone && $0.interlude == ProductInterlude(taskID:source.taskID,requirementsRevision:source.requirementsRevision,planVersion:source.planVersion)}) else {throw CodexTaskStoreError.conflict}
                }
            }
            let publications = conversation.foregroundPublications ?? []
            guard publications.count <= 2048, Set(publications.map(\.publicationID)).count == publications.count else { throw CodexTaskStoreError.conflict }
            for publication in publications {
                try publication.validate()
                guard conversation.inputs.contains(where: { $0.id == publication.inputID && $0.author == .user }),
                      publication.taskID == nil || products.contains(where: { $0.id == publication.taskID && $0.conversationID == conversation.id }) else { throw CodexTaskStoreError.conflict }
            }
            for product in products where product.conversationID == conversation.id {
                for scope in product.continuations ?? [] {
                    if let resumed = scope.resumeAfterID {
                        let worker=WorkerResultPublication.root(task:product,outcomeID:scope.sourceOutcomeID,publications:workerPublications)
                        guard scope.foregroundID != nil || (worker?.inputID==scope.inputID && worker?.requirementsRevision==scope.requirementsRevision && worker?.planVersion==scope.planVersion), let answer = publications.first(where: { $0.publicationID == resumed }), answer.state == "delivered", answer.taskID == nil, answer.answerKind == "answer",
                              conversation.inputs.contains(where: { $0.id == answer.inputID && $0.productRelation == .standalone && $0.interlude == ProductInterlude(taskID: product.id, requirementsRevision: scope.requirementsRevision, planVersion: scope.planVersion) }) else { throw CodexTaskStoreError.conflict }
                    }
                    if let root = scope.foregroundID {
                        guard publications.contains(where: { $0.publicationID == root && $0.state == "delivered" && $0.taskID == product.id && $0.inputID == scope.inputID && $0.requirementsRevision == scope.requirementsRevision && $0.planVersion == scope.planVersion }) else { throw CodexTaskStoreError.conflict }
                    }
                }
            }
            guard !conversation.id.isEmpty, conversation.sequence >= 0,
                  Set(conversation.inputs.map(\.id)).count == conversation.inputs.count,
                  conversation.inputs.allSatisfy({ !$0.id.isEmpty }) else { throw CodexTaskStoreError.invalid("協作輸入紀錄不正確。") }
            guard conversation.inputs.allSatisfy({ input in input.productTaskID == nil || products.contains { $0.id == input.productTaskID && $0.conversationID == conversation.id } }) else { throw CodexTaskStoreError.invalid("輸入關聯到未知或跨對話任務。") }
            for input in conversation.inputs {
                if let interlude = input.interlude {
                    guard input.productRelation == .standalone, input.productTaskID == nil, interlude.requirementsRevision > 0, interlude.planVersion > 0,
                          products.contains(where: { $0.id == interlude.taskID && $0.conversationID == conversation.id }) else { throw CodexTaskStoreError.conflict }
                }
                if input.productRelation == .standalone && input.productTaskID != nil || input.productRelation == .continueTask && input.productTaskID == nil {
                    throw CodexTaskStoreError.invalid("輸入分類與任務關聯不符。")
                }
                if let old = document.conversations?.first(where: { $0.id == conversation.id })?.inputs.first(where: { $0.id == input.id }),
                   let relation = old.productRelation, (relation != input.productRelation || old.interlude != input.interlude) { throw CodexTaskStoreError.conflict }
            }
            if let taskID = conversation.activeTaskID {
                guard candidate.tasks.contains(where: { $0.id == taskID && $0.conversationID == conversation.id }) else {
                    throw CodexTaskStoreError.invalid("協作任務不屬於目前對話。")
                }
            }
            if let id = conversation.activeProductTaskID, !products.contains(where: { $0.id == id && $0.conversationID == conversation.id }) { throw CodexTaskStoreError.invalid("共同任務不屬於目前對話。") }
        }
        var threads = Set<String>()
        for task in candidate.tasks {
            if let id = task.productTaskID, !products.contains(where: { $0.id == id && $0.conversationID == task.conversationID }) { throw CodexTaskStoreError.invalid("Codex 執行引用缺少共同任務。") }
            if let model = task.model, model.isEmpty || model.count > 200 { throw CodexTaskStoreError.invalid("Codex 任務模型不正確。") }
            guard !task.conversationID.isEmpty, !task.delegation.objective.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  task.repositoryPath.hasPrefix("/"), task.worktreePath.hasPrefix("/"),
                  Set(task.messages.map(\.id)).count == task.messages.count,
                  task.messages.allSatisfy({ !$0.id.isEmpty && ($0.threadID == nil || $0.threadID == task.threadID) }) else {
                throw CodexTaskStoreError.invalid("Codex 任務缺少必要的來源、對話或絕對路徑。")
            }
            if let thread = task.threadID {
                guard !thread.isEmpty, threads.insert(thread).inserted else {
                    throw CodexTaskStoreError.invalid("Codex thread 不可對應到多個產品任務。")
                }
            }
            if task.activeTurnID != nil && task.threadID == nil {
                throw CodexTaskStoreError.invalid("Codex 回合必須屬於已知 thread。")
            }
            if task.status == .completed && (task.outcomeSummary?.isEmpty != false || task.activeTurnID != nil) {
                throw CodexTaskStoreError.invalid("Codex 任務完成需要成果，且不能仍有執行中的回合。")
            }
        }
    }
}
