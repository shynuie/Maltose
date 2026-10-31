import Foundation
import CryptoKit
public struct PairingRequest:Sendable,Identifiable {
    public let id:String
    public let name:String
    public let requestedAgentID:String
    public let code:String
    public let createdAt:Date
    public let expiresAt:Date
    let claimDigest:Data
    public var json:JSON {.object(["pairing_id":.s(id),"name":.s(name),"requested_agent_id":.s(requestedAgentID),"verification_code":.s(code),"expires_at":.s(ISO8601DateFormatter().string(from:expiresAt))])}
}
private struct PairingEntry:Sendable {
    var request:PairingRequest
    var status="pending"
    var token:String?
    var agentID:String?
}
public actor PairingCoordinator {
    private var entries:[String:PairingEntry]=[:]
    public let registry:AgentRegistry
    public init(registry:AgentRegistry){self.registry=registry}
    private func prune(){entries=entries.filter {$0.value.request.expiresAt>Date()}}
    public func request(name:String,agentID:String,claim:String) throws->JSON {
        prune()
        guard entries.count<8 else {throw MUPError("quota","Too many pending pairing requests")}
        guard claim.utf8.count>=32 else {throw MUPError("invalid_pairing","Pairing proof is too short")}
        let digest=Data(SHA256.hash(data:Data(claim.utf8)))
        if let existing=entries.values.first(where:{$0.request.claimDigest == digest}) {return existing.request.json}
        guard !entries.values.contains(where:{$0.request.requestedAgentID == agentID}) else {throw MUPError("pairing_pending","This agent already has a pending pairing request")}
        let now=Date(),id=UUID().uuidString
        let request=PairingRequest(id:id,name:name,requestedAgentID:agentID,code:String(Int.random(in:100000...999999)),createdAt:now,expiresAt:now.addingTimeInterval(120),claimDigest:digest)
        entries[id]=PairingEntry(request:request)
        return request.json
    }
    public func pending()->[PairingRequest] {prune();return entries.values.filter {$0.status == "pending"}.map(\.request).sorted {$0.createdAt<$1.createdAt}}
    /// Called only by the trusted native user interface, never exposed as a remote command.
    public func approve(_ id:String) async throws {
        prune()
        guard var entry=entries[id],entry.status == "pending" else {throw MUPError("invalid_pairing","Pairing request expired")}
        // Never let a new request rotate credentials or inherit grants for an existing principal.
        entry.status="approving";entries[id]=entry
        do {
            let token=try await registry.registerNew(entry.request.requestedAgentID)
            entry.token=token;entry.agentID=entry.request.requestedAgentID;entry.status="approved"
            entries[id]=entry
        } catch {
            entry.status="denied";entries[id]=entry
            throw error
        }
    }
    public func deny(_ id:String){if var entry=entries[id] {entry.status="denied";entries[id]=entry}}
    public func poll(id:String,claim:String) throws->JSON {
        prune()
        guard var entry=entries[id],entry.request.claimDigest == Data(SHA256.hash(data:Data(claim.utf8))) else {throw MUPError("invalid_pairing","Pairing request unavailable")}
        if entry.status == "approved" {
            guard let token=entry.token,let agentID=entry.agentID else {throw MUPError("invalid_pairing","Pairing result already claimed")}
            entry.token=nil;entry.status="claimed";entries[id]=entry
            return .object(["status":.s("approved"),"token":.s(token),"principal":.s(agentID)])
        }
        return .object(["status":.s(entry.status)])
    }
}
