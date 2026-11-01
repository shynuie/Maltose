import Foundation

struct AgentInputRecord: Codable, Equatable, Identifiable {
    enum Delivery: String, Codable { case queued, dispatching, accepted, uncertain, deferred }
    enum ReviewDisposition: String, Codable { case movedToDraft, dismissed }
    let id: String
    let text: String
    let author: CodexMessageAuthor
    let origin: CodexMessageOrigin
    let speakerID: String?
    let speakerStatus: String?
    let runtimeSessionID: String?
    var recipient: AgentRecipient
    var delivery: Delivery = .queued
    var taskID: UUID?
    var reviewDisposition: ReviewDisposition? = nil
}

struct AgentConversationState: Codable, Equatable, Identifiable {
    let id: String
    var recipient: AgentRecipient = .maltose
    var phase: AgentControlState = .maltoseActive
    var activeTaskID: UUID?
    var inputs: [AgentInputRecord] = []
    /// Reserved event high watermark; unused sequence numbers may be skipped after a crash.
    var sequence = 0
    var lastReportedTurnID: String?
    var pendingQuestionID: String?
    var lastDeliveredQuestionID: String?
    var issue: String?
    var workspaceTaskID: UUID?
    var repositoryPath: String?
    var worktreePath: String?
    var delegation: CodexDelegation?
    var stopRequested: Bool? = nil
}
