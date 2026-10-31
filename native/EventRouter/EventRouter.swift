import Foundation
extension HostState {
    func subscribe(_ p: JSON, principal: String, sessionID: String, contextOnly: Bool) throws -> JSON {
        if let id = p["surface_id"].string { _ = try surface(id,principal:principal) }
        guard subscriptions.values.filter({$0.principal == principal}).count < 16 else {throw MUPError("quota","Subscription quota reached")}
        let id = UUID().uuidString
        subscriptions[id] = Subscription(id:id,principal:principal,sessionID:sessionID,surfaceID:p["surface_id"].string,kinds:Set((p["kinds"].array ?? []).compactMap(\.string)),contextOnly:contextOnly)
        return .object(["subscription_id":.s(id),"context_revision":.n(revision(principal)),"resync_required":.bool(p["since_context_revision"].int != nil && p["since_context_revision"].int != revision(principal))])
    }
    func unsubscribe(_ p: JSON, principal: String, sessionID: String) throws -> JSON {
        let id = p["subscription_id"].string!
        guard let sub = subscriptions[id], sub.principal == principal, sub.sessionID == sessionID else {throw MUPError("forbidden","Subscription unavailable")}
        subscriptions.removeValue(forKey:id)
        return .object(["unsubscribed":.bool(true)])
    }
    func enqueue(_ kind: String, surface s: Surface, principal: String, changes: JSON) {
        for id in subscriptions.keys.sorted() {
            guard var sub = subscriptions[id], sub.principal == principal, sub.surfaceID == nil || sub.surfaceID == s.id, sub.kinds.isEmpty || sub.kinds.contains(kind), !sub.contextOnly || kind.hasPrefix("context.") else {continue}
            sub.sequence += 1
            let event: JSON = .object(["protocol":.s(MUP.version),"type":.s("event"),"event_id":.s(UUID().uuidString),"subscription_id":.s(sub.id),"source_agent_id":.s(s.owner),"surface_id":.s(s.id),"sequence":.n(sub.sequence),"timestamp":.s(timestamp()),"name":.s(kind),"context_revision":.n(revision(principal)),"changes":changes])
            if sub.queue.count >= 128 {sub.queue.removeAll(keepingCapacity:true);sub.gap = true}
            sub.queue.append(event);subscriptions[id] = sub
        }
    }
    public func drainEvents(principal: String, sessionID: String) -> [JSON] {
        guard sessions[sessionID] == principal else {return []}
        var result: [JSON] = controlEvents.removeValue(forKey:sessionID) ?? []
        for id in subscriptions.keys.sorted() {
            guard var sub = subscriptions[id], sub.principal == principal, sub.sessionID == sessionID else {continue}
            let allowed = sub.queue.filter { event in
                guard let sid = event["surface_id"].string, let s = durable.surfaces[sid] else {return false}
                let name = event["name"].string!
                return name.hasPrefix("context.") ? contextAllowed(principal,s,name) : allows(principal,s,name == "data.updated" ? .data : .events)
            }
            if sub.gap {
                sub.sequence += 1
                result.append(.object(["protocol":.s(MUP.version),"type":.s("event"),"event_id":.s(UUID().uuidString),"subscription_id":.s(id),"source_agent_id":.s(principal),"surface_id":.null,"sequence":.n(sub.sequence),"timestamp":.s(timestamp()),"name":.s("context.stale"),"context_revision":.n(revision(principal)),"changes":.object(["resync_required":.bool(true)])]))
                sub.gap = false
            } else {result += allowed}
            sub.queue.removeAll(keepingCapacity:true);subscriptions[id] = sub
        }
        return result
    }
}

extension HostState {
    func invalidateSurface(_ surface:Surface,principals:Set<String>) {
        live.removeValue(forKey:surface.id);bridgeEpochs.removeValue(forKey:surface.id)
        if focusedSurface == surface.id {focusedSurface=nil;focusedNode=nil}
        for principal in principals {
            contextRevisions[principal,default:0] += 1
            for sub in subscriptions.values where sub.principal == principal && (sub.surfaceID == nil || sub.surfaceID == surface.id) {
                let event:JSON = .object(["protocol":.s(MUP.version),"type":.s("event"),"event_id":.s(UUID().uuidString),"subscription_id":.s(sub.id),"source_agent_id":.s(principal),"surface_id":.null,"sequence":.n(sub.sequence+1),"timestamp":.s(timestamp()),"name":.s("context.stale"),"context_revision":.n(revision(principal)),"changes":.object(["resync_required":.bool(true)])])
                controlEvents[sub.sessionID,default:[]].append(event)
                if sub.surfaceID == surface.id {subscriptions.removeValue(forKey:sub.id)}
                else {subscriptions[sub.id]?.queue=[];subscriptions[sub.id]?.sequence += 1}
            }
        }
    }
}
