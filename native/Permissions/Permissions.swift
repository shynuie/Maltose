import Foundation
extension HostState {
    /// Trusted local UI only. Remote agents cannot create or modify grants.
    public func setGrant(surfaceID: String, grantee: String, scopes: Set<Scope>) throws {
        guard let s = durable.surfaces[surfaceID], s.owner != grantee else {throw MUPError("invalid_grant","Grant target unavailable")}
        let old = durable
        durable.grants.removeAll {$0.surfaceID == surfaceID && $0.grantee == grantee}
        if !scopes.isEmpty {durable.grants.append(Grant(surfaceID:surfaceID,grantee:grantee,scopes:scopes))}
        do {try store.save(durable,principal:"local.user",action:scopes.isEmpty ? "grant.revoke" : "grant.set")} catch {durable = old;throw error}
        // Send content-free termination markers, then discard all queued old data.
        for sub in subscriptions.values where sub.principal == grantee {
            let event:JSON = .object(["protocol":.s(MUP.version),"type":.s("event"),"event_id":.s(UUID().uuidString),"subscription_id":.s(sub.id),"source_agent_id":.s(grantee),"surface_id":.null,"sequence":.n(sub.sequence+1),"timestamp":.s(timestamp()),"name":.s("context.permission_changed"),"context_revision":.n(revision(grantee)+1),"changes":.object(["subscription_terminated":.bool(true),"resync_required":.bool(true)])])
            controlEvents[sub.sessionID,default:[]].append(event)
            if controlEvents[sub.sessionID,default:[]].count>16 {controlEvents[sub.sessionID]=[event]}
        }
        subscriptions = subscriptions.filter {$0.value.principal != grantee}
        replies = replies.filter {!$0.key.hasPrefix(grantee + ":")}
        contextRevisions[grantee,default:0] += 1
    }
    public func grantsForHost() -> [Grant] {durable.grants}
}
