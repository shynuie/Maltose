import Foundation
/// Public, Codable domain model. Its wire representation is conformance-tested against context.schema.json.
public struct UIContextSnapshot:Codable,Sendable {
    public let contextRevision:Int
    public let capturedAt:String
    public let activeApp:String?
    public let focusedSurfaceID:String?
    public let focusedNodeID:String?
    public let privateFocus:Bool
    public let fresh:Bool
    public let resyncRequired:Bool
    public let unchanged:Bool?
    public let surfaces:[SurfaceContext]
    enum CodingKeys:String,CodingKey {
        case contextRevision="context_revision",capturedAt="captured_at",activeApp="active_app",focusedSurfaceID="focused_surface_id",focusedNodeID="focused_node_id",privateFocus="private_focus",fresh,resyncRequired="resync_required",unchanged,surfaces
    }
}
public struct SurfaceContext:Codable,Sendable {
    public let surfaceID:String
    public let ownerAgentID:String
    public let kind:String
    public let visible:Bool
    public let title:String
    public let selectedNodeIDs:[String]?
    public let selection:SemanticSelection?
    public let viewport:ChartViewport?
    public let layout:JSON?
    public let visibleNodes:[String]?
    public let interaction:JSON?
    public let documentRevision:Int
    public let contextRevision:Int
    public let redacted:Bool
    public let capturedAt:String
    public let stale:Bool
    public let dataStale:Bool?
    enum CodingKeys:String,CodingKey {
        case surfaceID="surface_id",ownerAgentID="owner_agent_id",kind,visible,title,selectedNodeIDs="selected_node_ids",selection,viewport,layout,visibleNodes="visible_nodes",interaction,documentRevision="document_revision",contextRevision="context_revision",redacted,capturedAt="captured_at",stale,dataStale="data_stale"
    }
}
public struct SemanticSelection:Codable,Sendable {
    public enum Kind:String,Codable,Sendable {case chartTimeRange="chart.time_range",node}
    public let nodeID:String
    public let kind:Kind
    public let value:[String:JSON]?
    enum CodingKeys:String,CodingKey {case nodeID="node_id",kind,value}
}
public struct ChartViewport:Codable,Sendable {
    public let nodeID:String
    public let xDomain:[JSON]
    enum CodingKeys:String,CodingKey {case nodeID="node_id",xDomain="x_domain"}
}
extension HostState {
    public func typedContext(principal:String,filters:JSON = .object([:])) throws->UIContextSnapshot {
        let value=try contextSnapshot(principal:principal,filters:filters)
        return try JSONDecoder().decode(UIContextSnapshot.self,from:value.data())
    }
}
