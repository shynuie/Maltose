import Foundation
import CryptoKit

extension AgentSessionCoordinator {
    func installPanelPolicy(_ policy: NativePanelPolicy) {
        let journal = NativePanelOperationJournal(store: store, conversationID: conversation.id)
        policy.operationJournal = journal
        policy.operationProtocolEnabled = { [weak self] in self?.runtime.panelOperationVersion == 1 }
        policy.canRetryMutation = { [weak self] previous, next in
            guard let self, (try? self.validatePanelSource(next.source)) != nil,
                  let saved = self.conversation.panelMutationClaims?.last(where: { $0.inputID == previous.inputID && $0.targetID == previous.targetID && $0.category == previous.category }),
                  saved.source == previous.source else { return false }
            return journal.canRetry(saved, as: next)
        }
        capturePanelInput = { [weak policy, weak self] id in
            policy?.captureHumanInput(id, runtimeSessionID: self?.runtime.state == .ready ? self?.runtime.sessionID : nil)
        }
        readPanelActionBoundary = { [weak policy, weak self] inputID, producerSessionID in
            guard let self, let policy, self.runtime.state == .ready,
                  self.runtime.sessionID == producerSessionID, self.runtime.panelPolicyVersion == 1,
                  self.runtime.panelOperationVersion == 1 else { return nil }
            return policy.actionBoundary(inputID: inputID, runtimeSessionID: producerSessionID,
                claims: self.conversation.panelMutationClaims ?? [], operations: self.conversation.panelOperations ?? [])
        }
        policy.validateSource = { [weak self] source in
            guard let self else { throw CodexTaskStoreError.conflict }
            return try self.validatePanelSource(source)
        }
        policy.assessIntent = { [weak self] context, source in
            guard let self else { throw CodexTaskStoreError.conflict }
            _ = try self.validatePanelSource(source)
            var params: [String: UserViewValue] = ["context": .object(context), "executor": .string(source.executor.rawValue),
                "runtimeSessionID": .string(source.runtimeSessionID)]
            if source.executor == .codex {
                params["ownerID"] = .string(Self.controlOwner)
                params["leaseID"] = source.leaseID.map(UserViewValue.string) ?? .null
            }
            let response = try await self.runtime.call("assess_panel_intent", params: params, timeout: .seconds(65))
            _ = try self.validatePanelSource(source)
            return try JSONDecoder().decode(NativePanelIntent.self, from: JSONEncoder().encode(response))
        }
        policy.claimMutation = { [weak self] requested in
            guard let self, let first = requested.first else { throw CodexTaskStoreError.conflict }
            let human = try self.validatePanelSource(first.source)
            guard requested.allSatisfy({ $0.source == first.source && $0.inputID == human.inputID }) else { throw CodexTaskStoreError.conflict }
            try self.store.updateConversation(self.conversation.id) { conversation in
                var claims = conversation.panelMutationClaims ?? []
                for claim in requested {
                    if claims.contains(where: { $0.inputID == claim.inputID && $0.targetID == claim.targetID && $0.category == claim.category && $0.source == claim.source && $0.operationVersion == claim.operationVersion }) { continue }
                    if let previous = claims.last(where: { $0.inputID == claim.inputID && $0.targetID == claim.targetID && $0.category == claim.category }) {
                        if previous == claim { continue }
                        guard claim.autonomous == true && claim.category != "save" || journal.canRetry(previous, as: claim) else { throw WorkspaceAgentFailure(code: "update_scope_expired", message: "先前操作不是已核對的無變更失敗，不能重新使用修改許可。") }
                    }
                    guard claims.count < 1024 else { throw WorkspaceAgentFailure(code: "panel_limit", message: "面板修改來源紀錄已達上限，保留現有面板。") }
                    claims.append(claim)
                }
                conversation.panelMutationClaims = claims
            }
        }
    }

    func currentCodexPanelSource(taskID: UUID, turnID: String, lease: String) throws -> NativePanelSource {
        guard let runtimeID = runtime.sessionID, let task = store.task(taskID), task.activeTurnID == turnID,
              let input = conversation.inputs.last(where: { input in
                  input.taskID == taskID && input.recipient == .codex && [.dispatching, .accepted, .uncertain].contains(input.delivery)
                  && task.messages.contains(where: { $0.id == input.id && ($0.turnID == turnID || task.pendingOperation?.clientMessageID == input.id) })
              }) else { throw CodexTaskStoreError.conflict }
        guard let productID = task.productTaskID, let product = store.productTask(productID),
              let execution = product.executions.last(where: { $0.engine == .codex && $0.externalID == taskID.uuidString && $0.inputID == input.id }) else {
            throw CodexTaskStoreError.conflict
        }
        let key = "\(codex.connection.connectionID):\(taskID):\(turnID):\(input.id)"
        let scope = "codex:" + SHA256.hash(data: Data(key.utf8)).map { String(format:"%02x",$0) }.joined()
        return .init(runtimeSessionID: runtimeID, executor: .codex, inputID: input.id, scopeID: scope,
                     product: .init(taskID: productID, requirementsRevision: execution.requirementsRevision,
                                    planVersion: execution.planVersion, executionID: execution.id),
                     taskID: taskID, turnID: turnID, connectionID: codex.connection.connectionID, leaseID: lease)
    }

    func validatePanelSource(_ source: NativePanelSource) throws -> NativePanelHumanContext {
        guard runtime.state == .ready, runtime.sessionID == source.runtimeSessionID, conversation.stopRequested != true,
              let input = conversation.inputs.first(where: { $0.id == source.inputID }), input.delivery != .deferred,
              input.reviewDisposition != .dismissed else { throw CodexTaskStoreError.conflict }
        let human: AgentInputRecord
        let canRead: Bool
        switch source.executor {
        case .maltose:
            guard conversation.phase == .maltoseActive, conversation.recipient == .maltose,
                  runtime.autonomy?.state == .active, input.author == .user,
                  source.controlEpoch == runtime.autonomy?.epoch,
                  source.taskID == nil, source.turnID == nil, source.connectionID == nil, source.leaseID == nil else { throw CodexTaskStoreError.conflict }
            try validatePanelProduct(source, input: input)
            if let continuation = source.continuation {
                guard continuation.inputID == input.id else { throw CodexTaskStoreError.conflict }
                try validatePanelContinuation(continuation)
            } else {
                guard latestProductHumanInputID == input.id else { throw CodexTaskStoreError.conflict }
            }
            human = input
            canRead = true // Standing UI access grant; never a Memory/filesystem identity.
        case .codex:
            guard let id = source.taskID, let turn = source.turnID, let lease = source.leaseID,
                  source.continuation == nil, source.controlEpoch == nil, source.connectionID == codex.connection.connectionID,
                  conversation.phase == .codexDirect, conversation.recipient == .codex, conversation.activeTaskID == id,
                  runtime.autonomy?.state == .paused, runtime.autonomy?.ownerID == Self.controlOwner, runtime.autonomy?.leaseID == lease,
                  try currentCodexPanelSource(taskID: id, turnID: turn, lease: lease) == source else { throw CodexTaskStoreError.conflict }
            try validatePanelProduct(source, input: input)
            if input.author == .user { human = input }
            else {
                guard input.origin == .delegation, let original = input.sourceInputID,
                      let record = conversation.inputs.first(where: { $0.id == original && $0.author == .user }) else { throw CodexTaskStoreError.conflict }
                human = record
            }
            guard latestProductHumanInputID == human.id else { throw CodexTaskStoreError.conflict }
            canRead = true // Codex shares panel access while its actual paused lease is current.
        }
        return .init(inputID: human.id, text: human.text, canReadExisting: canRead)
    }

    private func validatePanelProduct(_ source: NativePanelSource, input: AgentInputRecord) throws {
        guard let id = input.productTaskID else {
            guard source.product == nil, source.continuation == nil, source.executor == .maltose else { throw CodexTaskStoreError.conflict }
            return
        }
        guard let reference = source.product, reference.taskID == id,
              let product = store.productTask(id), product.conversationID == conversation.id,
              conversation.activeProductTaskID == id, !product.held, !product.cancelled,
              reference.requirementsRevision == product.requirementsRevision, reference.planVersion == product.planVersion else {
            throw WorkspaceAgentFailure(code: "task_scope_changed", message: "任務已暫停、取消或變更版本，本次面板操作未套用。")
        }
        if source.executor == .codex {
            guard let executionID = reference.executionID, let taskID = source.taskID,
                  let execution = product.executions.first(where: { $0.id == executionID }), execution.engine == .codex,
                  execution.externalID == taskID.uuidString, execution.inputID == input.id,
                  [.prepared, .running].contains(execution.state),
                  execution.requirementsRevision == reference.requirementsRevision, execution.planVersion == reference.planVersion else { throw CodexTaskStoreError.conflict }
        } else {
            guard reference.executionID == nil else { throw CodexTaskStoreError.conflict }
        }
    }
}
