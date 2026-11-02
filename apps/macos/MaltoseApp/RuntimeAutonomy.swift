import Foundation

struct RuntimeAutonomySnapshot: Codable, Equatable {
    enum State: String, Codable { case active, pausing, paused, closed }
    var state: State
    var ownerID: String?
    var leaseID: String?
    var epoch: Int
    var version: Int
    var activities: [String: Int]
    var inFlight: Int

    func validate() throws {
        guard epoch >= 0, version >= 0, inFlight >= 0, activities.values.allSatisfy({ $0 > 0 }),
              activities.values.reduce(0, +) == inFlight else {
            throw RuntimeRequestError.rejected("主 Agent 執行權計數不正確。")
        }
        switch state {
        case .active:
            guard ownerID == nil, leaseID == nil else { throw RuntimeRequestError.rejected("主 Agent 執行權來源不正確。") }
        case .pausing, .paused:
            guard ownerID?.isEmpty == false, leaseID?.isEmpty == false,
                  (state == .paused ? inFlight == 0 : inFlight > 0) else {
                throw RuntimeRequestError.rejected("主 Agent 尚未提供有效的交接狀態。")
            }
        case .closed: break
        }
    }
}

enum RuntimeRequestError: Error, LocalizedError {
    case unavailable, rejected(String), outcomeUnknown(String)
    var errorDescription: String? {
        switch self {
        case .unavailable: "主 Agent 尚未連線。"
        case let .rejected(message): message
        case let .outcomeUnknown(method): "尚無法確認主 Agent 的 \(method) 結果；請先讀回狀態，避免重複執行。"
        }
    }
}
