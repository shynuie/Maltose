import Foundation

struct WorkspaceAgentToolDefinition: Codable {
    var name: String
    var command: String
    var description: String
    var inputSchema: [String: UserViewValue]
}

enum WorkspaceAgentToolDefinitions {
    private enum Field {
        case string, number, integer, boolean, strings, enumeration([String]), bands
        var schema: UserViewValue {
            switch self {
            case .string: .object(["type": .string("string")])
            case .number: .object(["type": .string("number")])
            case .integer: .object(["type": .string("integer")])
            case .boolean: .object(["type": .string("boolean")])
            case .strings: .object(["type": .string("array"), "items": Field.string.schema])
            case let .enumeration(values): .object(["type": .string("string"), "enum": .strings(values)])
            case .bands: .object(["type": .string("array"), "items": .object([
                "type": .string("object"), "additionalProperties": .boolean(false),
                "properties": .object(["firstSeriesName": Field.string.schema, "secondSeriesName": Field.string.schema, "opacity": Field.number.schema]),
                "required": .strings(["firstSeriesName", "secondSeriesName", "opacity"])
            ])])
            }
        }
    }

    static var all: [WorkspaceAgentToolDefinition] {
        var definitions: [WorkspaceAgentToolDefinition] = []
        func add(_ name: String, _ description: String, _ fields: [(String, Field)] = [], optional: Set<String> = []) {
            definitions.append(.init(name: "maltose_" + name, command: name, description: description,
                inputSchema: ["type": .string("object"), "additionalProperties": .boolean(false),
                    "properties": .object(Dictionary(uniqueKeysWithValues: fields.map { ($0.0, $0.1.schema) })),
                    "required": .strings(fields.map(\.0).filter { !optional.contains($0) })]))
        }
        let panel: [(String, Field)] = [("panelID", .string)]
        add("get_user_view", "Read the user's current workspace view. Main panels include bounded content; other panels include summaries.")
        add("list_capabilities", "List current panel IDs and their supported operations.")
        add("read_panel", "Read the bounded contents of one panel without moving, focusing or resizing it.", panel)
        add("create_panel", "Create a panel. Chat and identity are singletons. Returns panelID.", [("kind", .enumeration(WorkspacePanel.Kind.allCases.filter { $0 != .agentCoreTest }.map(\.rawValue))), ("screenID", .string)], optional: ["screenID"])
        add("close_panel", "Close a panel. Unsaved flowcharts require saving first or explicit discardChanges.", panel + [("discardChanges", .boolean)])
        add("select_panel", "Highlight a panel, retaining the current layout; extending toggles command-multiselection.", panel + [("extending", .boolean)])
        add("focus_panel", "Show a panel as the main panel. Identity cannot be focused.", panel)
        add("toggle_panel", "Toggle panel focus and global layout.", panel)
        add("set_mode", "Set one screen's layout mode.", [("screenID", .string), ("mode", .enumeration(["grid", "focused", "sidebar"]))])
        add("move_panels", "Move panels from one screen to another or reorder by row/column. Coordinates are zero-based; specify both or neither.", [("panelIDs", .strings), ("screenID", .string), ("row", .integer), ("column", .integer)], optional: ["row", "column"])
        add("grid_viewport", "Set absolute global-grid zoom and scroll offset.", [("screenID", .string), ("zoom", .number), ("scrollOffset", .number)])
        add("conversation_select_session", "Select a chat session while the chat panel is focused.", panel + [("sessionID", .string)])
        add("notes_set_text", "Replace a notes panel's text.", panel + [("text", .string)])
        add("chart_load_csv", "Load CSV text into a chart. First column is X; numeric columns are series; optional last note column provides point notes.", panel + [("csv", .string), ("sourceName", .string)])
        add("chart_open_csv", "Load a local CSV through the configured filesystem policy.", panel + [("path", .string)])
        add("chart_set_series", "Set visible chart series by their exact names.", panel + [("names", .strings)])
        add("chart_set_bands", "Set translucent fills between named chart series.", panel + [("bands", .bands)])
        add("chart_viewport", "Set chart X-axis zoom and pan.", panel + [("zoom", .number), ("pan", .number)])
        add("image_add_url", "Add an HTTP(S) image to a gallery.", panel + [("url", .string)])
        add("image_add_file", "Add a local image through the configured filesystem policy.", panel + [("path", .string)])
        add("image_select", "Select a gallery image using a zero-based index.", panel + [("index", .integer)])
        add("image_expand", "Expand an image inside a focused gallery.", panel + [("index", .integer)])
        add("image_collapse", "Return an expanded image to gallery preview.", panel)
        add("image_viewport", "Set absolute zoom and bounded pan for an expanded image.", panel + [("zoom", .number), ("panX", .number), ("panY", .number)])
        add("browser_navigate", "Navigate a browser panel to HTTP(S), a domain or a search query.", panel + [("address", .string)])
        add("browser_control", "Control browser navigation/loading, or open the offline test page.", panel + [("action", .enumeration(WorkspaceAgentCommand.BrowserAction.allCases.map(\.rawValue)))])
        add("flowchart_add_node", "Create a flowchart node and return nodeID.", panel + [("type", .enumeration(FlowchartNodeType.allCases.map(\.rawValue))), ("x", .number), ("y", .number)])
        add("flowchart_update_node", "Update a flowchart node's text and absolute position.", panel + [("nodeID", .string), ("text", .string), ("x", .number), ("y", .number)])
        add("flowchart_select_node", "Select an existing flowchart node.", panel + [("nodeID", .string), ("extending", .boolean)])
        add("flowchart_connect", "Connect two different flowchart nodes; duplicate edges are rejected.", panel + [("from", .string), ("to", .string), ("label", .string)], optional: ["label"])
        add("flowchart_delete_selection", "Delete selected flowchart nodes and their incident edges.", panel)
        add("flowchart_viewport", "Set absolute flowchart zoom and pan.", panel + [("zoom", .number), ("panX", .number), ("panY", .number)])
        add("flowchart_new", "Start an empty flowchart. Unsaved changes require explicit discardChanges.", panel + [("discardChanges", .boolean)])
        add("flowchart_open", "Open a .maltoseflow.json document through filesystem policy, with unsaved-change protection.", panel + [("path", .string), ("discardChanges", .boolean)])
        add("flowchart_save", "Save a flowchart through filesystem policy. Overwriting a file not previously opened requires its expectedSHA256; externally changed files are rejected.", panel + [("path", .string), ("expectedSHA256", .string)], optional: ["expectedSHA256"])
        add("identity_set_state", "Set the identity animation preset for an explicit UI operation.", panel + [("state", .enumeration(EntityPreset.allCases.map(\.rawValue)))])
        return definitions
    }
}
