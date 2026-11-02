import Foundation
import CryptoKit

/// A runtime-produced answer, bound to its real input before journal/UI writes.
/// This is delivery metadata, never speaker identity or permission to run work.
struct ForegroundPublication: Codable, Equatable {
    let publicationID: String
    let inputID: String
    let messageID: String
    let title: String
    let markdownSHA256: String
    let createDocument: Bool
    let producerSessionID: String
    var deliverySessionID: String
    var taskID: UUID?
    var requirementsRevision: Int?
    var planVersion: Int?
    var state = "prepared"
    var assessment: Assessment?
    var chart: ResultChart? = nil
    var answerKind: String? = nil

    struct Assessment: Codable, Equatable {
        let title: String
        let markdownSHA256: String
    }

    static func digest(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func validate() throws {
        try chart?.validate()
        func bounded(_ text: String, _ count: Int) -> Bool {
            !text.isEmpty && text.utf8.count <= count && text.rangeOfCharacter(from: .controlCharacters) == nil
        }
        guard publicationID.range(of: "^main-result:[a-f0-9]{32}$", options: .regularExpression) != nil,
              bounded(inputID, 128), bounded(messageID, 128), bounded(title, 200),
              producerSessionID.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              deliverySessionID.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              markdownSHA256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              ["prepared", "delivered", "superseded"].contains(state),
              answerKind == nil || ["answer", "partial", "needs_input", "failed"].contains(answerKind!),
              (taskID == nil && requirementsRevision == nil && planVersion == nil) ||
                (taskID != nil && (requirementsRevision ?? 0) > 0 && (planVersion ?? 0) > 0) else { throw CodexTaskStoreError.conflict }
        if let assessment {
            guard bounded(assessment.title, 200), assessment.markdownSHA256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { throw CodexTaskStoreError.conflict }
        }
    }
    func sameSource(as other: Self) -> Bool {
        var left = self, right = other
        left.deliverySessionID = ""; right.deliverySessionID = ""
        left.state = ""; right.state = ""
        left.assessment = nil; right.assessment = nil
        left.answerKind = nil; right.answerKind = nil
        return left == right
    }
    func matches(_ record: ResultDeliveryRecord) -> Bool {
        if record.publicationID == publicationID {
            return record.chart == chart && record.messageID == messageID && record.title == title && record.createDocument == createDocument && Self.digest(record.markdown) == markdownSHA256
        }
        return record.chart == nil && record.publicationID == publicationID + ":assessment" && record.messageID == record.publicationID && !record.createDocument &&
            record.title == assessment?.title && Self.digest(record.markdown) == assessment?.markdownSHA256
    }
}

extension AgentSessionCoordinator {
    func checkForegroundPresentation(_ request: ProductWorkflowRequest, input: AgentInputRecord) throws -> [String: UserViewValue] {
        guard runtime.visualPlanningVersion == 1, input.author == .user, let identity = request.resultID,
              identity.range(of: "^main-result:[a-f0-9]{32}$", options: .regularExpression) != nil else { throw CodexTaskStoreError.conflict }
        var current = latestProductHumanInputID == input.id && conversation.stopRequested != true &&
            !conversation.inputs.contains(where: { $0.id != input.id && ($0.delivery == .queued || $0.delivery == .dispatching) })
        if let id = request.taskID {
            guard input.productTaskID == id, let task = store.productTask(id), canAccessProductTask(task, input: input) else { throw CodexTaskStoreError.conflict }
            current = current && conversation.activeProductTaskID == id && !task.held && !task.cancelled &&
                task.requirementsRevision == request.requirementsRevision && task.planVersion == request.planVersion
        }
        let unpublished = !(conversation.foregroundPublications ?? []).contains(where: { $0.publicationID == identity })
        return ["schemaVersion": .number(1), "superseded": .boolean(!current),
                "current": .boolean(current && unpublished && runtime.autonomy?.state == .active && conversation.phase == .maltoseActive && conversation.recipient == .maltose)]
    }

    private func checkForegroundSource(_ source: ForegroundPublication) throws {
        guard conversation.stopRequested != true, source.state != "superseded", latestProductHumanInputID == source.inputID,
              !conversation.inputs.contains(where: { $0.id != source.inputID && ($0.delivery == .queued || $0.delivery == .dispatching) }) else { throw CodexTaskStoreError.conflict }
        if let id = source.taskID {
            guard let task = store.productTask(id), task.conversationID == conversation.id, conversation.activeProductTaskID == id,
                  !task.held, !task.cancelled, task.requirementsRevision == source.requirementsRevision, task.planVersion == source.planVersion else { throw CodexTaskStoreError.conflict }
        }
    }

    func checkForegroundPublication(_ source: ForegroundPublication) throws {
        try checkForegroundSource(source)
        guard runtime.state == .ready, source.deliverySessionID == runtime.sessionID, runtime.autonomy?.state == .active,
              conversation.phase == .maltoseActive, conversation.recipient == .maltose else { throw CodexTaskStoreError.conflict }
    }

    func validateForegroundPublication(_ record: ResultDeliveryRecord) throws {
        guard record.publicationID.hasPrefix("main-result:") else { return }
        let root = record.publicationID.hasSuffix(":assessment") ? String(record.publicationID.dropLast(":assessment".count)) : record.publicationID
        guard record.conversationID == conversation.id, let source = conversation.foregroundPublications?.first(where: { $0.publicationID == root }),
              source.matches(record) else { throw CodexTaskStoreError.conflict }
        try checkForegroundPublication(source)
    }

    func handleForegroundWorkflow(_ request: ProductWorkflowRequest, input: AgentInputRecord) throws -> [String: UserViewValue] {
        guard runtime.foregroundResultVersion == 1, input.author == .user else { throw CodexTaskStoreError.conflict }
        if request.operation == .foregroundPrepare {
            guard var source = request.foregroundPublication, source.inputID == input.id,
                  source.deliverySessionID == request.runtimeSessionID, source.assessment == nil,
                  input.origin != .voice || input.runtimeSessionID == source.producerSessionID else { throw CodexTaskStoreError.conflict }
            try source.validate()
            source.state = "prepared"
            source.answerKind = request.answerKind
            if let previous = conversation.foregroundPublications?.first(where: { $0.publicationID == source.publicationID }) {
                guard previous.sameSource(as: source) else { throw CodexTaskStoreError.conflict }
                source.state = previous.state; source.assessment = previous.assessment; source.answerKind = previous.answerKind
            }
            if let id = source.taskID {
                guard input.productTaskID == id, let task = store.productTask(id), canAccessProductTask(task, input: input),
                      task.conversationID == conversation.id, let revision = source.requirementsRevision, revision <= task.requirementsRevision,
                      let version = source.planVersion, version <= task.planVersion, let kind = request.answerKind,
                      ["answer", "partial", "needs_input", "failed"].contains(kind), let summary = request.answerSummary else { throw CodexTaskStoreError.conflict }
                let execution = ProductExecution(id: "main:\(input.id):r\(revision):p\(version)", engine: .main, externalID: source.producerSessionID,
                    inputID: input.id, requirementsRevision: revision, planVersion: version, state: .succeeded)
                let observations = request.observations ?? []
                guard observations.count <= 64 else { throw CodexTaskStoreError.conflict }
                var evidence = try observations.map { try $0.evidence(executionID: execution.id) }
                if let boundary = try panelActionBoundaryEvidence(source, executionID: execution.id) { evidence.append(boundary) }
                try store.recordProductReport(id, execution: execution, evidence: evidence,
                    outcome: .init(id: source.publicationID, executionID: execution.id, requirementsRevision: revision, planVersion: version,
                        reportedState: kind == "needs_input" ? .needsInput : kind == "failed" ? .failed : .partial,
                        summary: summary, remaining: ["尚未核對全部產品任務完成條件。"], artifactID: source.publicationID))
            }
            let current = (try? checkForegroundPublication(source)) != nil
            let superseded = (try? checkForegroundSource(source)) == nil
            if superseded && source.state != "delivered" { source.state = "superseded" }
            try store.saveForegroundPublication(source, conversationID: conversation.id)
            return ["schemaVersion": .number(1), "current": .boolean(current), "superseded": .boolean(superseded)]
        }
        guard let id = request.resultID, let source = conversation.foregroundPublications?.first(where: { $0.publicationID == id }), source.inputID == input.id else { throw CodexTaskStoreError.conflict }
        try checkForegroundPublication(source)
        if request.operation == .foregroundAssessment {
            guard let assessment = request.foregroundPublication?.assessment, let taskID = source.taskID,
                  let outcome = store.productTask(taskID)?.outcomes.last, outcome.id == "assessment:\(id)", let actual = outcome.assessment else { throw CodexTaskStoreError.conflict }
            var body = "任務核對：" + actual.summary
            if !actual.remaining.isEmpty { body += "\n\n尚待處理：\n" + actual.remaining.map { "• " + $0 }.joined(separator: "\n") }
            guard assessment.title == "任務核對", assessment.markdownSHA256 == ForegroundPublication.digest(body) else { throw CodexTaskStoreError.conflict }
            var updated = source; updated.assessment = assessment
            try updated.validate(); try store.saveForegroundPublication(updated, conversationID: conversation.id)
            return ["schemaVersion": .number(1)]
        }
        guard request.operation == .foregroundDelivered, let saved = readResultPublication?(id), saved.conversationID == conversation.id, source.matches(saved),
              !saved.createDocument || saved.panelApplied || saved.closed,
              saved.chart == nil || saved.chartApplied == true || saved.chartClosed == true else { throw CodexTaskStoreError.conflict }
        var updated = source; updated.state = "delivered"
        try store.saveForegroundPublication(updated, conversationID: conversation.id)
        guard let taskID = source.taskID else { return ["schemaVersion": .number(1)] }
        let executionID = "main:\(input.id):r\(source.requirementsRevision!):p\(source.planVersion!)"
        try store.recordProductEvidence(taskID, answerDeliveryEvidence(saved, executionID: executionID))
        let task = store.productTask(taskID)!
        if let assessment = task.outcomes.last, assessment.id == "assessment:\(id)", assessment.reportedState != .completed || task.isVerifiedComplete(assessment) {
            let data = try JSONEncoder().encode(CodexTaskStore.assessment(from: assessment))
            return ["schemaVersion": .number(1), "assessment": try JSONDecoder().decode(UserViewValue.self, from: data)]
        }
        if task.outcomes.contains(where: { $0.id == "assessment:\(id)" }) {
            return ["schemaVersion": .number(1), "assessmentContext": .object(["stale": .boolean(true)])]
        }
        return ["schemaVersion": .number(1), "assessmentContext": try productAssessmentContext(taskID)]
    }
    func panelActionBoundaryEvidence(_ source: ForegroundPublication, executionID: String) throws -> ProductEvidence? {
        guard let taskID = source.taskID, let task = store.productTask(taskID) else { return nil }
        let id = "panel-boundary:\(source.publicationID)"
        if let previous = task.evidence.first(where: { $0.id == id }) {
            guard previous.executionID == executionID else { throw CodexTaskStoreError.conflict }
            return previous // Immutable historical boundary, including after restart or later actions.
        }
        // A legacy report has no sealed boundary. Never retroactively certify it.
        guard !task.outcomes.contains(where: { $0.id == source.publicationID }) else { return nil }
        var detail = readPanelActionBoundary?(source.inputID, source.producerSessionID) ?? [
            "kind": .string("native_panel_action_boundary"), "complete": .boolean(false),
            "noAcceptedExistingPanelActions": .boolean(false),
            "limitation": .string("原輸入快照、runtime 或受控入口不可核對，不能推定沒有操作舊面板。")]
        detail["publicationID"] = .string(source.publicationID)
        detail["executionID"] = .string(executionID)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        return .init(id: id, executionID: executionID, kind: .artifact, source: .observed,
            verdict: detail["complete"] == .boolean(true) ? .passed : .unknown,
            detail: String(decoding: try encoder.encode(detail), as: UTF8.self), scopeID: id)
    }

    func answerDeliveryEvidence(_ saved: ResultDeliveryRecord, executionID: String) throws -> ProductEvidence {
        guard saved.conversationID == conversation.id,
              !saved.createDocument || saved.panelApplied || saved.closed,
              saved.chart == nil || saved.chartApplied == true || saved.chartClosed == true else { throw CodexTaskStoreError.conflict }
        let detail: [String: UserViewValue] = ["kind": .string("answer_delivery"), "publicationID": .string(saved.publicationID),
            "sha256": .string(ForegroundPublication.digest(saved.markdown)), "content": .string(saved.markdown),
            "documentApplied": .boolean(saved.panelApplied), "chartApplied": .boolean(saved.chartApplied == true),
            "panelWriteScope": .string("publication_owned_panels_only"),
            "documentPanelID": saved.panelID.map(UserViewValue.string) ?? .null,
            "chartPanelID": saved.chartPanelID.map(UserViewValue.string) ?? .null,
            "panelScopeNote": .string("Applied 只指本 publication 衍生 ID 的成果面板；此交付不寫入其範圍外的舊面板。其他工具操作需另看其回執。"),
            "limitation": .string("這只證明實際文字與面板交付，不能證明內容聲稱的功能、外部來源或測試已實現。")]
        return .init(id: "delivered:\(saved.publicationID)", executionID: executionID, kind: .artifact, source: .observed,
            verdict: .passed, detail: String(decoding: try JSONEncoder().encode(detail), as: UTF8.self), scopeID: "answer-delivery:\(saved.publicationID)")
    }

}
