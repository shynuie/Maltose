import Foundation
public struct Surface: Codable, Sendable, Identifiable, Equatable {
    public var id: String
    public var owner: String
    public var kind: String
    public var revision: Int
    public var title: String
    public var document: JSON
    public var placement: JSON
    public var visible: Bool
    public var lifecycle: String
    public var createdAt: String
    public var updatedAt: String
    public var userOverrides: JSON = .object([:])
    public var json: JSON { .object(["surface_id":.s(id),"owner_agent_id":.s(owner),"kind":.s(kind),"revision":.n(revision),"title":.s(title),"document":document,"placement":placement,"visibility":.bool(visible),"lifecycle":.s(lifecycle),"created_at":.s(createdAt),"updated_at":.s(updatedAt),"user_overrides":userOverrides]) }
}
public enum Scope: String, Codable, Sendable, CaseIterable {
    case summary, document, selection, viewport, layout, interaction, events, data
}
public struct Grant: Codable, Sendable, Equatable {
    public let surfaceID: String
    public let grantee: String
    public let scopes: Set<Scope>
    public init(surfaceID: String, grantee: String, scopes: Set<Scope>) { self.surfaceID = surfaceID; self.grantee = grantee; self.scopes = scopes }
}
public struct DurableState: Codable, Sendable {
    public var surfaces: [String:Surface] = [:]
    public var grants: [Grant] = []
    public var idempotency: [String:CachedReply] = [:]
    public init() {}
}
public struct CachedReply: Codable, Sendable { var fingerprint: JSON; var result: JSON }
public struct LiveContext: Sendable {
    public var selection: JSON = .null
    public var viewport: JSON = .null
    public var interaction: JSON = .null
    public var updated = Date()
    public var observedAt = Date()
    public var bridgeSequence = -1
}
public struct Subscription: Sendable {
    var id: String
    var principal: String
    var sessionID: String
    var surfaceID: String?
    var kinds: Set<String>
    var contextOnly: Bool
    var queue: [JSON] = []
    var sequence = 0
    var gap = false
}
public struct DataStream: Sendable {
    var owner: String
    var sequence: Int = -1
    var points: JSON = .array([])
    var stale = true
}
