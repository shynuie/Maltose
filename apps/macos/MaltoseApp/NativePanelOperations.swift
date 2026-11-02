import Foundation
import CryptoKit

struct NativePanelOperation: Codable, Equatable {
    enum Phase: String, Codable { case prepared, completed, failedNoChange, uncertain }
    let id: String
    let inputID: String
    let source: NativePanelSource
    let category: String
    let targets: [String]
    let commandDigest: String
    let instanceID: String
    let beforeStamp: String
    let acknowledgementToken: String
    var phase: Phase = .prepared
    var afterStamp: String?
    var responseData: Data?
    var acknowledged = false

    func hasSameOrigin(as other: Self) -> Bool {
        id == other.id && inputID == other.inputID && source == other.source && category == other.category
        && targets == other.targets && commandDigest == other.commandDigest && instanceID == other.instanceID
        && beforeStamp == other.beforeStamp && acknowledgementToken == other.acknowledgementToken
    }
}

struct NativePanelOperationReceipt: Codable {
    let id: String
    let token: String
}

@MainActor final class NativePanelOperationJournal {
    let store: CodexTaskStore
    let conversationID: String
    init(store: CodexTaskStore, conversationID: String) { self.store = store; self.conversationID = conversationID }
    var operations: [NativePanelOperation] { store.conversations.first(where: { $0.id == conversationID })?.panelOperations ?? [] }

    func prepare(_ operation: NativePanelOperation) throws {
        try store.updateConversation(conversationID) { conversation in
            var rows = conversation.panelOperations ?? []
            guard rows.count < 4096 else { throw WorkspaceAgentFailure(code: "operation_limit", message: "面板操作紀錄已達上限，保留現有內容。") }
            guard !rows.contains(where: { $0.id == operation.id }) else { throw WorkspaceAgentFailure(code: "invalid_request", message: "操作識別碼已存在，請讀回原操作結果。") }
            if let previous = rows.last(where: { row in
                row.inputID == operation.inputID && !Set(row.targets).isDisjoint(with: operation.targets)
                && (row.phase == .prepared || row.phase == .uncertain || !row.acknowledged)
            }) {
                throw WorkspaceAgentFailure(code: "outcome_unknown", message: "先前面板操作的結果尚未核對；請讀取該面板與操作回執，再決定下一步。", operationID: previous.id)
            }
            rows.append(operation); conversation.panelOperations = rows
        }
    }

    func finish(_ operation: NativePanelOperation) throws {
        try store.updateConversation(conversationID) { conversation in
            guard let index = conversation.panelOperations?.firstIndex(where: { $0.id == operation.id }),
                  conversation.panelOperations?[index].phase == .prepared else { throw CodexTaskStoreError.conflict }
            conversation.panelOperations?[index] = operation
        }
    }

    func acknowledge(_ receipts: [NativePanelOperationReceipt]) throws {
        guard !receipts.isEmpty, receipts.count <= 32 else { throw CodexTaskStoreError.conflict }
        try store.updateConversation(conversationID) { conversation in
            for receipt in receipts {
                guard let index = conversation.panelOperations?.firstIndex(where: { $0.id == receipt.id }),
                      let row = conversation.panelOperations?[index], row.acknowledgementToken == receipt.token,
                      [.completed, .failedNoChange].contains(row.phase) else { throw CodexTaskStoreError.conflict }
                conversation.panelOperations?[index].acknowledged = true
            }
        }
    }

    func canRetry(_ previous: NativePanelMutationClaim, as next: NativePanelMutationClaim) -> Bool {
        guard Self.retryLineage(previous, next), let current = next.source.product,
              let product = store.productTask(current.taskID), !product.held, !product.cancelled, product.state != .completed,
              product.requirementsRevision == current.requirementsRevision, product.planVersion == current.planVersion else { return false }
        return Self.noEffectProof(previous, operations: operations)
    }

    static func retryLineage(_ previous: NativePanelMutationClaim, _ next: NativePanelMutationClaim) -> Bool {
        guard previous.operationVersion == 1, next.operationVersion == 1, previous.inputID == next.inputID,
              previous.targetID == next.targetID, previous.category == next.category, previous.category != "save",
              previous.source.runtimeSessionID == next.source.runtimeSessionID,
              let old = previous.source.product, let current = next.source.product,
              old.taskID == current.taskID, old.requirementsRevision == current.requirementsRevision, old.planVersion == current.planVersion else { return false }
        if next.source.executor == .maltose { return next.source.continuation != nil }
        guard let execution = current.executionID, !execution.isEmpty else { return false }
        return next.source.executor == .codex && execution != old.executionID
    }

    static func noEffectProof(_ claim: NativePanelMutationClaim, operations: [NativePanelOperation]) -> Bool {
        let attempts = operations.filter { $0.inputID == claim.inputID && $0.source == claim.source && $0.targets.contains(claim.targetID) }
        return attempts.allSatisfy { $0.phase == .failedNoChange && $0.acknowledged }
    }

    static func stamp(_ text: String) -> String { SHA256.hash(data: Data(text.utf8)).map { String(format:"%02x",$0) }.joined() }
}
