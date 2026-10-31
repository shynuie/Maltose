import Foundation
extension HostState {
    public func resolveReference(principal: String, query: JSON) throws -> JSON {
        let snapshot = try contextSnapshot(principal:principal,filters:query)
        let phrase = (query["phrase"].string ?? "").lowercased()
        let chartOnly = phrase.contains("chart") || phrase.contains("圖")
        var candidates: [JSON] = []
        let maxAge = Double(query["max_age_ms"].int ?? 5000)/1000
        for s in durable.surfaces.values.sorted(by:{$0.id < $1.id}) where visibleTo(principal,s) && s.visible && (query["surface_id"].string == nil || query["surface_id"].string == s.id) && allows(principal,s,.document) {
            guard let context = live[s.id], Date().timeIntervalSince(context.observedAt) <= maxAge else {continue}
            for node in Document.nodes(s.document["root"]) where node["props"]["sensitive"].bool != true {
                let id = node["node_id"].string!
                guard !chartOnly || node["type"].string == "chart.line", query["node_id"].string == nil || query["node_id"].string == id else {continue}
                var score = 0.2; var evidence = ["visible_node"]
                if query["node_id"].string == id || phrase == id.lowercased() {score = 1; evidence = ["explicit_node_reference"]}
                else if focusedSurface == s.id && focusedNode == id {score = 0.95;evidence = ["native_focus","renderer_semantic_focus"]}
                else if allows(principal,s,.selection), context.selection["node_id"].string == id {score = 0.85;evidence = ["active_semantic_selection"]}
                else if allows(principal,s,.interaction), context.interaction["node_id"].string == id {score = 0.7;evidence = ["recent_interaction"]}
                else if node["props"]["title"].string?.lowercased() == phrase {score = 0.6;evidence = ["exact_title"]}
                candidates.append(.object(["surface_id":.s(s.id),"node_id":.s(id),"score":.number(score),"confidence":.number(score),"evidence":.array(evidence.map(JSON.s)),"context_revision":.n(revision(principal)),"document_revision":.n(s.revision),"captured_at":.s(ISO8601DateFormatter().string(from:context.observedAt)),"age_ms":.number(max(0,Date().timeIntervalSince(context.observedAt)*1000)),"fresh":.bool(true)]))
            }
        }
        candidates.sort { if $0["score"].number == $1["score"].number {return ($0["surface_id"].string! + $0["node_id"].string!) < ($1["surface_id"].string! + $1["node_id"].string!)}; return $0["score"].number! > $1["score"].number! }
        let ambiguous = candidates.count > 1 && candidates[0]["score"] == candidates[1]["score"]
        return .object(["candidates":.array(Array(candidates.prefix(20))),"ambiguous":.bool(ambiguous),"requires_clarification":.bool(ambiguous || candidates.isEmpty),"context_revision":snapshot["context_revision"],"fresh":.bool(!candidates.isEmpty),"captured_at":snapshot["captured_at"]])
    }
}
