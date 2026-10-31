import Foundation
extension HostState {
    func revision(_ principal: String) -> Int { contextRevisions[principal,default:0] }
    func audience(_ s: Surface) -> Set<String> { Set([s.owner] + durable.grants.filter {$0.surfaceID == s.id}.map(\.grantee)) }
    func contextAllowed(_ principal: String, _ s: Surface, _ kind: String) -> Bool {
        guard visibleTo(principal,s) else { return false }
        switch kind {
        case "context.selection_changed": return allows(principal,s,.selection)
        case "context.viewport_changed": return allows(principal,s,.viewport)
        case "context.surface_moved", "context.user_override_changed": return allows(principal,s,.layout)
        default: return true
        }
    }
    func changed(_ kind: String, surfaceID: String, fields: JSON = .object([:])) {
        guard let s = durable.surfaces[surfaceID] else { return }
        for principal in audience(s) where contextAllowed(principal,s,kind) {
            contextRevisions[principal,default:0] += 1
            let changes: JSON
            if kind == "context.focus_changed" {
                let target = focusedSurface.flatMap {durable.surfaces[$0]}
                let canSee = target.map {visibleTo(principal,$0)} ?? false
                let details = target.map {allows(principal,$0,.document)} ?? false
                changes = .object(["focused_surface_id":canSee ? focusedSurface.map(JSON.s) ?? .null : .null,"focused_node_id":canSee && details ? focusedNode.map(JSON.s) ?? .null : .null])
            } else if kind == "context.stale",fields.object?["data_stale"] != nil,!allows(principal,s,.data) {changes = .object([:])} else { changes = fields }
            enqueue(kind, surface:s, principal:principal, changes:changes)
        }
    }
    public func contextSnapshot(principal: String, filters: JSON = .object([:])) throws -> JSON {
        let surfaceID = filters["surface_id"].string
        if let surfaceID { _ = try surface(surfaceID,principal:principal) }
        let include = Set((filters["include"].array ?? ["focus","selection","viewport","layout","visible_nodes","interaction"].map(JSON.s)).compactMap(\.string))
        let maxAge = Double(filters["max_age_ms"].int ?? 5000) / 1000
        let all = durable.surfaces.values.filter { visibleTo(principal,$0) && (surfaceID == nil || surfaceID == $0.id) }.sorted {$0.id < $1.id}
        var fresh = true
        let surfaces: [JSON] = all.map { s in
            let context = live[s.id]
            let stale = context == nil || Date().timeIntervalSince(context!.observedAt) > maxAge
            fresh = fresh && !stale
            var json: JSON = .object(["surface_id":.s(s.id),"owner_agent_id":.s(s.owner),"kind":.s(s.kind),"visible":.bool(s.visible),"title":.s(s.title),"document_revision":.n(s.revision),"context_revision":.n(revision(principal)),"redacted":.bool(s.owner != principal),"captured_at":.s(context.map { ISO8601DateFormatter().string(from:$0.observedAt) } ?? s.updatedAt),"stale":.bool(stale)])
            if allows(principal,s,.data) {
                let ids=Document.nodes(s.document["root"]).compactMap {$0["props"]["data_id"].string}
                json["data_stale"] = .bool(ids.contains {streams[s.owner+":"+$0]?.stale ?? true})
            }
            if include.contains("selection"), allows(principal,s,.selection) {
                json["selection"] = context?.selection ?? .null
                json["selected_node_ids"] = .array(context?.selection["node_id"].string.map {[.s($0)]} ?? [])
            }
            if include.contains("viewport"), allows(principal,s,.viewport) { json["viewport"] = context?.viewport ?? .null }
            if include.contains("layout"), allows(principal,s,.layout) { json["layout"] = s.placement }
            if include.contains("visible_nodes"), allows(principal,s,.document) { json["visible_nodes"] = .array(s.visible ? Document.nodes(s.document["root"]).filter {$0["props"]["sensitive"].bool != true}.compactMap {$0["node_id"].string}.map(JSON.s) : []) }
            if include.contains("interaction"), allows(principal,s,.interaction) { json["interaction"] = context?.interaction ?? .null }
            return json
        }
        let focused = focusedSurface.flatMap { durable.surfaces[$0] }
        let focusVisible = focused.map {visibleTo(principal,$0) && (surfaceID == nil || surfaceID == $0.id)} ?? false
        let focusDetails = focused.map {allows(principal,$0,.document)} ?? false
        let requestedFocus = include.contains("focus")
        let since = filters["since_context_revision"].int
        return .object(["context_revision":.n(revision(principal)),"captured_at":.s(timestamp()),"active_app":activeApp ? .s("Maltose UI Host") : .null,"focused_surface_id":requestedFocus && focusVisible ? focusedSurface.map(JSON.s) ?? .null : .null,"focused_node_id":requestedFocus && focusVisible && focusDetails ? focusedNode.map(JSON.s) ?? .null : .null,"private_focus":.bool(requestedFocus && activeApp && focused != nil && !focusVisible),"fresh":.bool(fresh),"resync_required":.bool(since != nil && since != revision(principal)),"unchanged":.bool(since == revision(principal)),"surfaces":.array(surfaces)])
    }
}
