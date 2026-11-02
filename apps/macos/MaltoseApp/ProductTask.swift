import Foundation

enum ProductTaskState: String, Codable { case planned, running, awaitingEvidence, needsInput, partial, completed, held, cancelled }

struct ProductRequirement: Codable, Equatable {
    let inputID: String
    let text: String
    let author: CodexMessageAuthor
    let origin: CodexMessageOrigin
    let revision: Int
}

struct ProductPlanStep: Codable, Equatable {
    let id: String
    let title: String
    var dependencies: [String] = []
    var parentID: String? = nil
}

struct ProductStepProgress: Codable, Equatable {
    enum State: String, Codable { case pending, running, completed, failed }
    var stepID: String
    var state: State
    var detail: String
    var requirementsRevision: Int
    var planVersion: Int
}

struct ProductTaskPlan: Codable, Equatable {
    let sourceInputID: String
    let criteria: [String]
    let steps: [ProductPlanStep]
}

struct ProductExecution: Codable, Equatable {
    enum Engine: String, Codable { case main, python, codex }
    enum State: String, Codable { case prepared, running, succeeded, failed, cancelled, uncertain }
    let id: String
    let engine: Engine
    let externalID: String
    let inputID: String
    let requirementsRevision: Int
    let planVersion: Int
    var state: State
    var threadID: String?
    var turnID: String?
}

struct ProductEvidence: Codable, Equatable {
    enum Kind: String, Codable { case execution, verification, artifact, sourceRead, report }
    enum Source: String, Codable { case observed, reported }
    enum Verdict: String, Codable { case passed, failed, unknown }
    let id: String
    let executionID: String
    let kind: Kind
    let source: Source
    let verdict: Verdict
    let detail: String
    var blocksCompletion = false
    var checkKey: String?
    var invalidatesPriorEvidence: Bool?
    var scopeID: String?
    var invalidatesVerification: Bool?
}

struct ProductCriterionCheck: Codable, Equatable {
    enum Resolution: String, Codable { case satisfied, superseded }
    let criterion: String
    let evidenceIDs: [String]
    var resolution: Resolution = .satisfied
    var supersededByInputID: String?
    var explanation: String?
}

struct ProductCompletionReview: Codable, Equatable {
    let checks: [ProductCriterionCheck]
    /// A later real passing check may resolve an earlier failure; never erase it.
    var resolvedFailures: [String: String] = [:]
    let explanation: String
}

struct ProductTaskOutcome: Codable, Equatable {
    enum ReportedState: String, Codable { case completed, partial, needsInput, failed, cancelled }
    let id: String
    let executionID: String
    let requirementsRevision: Int
    let planVersion: Int
    let reportedState: ReportedState
    let summary: String
    let remaining: [String]
    var artifactID: String?
    var review: ProductCompletionReview?
    var assessment: ProductAssessment?
}

/// Canonical product state. Engine status, verification, delivery and autonomy
/// are independent; a turn ending or worker succeeding never sets completed.
struct ProductContinuation: Codable, Equatable {
    let id: String
    let sourceOutcomeID: String
    let inputID: String
    let requirementsRevision: Int
    let planVersion: Int
    let mode: String
    var runtimeSessionID: String
    var state: String
    var foregroundID: String? = nil
    var recoveryState: String? = nil
    var resumeAfterID: String? = nil
}

struct ProductTask: Codable, Equatable, Identifiable {
    var schemaVersion = 1
    let id: UUID
    let conversationID: String
    let parentID: UUID?
    let objective: String
    var requirements: [ProductRequirement]
    var plan: ProductTaskPlan
    var planVersion = 1
    var previousPlans: [ProductTaskPlan] = []
    var executions: [ProductExecution] = []
    var evidence: [ProductEvidence] = []
    var outcomes: [ProductTaskOutcome] = []
    var continuations: [ProductContinuation]?
    var stepProgress: [ProductStepProgress]?
    var held = false
    var cancelled = false
    let createdAt: Date
    var updatedAt: Date

    var requirementsRevision: Int { requirements.count }
    var completionCriteria: [String] {
        // Every human input remains in scope; a model's short plan cannot drop
        // a late requirement. De-duplicate identical text only for evaluation.
        var seen = Set<String>()
        return (requirements.filter { $0.author == .user }.map(\.text) + plan.criteria).filter { seen.insert($0).inserted }
    }
    var state: ProductTaskState {
        if cancelled { return .cancelled }
        if held { return .held }
        if let latest = outcomes.last(where: { $0.requirementsRevision == requirementsRevision && $0.planVersion == planVersion }), isVerifiedComplete(latest) { return .completed }
        let current = executions.filter { $0.requirementsRevision == requirementsRevision && $0.planVersion == planVersion }
        if current.contains(where: { $0.state == .running || $0.state == .prepared }) { return .running }
        let reports = outcomes.filter { $0.requirementsRevision == requirementsRevision && $0.planVersion == planVersion }
        if reports.last?.reportedState == .needsInput { return .needsInput }
        if !current.isEmpty || !reports.isEmpty { return .awaitingEvidence }
        return executions.isEmpty ? .planned : .partial
    }

    init(id: UUID = UUID(), conversationID: String, parentID: UUID? = nil, input: AgentInputRecord, plan: ProductTaskPlan) {
        self.id = id; self.conversationID = conversationID; self.parentID = parentID
        objective = input.text; self.plan = plan
        requirements = [.init(inputID: input.id, text: input.text, author: input.author, origin: input.origin, revision: 1)]
        createdAt = Date(); updatedAt = createdAt
    }

    mutating func append(_ input: AgentInputRecord) throws {
        if let previous = requirements.first(where: { $0.inputID == input.id }) {
            guard previous.text == input.text, previous.author == input.author, previous.origin == input.origin else { throw invalid("任務要求的來源或內容衝突。") }
            return
        }
        requirements.append(.init(inputID: input.id, text: input.text, author: input.author, origin: input.origin, revision: requirements.count + 1))
        updatedAt = Date()
    }

    func isVerifiedComplete(_ outcome: ProductTaskOutcome) -> Bool {
        guard outcome.requirementsRevision == requirementsRevision, outcome.planVersion == planVersion,
              outcomes.last(where: { $0.requirementsRevision == requirementsRevision && $0.planVersion == planVersion })?.id == outcome.id,
              outcome.reportedState == .completed, outcome.remaining.isEmpty, let review = outcome.review,
              executions.first(where: { $0.id == outcome.executionID })?.state == .succeeded,
              requirements.contains(where: { $0.author == .user }), !completionCriteria.isEmpty,
              !executions.contains(where: { [.prepared, .running, .uncertain].contains($0.state) }),
              Set(review.checks.map(\.criterion)) == Set(completionCriteria), review.checks.count == completionCriteria.count else { return false }
        let currentEvidence = evidence.filter { item in executions.contains { $0.id == item.executionID && $0.requirementsRevision == requirementsRevision && $0.planVersion == planVersion } }
        func witness(_ id: String) -> ProductEvidence? { currentEvidence.first { $0.id == id } }
        for check in review.checks {
            if check.resolution == .superseded {
                guard let original = requirements.first(where: { $0.author == .user && $0.text == check.criterion }),
                      let newer = requirements.first(where: { $0.inputID == check.supersededByInputID && $0.author == .user }),
                      newer.revision > original.revision, check.explanation?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else { return false }
                continue
            }
            guard !check.evidenceIDs.isEmpty, Set(check.evidenceIDs).count == check.evidenceIDs.count,
                  check.evidenceIDs.allSatisfy({ id in
                      guard let item = witness(id) else { return false }
                      guard item.source == .observed && item.verdict == .passed && [.verification, .artifact, .sourceRead].contains(item.kind) else { return false }
                      if let key = item.checkKey, let index = evidence.firstIndex(where: { $0.id == item.id }),
                         evidence.dropFirst(index + 1).contains(where: { $0.invalidatesPriorEvidence == true && $0.checkKey == key }) { return false }
                      if item.kind == .verification, let scope = item.scopeID, let index = evidence.firstIndex(where: { $0.id == item.id }),
                         evidence.dropFirst(index + 1).contains(where: { $0.invalidatesVerification == true && $0.scopeID == scope }) { return false }
                      return true
                  }) else { return false }
        }
        for failure in evidence where failure.blocksCompletion && failure.verdict == .failed {
            guard let replacement = review.resolvedFailures[failure.id], let passed = witness(replacement),
                  passed.source == .observed, passed.verdict == .passed, passed.kind == failure.kind,
                  let key = failure.checkKey, passed.checkKey == key,
                  let failedIndex = evidence.firstIndex(where: { $0.id == failure.id }),
                  let passedIndex = evidence.firstIndex(where: { $0.id == passed.id }), passedIndex > failedIndex else { return false }
        }
        return true
    }

    func validate() throws {
        func text(_ value: String, _ maximum: Int = 16000) -> Bool { !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.utf8.count <= maximum }
        guard schemaVersion == 1, text(conversationID, 128), text(objective, 64000), parentID != id,
              (1...256).contains(requirements.count), (1...512).contains(planVersion), previousPlans.count == planVersion - 1,
              Set(requirements.map(\.inputID)).count == requirements.count,
              requirements.enumerated().allSatisfy({ $0.element.revision == $0.offset + 1 && text($0.element.inputID, 256) && text($0.element.text, 64000) }),
              executions.count <= 512, evidence.count <= 2048, outcomes.count <= 512,
              Set(executions.map(\.id)).count == executions.count, Set(evidence.map(\.id)).count == evidence.count,
              Set(outcomes.map(\.id)).count == outcomes.count else { throw invalid("共同任務合約、大小或識別碼不正確。") }
        let progress = stepProgress ?? []
        guard progress.count <= 8, Set(progress.map(\.stepID)).count == progress.count,
              progress.allSatisfy({ item in plan.steps.contains(where: { $0.id == item.stepID }) &&
                  item.detail.utf8.count <= 1000 && item.requirementsRevision <= requirementsRevision && item.requirementsRevision >= 1 &&
                  item.planVersion == planVersion }) else { throw invalid("步驟進度不屬於目前計畫。") }
        let plans = previousPlans + [plan]
        let followups = continuations ?? []
        guard followups.count <= 512, Set(followups.map(\.id)).count == followups.count,
              followups.allSatisfy({ item in text(item.id, 128) && text(item.runtimeSessionID, 128) &&
                  ["work", "finalize", "clarify"].contains(item.mode) && ["running", "stored", "delivered", "interrupted"].contains(item.state) && (item.recoveryState == nil || item.recoveryState == "uncertain") &&
                  outcomes.contains(where: { $0.id == item.sourceOutcomeID }) && requirements.contains(where: { $0.inputID == item.inputID }) &&
                  (1...requirementsRevision).contains(item.requirementsRevision) && (1...planVersion).contains(item.planVersion) }) else {
            throw invalid("任務接續引用不符合有界合約。")
        }
        for candidate in plans {
            guard requirements.contains(where: { $0.inputID == candidate.sourceInputID }),
                  (1...32).contains(candidate.criteria.count), candidate.criteria.allSatisfy({ text($0) }),
                  (1...8).contains(candidate.steps.count), Set(candidate.steps.map(\.id)).count == candidate.steps.count,
                  candidate.steps.allSatisfy({ text($0.id, 256) && text($0.title) && $0.dependencies.count <= 8 && Set($0.dependencies).count == $0.dependencies.count }) else { throw invalid("歷史或目前計畫不符合有界合約。") }
            let parents = Dictionary(uniqueKeysWithValues: candidate.steps.map { ($0.id, $0.parentID) })
            for step in candidate.steps {
                var seen = Set([step.id]); var parent = step.parentID
                while let id = parent {
                    guard seen.insert(id).inserted, let entry = parents[id] else { throw invalid("步驟樹包含未知父節點或循環。") }
                    parent = entry
                }
            }
            let steps = Dictionary(uniqueKeysWithValues: candidate.steps.map { ($0.id, $0.dependencies) })
            var visited = Set<String>()
            func walk(_ id: String, path: Set<String>) -> Bool {
                if visited.contains(id) { return true }
                guard !path.contains(id), let dependencies = steps[id] else { return false }
                guard dependencies.allSatisfy({ walk($0, path: path.union([id])) }) else { return false }
                visited.insert(id); return true
            }
            guard candidate.steps.allSatisfy({ walk($0.id, path: []) }) else { throw invalid("任務步驟包含未知相依或循環。") }
        }
        for execution in executions {
            guard text(execution.id, 512), text(execution.externalID, 512),
                  let source = requirements.first(where: { $0.inputID == execution.inputID }), source.revision <= execution.requirementsRevision,
                  (1...requirementsRevision).contains(execution.requirementsRevision), (1...planVersion).contains(execution.planVersion),
                  let planSource = requirements.first(where: { $0.inputID == plans[execution.planVersion - 1].sourceInputID }),
                  planSource.revision <= execution.requirementsRevision else { throw invalid("執行引用不屬於已知要求版本。") }
        }
        for item in evidence {
            guard text(item.id, 512), text(item.detail, 32000), item.checkKey.map({ text($0, 512) }) ?? true,
                  item.scopeID.map({ text($0, 512) }) ?? true,
                  executions.contains(where: { $0.id == item.executionID }) else { throw invalid("證據缺少實際執行來源。") }
        }
        for outcome in outcomes {
            try outcome.assessment?.validate()
            if let assessment = outcome.assessment {
                let state: ProductTaskOutcome.ReportedState = assessment.status == "completed" ? .completed : assessment.status == "needs_input" ? .needsInput : .partial
                guard outcome.id.hasPrefix("assessment:"), outcome.reportedState == state, outcome.summary == assessment.summary,
                      outcome.remaining == assessment.remaining, assessment.status != "completed" || outcome.review == assessment.completionReview else { throw invalid("核對紀錄與成果狀態不符。") }
            }
            guard text(outcome.id, 512), text(outcome.summary, 64000), outcome.remaining.count <= 64, outcome.remaining.allSatisfy({ text($0) }),
                  let execution = executions.first(where: { $0.id == outcome.executionID }),
                  outcome.requirementsRevision == execution.requirementsRevision, outcome.planVersion == execution.planVersion else { throw invalid("成果版本與原執行引用不符。") }
            if let review = outcome.review {
                guard text(review.explanation), review.checks.count <= 288,
                      review.checks.allSatisfy({ text($0.criterion, 64000) && $0.evidenceIDs.count <= 64 }), review.resolvedFailures.count <= 2048 else { throw invalid("完成核對紀錄超出限制。") }
            }
        }
    }

    private func invalid(_ message: String) -> CodexTaskStoreError { .invalid(message) }
}

/// Only the private host/runtime transport can call these operations. Model
/// tools expose read/setPlan; engine reports never supply trusted evidence.
struct ProductWorkflowRequest: Codable {
    enum Operation: String, Codable { case observeInput, read, relateInput, stepProgress, setPlan, pythonPlan, pythonAttempt, pythonResult, mainResult, assessResult,
        foregroundPrepare, foregroundDelivered, foregroundAssessment, foregroundPresentationCheck, resumeContext,
        workerPending, workerPrepare, workerDelivered, workerAssessment, workerFollowup,
        continuationContext, continuationStart, continuationCheck, continuationResult, continuationAbort, continuationACK }
    var schemaVersion = 1
    let operation: Operation
    let runtimeSessionID: String
    let inputID: String?
    var taskID: UUID?
    var expectedRequirementsRevision: Int?
    var relation: AgentInputRecord.ProductRelation?
    var plan: ProductTaskPlan?
    var stepID: String?
    var stepState: ProductStepProgress.State?
    var stepDetail: String?
    var workers: [Worker]?
    var workerID: String?
    var attemptID: String?
    var continuationID: String?
    var foregroundID: String?
    var resumeAfterID: String?
    var continuationPhase: String?
    var sourceOutcomeID: String?
    var workerState: String?
    var resultID: String?
    var resultDigest: String?
    var requirementsRevision: Int?
    var planVersion: Int?
    var answerKind: String?
    var answerSummary: String?
    var offset: Int?
    var text: String?
    var speakerID: String?
    var speakerStatus: String?
    var observations: [ProductToolObservation]?
    var assessment: ProductAssessment?
    var foregroundPublication: ForegroundPublication?
    var workerPublication: WorkerResultPublication?

    struct Worker: Codable {
        let id: String
        let title: String
        let dependencies: [String]
    }
}
