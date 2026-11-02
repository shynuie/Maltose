import Foundation

extension AgentSessionCoordinator {
    func handleProductWorkflow(_ request: ProductWorkflowRequest) throws -> [String: UserViewValue] {
        guard request.schemaVersion == 1, request.runtimeSessionID == runtime.sessionID,
              runtime.state == .ready, let inputID = request.inputID,
              request.operation == .continuationAbort || request.operation == .foregroundPrepare || request.operation == .foregroundPresentationCheck || (conversation.phase == .maltoseActive && conversation.recipient == .maltose && conversation.stopRequested != true) else {
            throw CodexTaskStoreError.unavailable("共同任務操作的執行來源或交接狀態已失效。")
        }
        if request.operation == .observeInput {
            guard !inputID.isEmpty, inputID.utf8.count <= 128, let text = request.text, !text.isEmpty, text.utf8.count <= 64000,
                  let status = request.speakerStatus, status.utf8.count <= 64,
                  status != "identified" || (request.speakerID != nil && request.speakerID != "unknown") else { throw CodexTaskStoreError.invalid("語音輸入來源不正確。") }
            let observed = AgentInputRecord(id: inputID, text: text, author: .user, origin: .voice,
                speakerID: request.speakerID, speakerStatus: status, runtimeSessionID: request.runtimeSessionID, recipient: .maltose, delivery: .accepted)
            _ = try store.enqueue(observed, conversationID: conversation.id)
            capturePanelInput?(observed.id)
            return ["schemaVersion": .number(1), "inputStored": .boolean(true)]
        }
        guard let input = conversation.inputs.first(where: { $0.id == inputID }), input.delivery != .deferred else { throw CodexTaskStoreError.invalid("找不到已接納的原始輸入。") }
        let active = conversation.activeProductTaskID.flatMap(store.productTask)
        let accessible = active.map { canAccessProductTask($0, input: input) } ?? true
        switch request.operation {
        case .foregroundPresentationCheck:
            return try checkForegroundPresentation(request, input: input)
        case .workerPending: return try pendingWorkerScopes(input)
        case .workerPrepare, .workerDelivered, .workerAssessment, .workerFollowup:
            return try handleWorkerPublication(request,input:input)
        case .resumeContext:
            return try handleTaskResumption(request, input: input)
        case .foregroundPrepare, .foregroundDelivered, .foregroundAssessment:
            return try handleForegroundWorkflow(request, input: input)
        case .continuationContext, .continuationStart, .continuationCheck, .continuationResult, .continuationAbort, .continuationACK:
            return try handleProductContinuation(request, input: input)
        case .observeInput: throw CodexTaskStoreError.invalid("輸入觀察未經來源核對。")
        case .read:
            if runtime.inputScopeVersion == 0, accessible, let task = active, task.state != .completed, input.productTaskID == nil {
                try store.bindProductInput(conversationID: conversation.id, inputID: input.id, taskID: task.id)
            }
            return try productInputSnapshot(accessible ? conversation.activeProductTaskID : nil, inputID: input.id, offset: request.offset ?? 0)
        case .relateInput:
            guard runtime.inputScopeVersion == 1, let relation = request.relation, relation != .continueTask || accessible,
                  latestProductHumanInputID == input.id else { throw CodexTaskStoreError.conflict }
            try store.relateProductInput(conversationID: conversation.id, inputID: input.id, relation: relation,
                taskID: request.taskID, expectedRequirementsRevision: request.expectedRequirementsRevision)
            return try productInputSnapshot(accessible ? conversation.activeProductTaskID : nil, inputID: input.id)
        case .stepProgress:
            guard let id = request.taskID, let task = store.productTask(id), id == active?.id,
                  input.productTaskID == id, latestProductHumanInputID == input.id,
                  accessible, !task.held, !task.cancelled,
                  request.requirementsRevision == task.requirementsRevision, request.planVersion == task.planVersion,
                  let stepID = request.stepID, task.plan.steps.contains(where: { $0.id == stepID }),
                  let state = request.stepState, let detail = request.stepDetail, detail.utf8.count <= 1000 else { throw CodexTaskStoreError.conflict }
            try store.recordStepProgress(id, stepID: stepID, state: state, detail: detail)
            return try productInputSnapshot(id, inputID: input.id)
        case .setPlan, .pythonPlan:
            guard input.author != .user || latestProductHumanInputID == input.id else { throw CodexTaskStoreError.conflict }
            guard input.productRelation != .standalone else { throw CodexTaskStoreError.invalid("此輸入是獨立問答，不應變更任務計畫。") }
            if runtime.inputScopeVersion == 1, accessible, active != nil, input.productTaskID == nil, input.productRelation == nil {
                throw CodexTaskStoreError.invalid("請先判斷此輸入延續原任務、新建任務或獨立問答。")
            }
            if input.productTaskID == active?.id, active?.held == true { throw CodexTaskStoreError.invalid("原任務仍暫停，需先確認下一步。") }
            if accessible, let current = active, current.state != .completed {
                guard request.expectedRequirementsRevision == current.requirementsRevision else { throw CodexTaskStoreError.conflict }
            }
            let plan: ProductTaskPlan
            if request.operation == .pythonPlan {
                guard let workers = request.workers, (1...8).contains(workers.count), workers.allSatisfy({ UUID(uuidString: $0.id) != nil }) else {
                    throw CodexTaskStoreError.invalid("背景執行引用必須由 runtime 建立。")
                }
                plan = .init(sourceInputID: input.id, criteria: accessible ? active?.plan.criteria ?? [input.text] : [input.text],
                    steps: workers.map { .init(id: $0.id, title: $0.title, dependencies: $0.dependencies) })
            } else {
                guard let proposed = request.plan, proposed.sourceInputID == input.id else { throw CodexTaskStoreError.invalid("規劃必須引用原始人員輸入。") }
                plan = proposed
            }
            let task = try store.beginProductTask(conversationID: conversation.id, inputID: input.id, plan: plan, forceNew: !accessible)
            var bindings: [String: UserViewValue] = [:]
            if request.operation == .pythonPlan {
                for worker in request.workers! {
                    let execution = ProductExecution(id: "python:\(worker.id)", engine: .python, externalID: worker.id,
                        inputID: input.id, requirementsRevision: task.requirementsRevision, planVersion: task.planVersion, state: .prepared)
                    try store.recordProductExecution(task.id, execution)
                    bindings[worker.id] = .object(["schemaVersion": .number(1), "taskID": .string(task.id.uuidString),
                        "inputID": .string(input.id), "executionID": .string(execution.id),
                        "requirementsRevision": .number(Double(task.requirementsRevision)), "planVersion": .number(Double(task.planVersion))])
                }
            }
            var result = try productInputSnapshot(task.id, inputID: input.id)
            if !bindings.isEmpty { result["workerBindings"] = .object(bindings) }
            return result
        case .pythonAttempt:
            guard let id = request.taskID, let worker = request.workerID, UUID(uuidString: worker) != nil,
                  let attempt = request.attemptID, attempt.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
                  let task = store.productTask(id), task.conversationID == conversation.id,
                  canAccessProductTask(task, input: input), let revision = request.requirementsRevision, let version = request.planVersion else {
                throw CodexTaskStoreError.invalid("背景執行缺少已接納的來源。")
            }
            let execution = try store.recordProductWorkerAttempt(id, workerID: worker, attemptID: attempt, inputID: input.id,
                requirementsRevision: revision, planVersion: version)
            return ["schemaVersion": .number(1), "attemptBinding": .object(["schemaVersion": .number(1), "taskID": .string(id.uuidString),
                "inputID": .string(input.id), "executionID": .string(execution.id), "attemptID": .string(attempt),
                "requirementsRevision": .number(Double(revision)), "planVersion": .number(Double(version))])]
        case .pythonResult:
            guard let id = request.taskID, let task = store.productTask(id), task.conversationID == conversation.id,
                  let worker = request.workerID, var execution = task.executions.first(where: {
                      $0.id == "python:\(worker)" + (request.attemptID.map { ":\($0)" } ?? "") && $0.engine == .python && $0.externalID == worker
                  }),
                  request.requirementsRevision == execution.requirementsRevision, request.planVersion == execution.planVersion,
                  execution.inputID == input.id, let resultID = request.resultID,
                  resultID.range(of: "^[A-Za-z0-9._:-]{1,128}$", options: .regularExpression) != nil,
                  let digest = request.resultDigest, digest.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
                  let state = request.workerState, ["succeeded", "failed", "cancelled", "held"].contains(state),
                  request.attemptID == nil || (execution.turnID == request.attemptID && request.attemptID?.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil) else {
                throw CodexTaskStoreError.invalid("背景回報不屬於原來的執行引用或要求版本。")
            }
            execution.state = state == "succeeded" ? .succeeded : ["cancelled", "held"].contains(state) ? .cancelled : .failed
            let statusEvidence = ProductEvidence(id: "worker:\(resultID)", executionID: execution.id, kind: .execution,
                source: .observed, verdict: state == "succeeded" ? .passed : .unknown, detail: "Python 工作返回 \(state)，內容 SHA256：\(digest)。執行狀態不能替代需求完成。")
            let observations = request.observations ?? []
            guard observations.count <= 64, request.attemptID != nil || observations.isEmpty else { throw CodexTaskStoreError.invalid("背景證據缺少實際執行引用。") }
            let evidence = try observations.map { try $0.evidence(executionID: execution.id) }
            try store.recordProductReport(id, execution: execution, evidence: [statusEvidence] + evidence, outcome: .init(id: resultID, executionID: execution.id,
                requirementsRevision: execution.requirementsRevision, planVersion: execution.planVersion,
                reportedState: state == "cancelled" ? .cancelled : state == "failed" ? .failed : .partial,
                summary: "背景工作已返回 \(state) 回報，完成條件仍需核對。", remaining: ["核對目前需求與實際成果。"], artifactID: resultID))
            var response = try productSnapshot(id)
            let current = store.productTask(id)!
            if request.requirementsRevision != current.requirementsRevision || request.planVersion != current.planVersion || !isCurrentProductSource(input.id,task:current,resumeAfterID:request.resumeAfterID)
                || (runtime.workerResultVersion==1 && current.outcomes.last?.id != resultID && current.outcomes.last?.id != "assessment:\(resultID)") {
                response["assessmentContext"] = .object(["stale": .boolean(true)])
            } else if let saved = current.outcomes.last, saved.id == "assessment:\(resultID)",
                      saved.reportedState != .completed || current.isVerifiedComplete(saved) {
                response["assessment"] = try workflowValue(CodexTaskStore.assessment(from: saved))
            } else if current.outcomes.contains(where: { $0.id == "assessment:\(resultID)" }) {
                response["assessmentContext"] = .object(["stale": .boolean(true)])
            } else { response["assessmentContext"] = try productAssessmentContext(id) }
            return response
        case .mainResult:
            guard let id = request.taskID, let task = store.productTask(id), task.conversationID == conversation.id,
                  input.productTaskID == id, canAccessProductTask(task, input: input),
                  let version = request.requirementsRevision, version >= 1, version <= task.requirementsRevision,
                  let planVersion = request.planVersion, planVersion >= 1, planVersion <= task.planVersion,
                  let resultID = request.resultID, let summary = request.answerSummary,
                  let kind = request.answerKind, ["answer", "partial", "needs_input", "failed"].contains(kind) else { throw CodexTaskStoreError.invalid("Main 成果缺少原始要求版本。") }
            let execution = ProductExecution(id: "main:\(input.id):r\(version):p\(planVersion)", engine: .main, externalID: request.runtimeSessionID,
                inputID: input.id, requirementsRevision: version, planVersion: planVersion, state: .succeeded)
            let observations = request.observations ?? []
            guard observations.count <= 64 else { throw CodexTaskStoreError.invalid("當次工具觀察過多。") }
            let evidence = try observations.map { try $0.evidence(executionID: execution.id) }
            try store.recordProductReport(id, execution: execution, evidence: evidence, outcome: .init(id: resultID, executionID: execution.id,
                requirementsRevision: version, planVersion: planVersion,
                reportedState: kind == "needs_input" ? .needsInput : kind == "failed" ? .failed : .partial,
                summary: summary, remaining: ["尚未核對全部產品任務完成條件。"], artifactID: resultID))
            var response = try productSnapshot(id)
            let current = store.productTask(id)!
            if version != current.requirementsRevision || planVersion != current.planVersion || !isCurrentProductSource(input.id,task:current,resumeAfterID:request.resumeAfterID) {
                response["assessmentContext"] = .object(["stale": .boolean(true)])
            } else if let saved = current.outcomes.first(where: { $0.id == "assessment:\(resultID)" }),
                      current.outcomes.last?.id == saved.id,
                      saved.reportedState != .completed || current.isVerifiedComplete(saved) {
                response["assessment"] = try workflowValue(CodexTaskStore.assessment(from: saved))
            } else if current.outcomes.contains(where: { $0.id == "assessment:\(resultID)" }) {
                response["assessmentContext"] = .object(["stale": .boolean(true)])
            } else { response["assessmentContext"] = try productAssessmentContext(id) }
            return response
        case .assessResult:
            guard let id = request.taskID, let task = store.productTask(id), task.conversationID == conversation.id,
                  !hasUndeliveredWorkerResults(task),
                  isCurrentProductSource(input.id, task: task, resumeAfterID: request.resumeAfterID, continuationID: request.continuationID),
                  input.productTaskID == id, canAccessProductTask(task, input: input),
                  let resultID = request.resultID, let assessment = request.assessment,
                  let version = request.requirementsRevision, let planVersion = request.planVersion,
                  task.outcomes.contains(where: { outcome in outcome.id == resultID && (
                      outcome.executionID.hasPrefix("main:\(input.id):") || (request.continuationID != nil && outcome.executionID == "continue:\(request.continuationID!)") || task.executions.contains(where: {
                          $0.id == outcome.executionID && $0.engine == .python && $0.inputID == input.id && $0.turnID == request.attemptID && request.attemptID != nil
                      })) }) else {
                throw CodexTaskStoreError.invalid("成果核對不屬於目前的原始執行。")
            }
            if let continuationID = request.continuationID {
                guard let scope = task.continuations?.first(where: { $0.id == continuationID }), scope.foregroundID == request.foregroundID, scope.resumeAfterID == request.resumeAfterID else { throw CodexTaskStoreError.conflict }
            }
            let saved = try store.assessProductOutcome(id, outcomeID: resultID, assessment: assessment,
                expectedRequirementsRevision: version, expectedPlanVersion: planVersion)
            return ["schemaVersion": .number(1), "assessment": try workflowValue(saved)]
        }
    }

    private func productInputSnapshot(_ id: UUID?, inputID: String, offset: Int = 0) throws -> [String: UserViewValue] {
        var result = try productSnapshot(id, offset: offset)
        let input = conversation.inputs.first { $0.id == inputID }
        if runtime.inputScopeVersion == 1 {
            result["inputBound"] = .boolean(id != nil && input?.productTaskID == id)
            result["inputRelation"] = .string(input?.productRelation?.rawValue ?? "unclassified")
        }
        return result
    }

    private func workflowValue<T: Encodable>(_ object: T) throws -> UserViewValue {
        try JSONDecoder().decode(UserViewValue.self, from: JSONEncoder().encode(object))
    }

    func productAssessmentContext(_ id: UUID) throws -> UserViewValue {
        guard let task = store.productTask(id) else { throw CodexTaskStoreError.invalid("找不到核對任務。") }
        let current = Set(task.executions.filter { $0.requirementsRevision == task.requirementsRevision && $0.planVersion == task.planVersion }.map(\.id))
        let evidence = task.evidence.filter { current.contains($0.executionID) || ($0.blocksCompletion && $0.verdict == .failed) ||
            $0.invalidatesPriorEvidence == true || $0.invalidatesVerification == true }
        let unfinished = task.executions.contains { [.prepared, .running, .uncertain].contains($0.state) }
        let header: [String: UserViewValue] = ["requirementsRevision": .number(Double(task.requirementsRevision)),
            "planVersion": .number(Double(task.planVersion)), "held": .boolean(task.held || task.cancelled),
            "hasUnfinishedExecution": .boolean(unfinished),"hasUndeliveredResults": .boolean(hasUndeliveredWorkerResults(task))]
        var fields = header
        fields["criteria"] = .strings(task.completionCriteria)
        fields["evidence"] = try workflowValue(evidence)
        let value = UserViewValue.object(fields)
        let incomplete = evidence.contains { item in
            (try? JSONDecoder().decode(ProductToolObservation.self, from: Data(item.detail.utf8)))?.truncated == true
        }
        let size = try JSONEncoder().encode(value).count
        if incomplete || size > 192 * 1024 {
            fields = header; fields["complete"] = .boolean(false)
        } else { fields["complete"] = .boolean(true) }
        return .object(fields)
    }

    func canAccessProductTask(_ task: ProductTask, input: AgentInputRecord) -> Bool {
        if input.origin == .native { return true } // local UI authority, never a Memory identity
        guard let firstID = task.requirements.first?.inputID,
              let source = conversation.inputs.first(where: { $0.id == firstID }), input.origin == .voice, source.origin == .voice else { return false }
        // Unidentified speakers are not one shared owner. An unverified input
        // can inspect the plan it just created, not another unknown voice turn.
        if input.id == source.id { return true }
        return input.speakerStatus == "identified" && source.speakerStatus == "identified"
            && input.speakerID?.isEmpty == false && input.speakerID != "unknown" && input.speakerID == source.speakerID
    }

    var latestProductHumanInputID: String? {
        conversation.inputs.last(where: { $0.author == .user && $0.delivery != .deferred && $0.reviewDisposition != .dismissed })?.id
    }

    func productSnapshot(_ id: UUID?, offset: Int = 0) throws -> [String: UserViewValue] {
        guard let id, let task = store.productTask(id) else { return ["schemaVersion": .number(1), "task": .null] }
        guard offset >= 0, offset <= task.requirements.count else { throw CodexTaskStoreError.invalid("要求分頁位置不正確。") }
        func value<T: Encodable>(_ object: T) throws -> UserViewValue { try JSONDecoder().decode(UserViewValue.self, from: JSONEncoder().encode(object)) }
        let end = min(offset + 4, task.requirements.count)
        return ["schemaVersion": .number(1), "task": .object([
            "id": .string(id.uuidString), "conversationID": .string(task.conversationID), "objective": .string(task.objective),
            "state": .string(task.state.rawValue), "requirementsRevision": .number(Double(task.requirementsRevision)), "planVersion": .number(Double(task.planVersion)),
            "requirements": try value(Array(task.requirements[offset..<end])), "nextRequirementsOffset": end < task.requirements.count ? .number(Double(end)) : .null,
            "plan": try value(task.plan), "stepProgress": try value(task.stepProgress ?? []), "executions": try value(Array(task.executions.suffix(32))),
            "outcomes": try value(task.outcomes.suffix(4).map { outcome in
                UserViewValue.object(["id": .string(outcome.id), "reportedState": .string(outcome.reportedState.rawValue), "summary": .string(String(outcome.summary.prefix(2000))),
                 "requirementsRevision": .number(Double(outcome.requirementsRevision)), "planVersion": .number(Double(outcome.planVersion)),
                 "remaining": .strings(outcome.remaining), "verified": .boolean(task.isVerifiedComplete(outcome)), "artifactID": .string(outcome.artifactID ?? "")])
            }),
            "evidenceIDs": .strings(task.evidence.suffix(32).map(\.id)),
            "historyTruncated": .boolean(task.executions.count > 32 || task.outcomes.count > 4 || task.evidence.count > 32)])]
    }

    func productForCodex(_ taskID: UUID, input: AgentInputRecord) throws -> ProductTask {
        if let id = store.task(taskID)?.productTaskID, let product = store.productTask(id) {
            guard !product.cancelled else { throw CodexTaskStoreError.invalid("原任務已取消；請開始新的開發任務，不能重新使用已取消的執行。") }
            try store.bindProductInput(conversationID: conversation.id, inputID: input.id, taskID: id)
            if conversation.activeProductTaskID != id { try store.updateConversation(conversation.id) { $0.activeProductTaskID = id } }
            return store.productTask(product.id)!
        }
        let delegation = store.task(taskID)!.delegation
        let product: ProductTask
        if let current = conversation.activeProductTaskID, let existing = store.productTask(current), existing.state != .completed, !existing.cancelled {
            try store.bindProductInput(conversationID: conversation.id, inputID: input.id, taskID: current)
            product = store.productTask(current)!
        } else {
            let source = input.sourceInputID.flatMap { sourceID in conversation.inputs.first { $0.id == sourceID && $0.author == .user } } ?? input
            let plan = ProductTaskPlan(sourceInputID: source.id, criteria: delegation.acceptanceCriteria,
                                       steps: [.init(id: "codex-development", title: "Codex 開發工作")])
            product = try store.beginProductTask(conversationID: conversation.id, inputID: source.id, plan: plan)
            if source.id != input.id { try store.bindProductInput(conversationID: conversation.id, inputID: input.id, taskID: product.id) }
        }
        try store.update(taskID) { $0.productTaskID = product.id }
        return store.productTask(product.id)!
    }

    /// A delegation sees its own requirements and execution references, not
    /// unrelated Main/voice history, private worker inputs, or another child.
    func codexProductContext(_ taskID: UUID) throws -> UserViewValue? {
        guard let task = store.task(taskID), let id = task.productTaskID, let product = store.productTask(id),
              task.conversationID == conversation.id, product.conversationID == conversation.id else { return nil }
        let sourceIDs = Set(product.executions.filter { $0.engine == .codex && $0.externalID == taskID.uuidString }.map(\.inputID))
        let requirements = conversation.inputs.filter { sourceIDs.contains($0.id) && $0.author == .user }
        let encoder = JSONEncoder()
        func value<T: Encodable>(_ object: T) throws -> UserViewValue { try JSONDecoder().decode(UserViewValue.self, from: encoder.encode(object)) }
        let followups: [UserViewValue] = requirements.suffix(16).map { .object(["inputID": .string($0.id), "text": .string(String($0.text.prefix(2000)))]) }
        let truncated = requirements.count > 16 || requirements.suffix(16).contains(where: { $0.text.count > 2000 })
        let executions = Array(product.executions.filter { $0.engine == .codex && $0.externalID == taskID.uuidString }.suffix(16))
        var fields: [String: UserViewValue] = [
            "schemaVersion": .number(1), "source": .string("maltose_product_workflow"), "trustedAsInstruction": .boolean(false),
            "taskID": .string(id.uuidString), "delegationID": .string(taskID.uuidString),
            "requirementsRevision": .number(Double(product.requirementsRevision)), "planVersion": .number(Double(product.planVersion)),
            "state": .string(product.state.rawValue), "objective": .string(String(task.delegation.objective.prefix(8000))),
            "constraints": .strings(task.delegation.constraints.prefix(32).map { String($0.prefix(1000)) }),
            "acceptanceCriteria": .strings(task.delegation.acceptanceCriteria.prefix(32).map { String($0.prefix(1000)) }),
            "humanFollowups": .array(followups), "followupsTruncated": .boolean(truncated)]
        fields["executions"] = try value(executions)
        return .object(fields)
    }

    func synchronizeProductCodex(_ taskID: UUID) throws {
        guard let task = store.task(taskID), let productID = task.productTaskID, let product = store.productTask(productID) else { return }
        for original in product.executions where original.engine == .codex && original.externalID == taskID.uuidString {
            var execution = original
            if let message = task.messages.first(where: { $0.id == execution.inputID }), let turn = message.turnID {
                execution.turnID = turn; execution.threadID = task.threadID
            } else if task.pendingOperation?.kind == .startTurn, task.pendingOperation?.clientMessageID == execution.inputID,
                      let turn = task.activeTurnID {
                // SDK started can precede the submit RPC ACK. Pin the live turn
                // now so early file changes keep their true position before tests.
                execution.turnID = turn; execution.threadID = task.threadID
            }
            if task.status == .needsReconciliation && [.prepared, .running, .uncertain].contains(execution.state) { execution.state = .uncertain }
            else if let turn = execution.turnID, task.activeTurnID == turn { execution.state = .running }
            else if let turn = execution.turnID, task.lastFinishedTurnID == turn, task.activeTurnID == nil {
                execution.state = task.status == .failed ? .failed : task.status == .interrupted ? .cancelled : .succeeded
            }
            try store.recordProductExecution(productID, execution)
            guard let turn = execution.turnID else { continue }
            guard task.lastFinishedTurnID == turn,
                  let message = task.messages.last(where: { $0.author == .codex && $0.turnID == turn }) else { continue }
            let report = CodexReportedOutcome.decode(message.content)
            let summary = report?.summary.trimmingCharacters(in: .whitespacesAndNewlines)
            let usable = summary?.isEmpty == false && (summary?.utf8.count ?? 0) <= 64000
            let kind: ProductTaskOutcome.ReportedState = execution.state == .failed ? .failed : execution.state == .cancelled ? .cancelled :
                report?.kind == "completed" && usable ? .completed : report?.kind == "needs_input" ? .needsInput : .partial
            let remaining = report?.remaining ?? ["需要核對原始回報。"]
            try store.recordProductOutcome(productID, .init(id: "outcome:\(execution.id):\(turn)", executionID: execution.id,
                requirementsRevision: execution.requirementsRevision, planVersion: execution.planVersion,
                reportedState: kind, summary: usable ? summary! : "完整原始回報保存在 Codex 執行訊息中，摘要仍待核對。",
                remaining: remaining.count <= 64 && remaining.allSatisfy({ $0.utf8.count <= 16000 && !$0.isEmpty }) ? remaining : ["完整待辦清單見原始回報。"],
                artifactID: message.id))
            if report?.tests.isEmpty == false {
                try store.recordProductEvidence(productID, .init(id: "reported-tests:\(execution.id):\(turn)", executionID: execution.id,
                    kind: .report, source: .reported, verdict: .unknown, detail: "Codex 自述測試清單見 \(message.id)，此清單不是實際通過證據。"))
            }
        }
        // Preserve SDK receipt order during recovery too; grouping observations
        // by input would incorrectly move a late edit ahead of an earlier test.
        let executions = store.productTask(productID)!.executions
        for message in task.messages where message.author == .tool {
            guard let turn = message.turnID else { continue }
            let item = try? JSONDecoder().decode(UserViewValue.self, from: Data(message.content.utf8))
            let start = item?["id"]?.stringValue.flatMap { itemID in
                task.messages.first { $0.id == CodexProductObservation.originID(turn: turn, item: itemID) }
            }
            let origin = start.flatMap { try? JSONDecoder().decode(CodexProductObservationOrigin.self, from: Data($0.content.utf8)) }
            if let item, let origin,
               let execution = executions.first(where: { $0.id == origin.executionID && $0.engine == .codex && $0.externalID == taskID.uuidString }),
               execution.requirementsRevision == origin.requirementsRevision, execution.planVersion == origin.planVersion,
               item["type"]?.stringValue == origin.itemType {
                let proof = try CodexProductObservation.evidence(item: item, origin: origin, messageID: message.id,
                    worktree: task.worktreePath, scope: "codex:\(taskID.uuidString)")
                try store.recordProductEvidence(productID, proof)
            } else if let execution = executions.first(where: { $0.engine == .codex && $0.externalID == taskID.uuidString && $0.turnID == turn }) {
                // An imported terminal snapshot lacks a trustworthy start scope.
                // Preserve it without upgrading it to the newest requirement.
                try store.recordProductEvidence(productID, .init(id: "observation:\(message.id)", executionID: execution.id,
                    kind: .execution, source: .observed, verdict: .unknown,
                    detail: "完整工具紀錄保存在 \(message.id)，缺少可核對的開始來源，不作為目前要求的完成證據。",
                    scopeID: "codex:\(taskID.uuidString)", invalidatesVerification: item?["type"] == .string("fileChange")))
            }
        }
    }
}
