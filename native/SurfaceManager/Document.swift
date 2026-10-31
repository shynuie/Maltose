import Foundation
public enum Document {
    public static func nodes(_ root: JSON) -> [JSON] { [root] + (root["children"].array ?? []).flatMap { nodes($0) } }
    static func validateNode(_ node: JSON, parentType: String? = nil) throws {
        let type = node["type"].string ?? ""
        let props = node["props"]
        let children = node["children"].array ?? []
        let primitive = ["canvas.rect", "canvas.ellipse", "canvas.triangle", "canvas.text"].contains(type)
        if primitive {
            guard parentType == "canvas",
                  let x=props["x"].number, (0.0...4096.0).contains(x),
                  let y=props["y"].number, (0.0...4096.0).contains(y),
                  let width=props["width"].number, (1.0...4096.0).contains(width),
                  let height=props["height"].number, (1.0...4096.0).contains(height),
                  children.isEmpty else { throw MUPError("invalid_document", "Canvas elements require bounded geometry inside a canvas") }
            if let label=props["label"].string, label.count>2048 { throw MUPError("invalid_document", "Canvas label exceeds 2048 characters") }
        } else if type == "canvas" {
            guard parentType != "canvas",
                  let width=props["width"].number, (1.0...4096.0).contains(width),
                  let height=props["height"].number, (1.0...4096.0).contains(height) else { throw MUPError("invalid_document", "Canvas requires bounded width and height") }
            guard children.allSatisfy({ child in
                let p=child["props"]
                guard ["canvas.rect", "canvas.ellipse", "canvas.triangle", "canvas.text"].contains(child["type"].string ?? ""),
                      let x=p["x"].number, let y=p["y"].number, let w=p["width"].number, let h=p["height"].number else { return false }
                return x+w<=width && y+h<=height
            }) else { throw MUPError("invalid_document", "Canvas elements must be typed and fit inside the canvas") }
        } else if type != "stack", !children.isEmpty {
            throw MUPError("invalid_document", "Only stacks and canvases may contain children")
        }
        for child in children { try validateNode(child, parentType:type) }
    }
    public static func validate(_ document: JSON) throws {
        guard try document.data().count<=524288 else {throw MUPError("quota","Document exceeds 512 KiB")}
        try SchemaValidator(name: "document").validate(document)
        try validateNode(document["root"])
        let all = nodes(document["root"])
        guard all.count <= 512, Set(all.compactMap { $0["node_id"].string }).count == all.count else { throw MUPError("invalid_document", "Node IDs must be unique; limit 512 nodes") }
        let actions = Set((document["actions"].array ?? []).compactMap(\.string))
        for n in all {
            if n["type"].string == "button", !actions.contains(n["props"]["action_id"].string ?? "") { throw MUPError("invalid_action", "Button requires a registered action") }
            if !["stack", "canvas"].contains(n["type"].string ?? ""), !(n["children"].array ?? []).isEmpty { throw MUPError("invalid_document", "Only stacks and canvases may contain children") }
        }
    }
}
extension Document {
    static func transform(_ node: JSON, id: String, change: (JSON) throws -> JSON) rethrows -> JSON {
        if node["node_id"].string == id { return try change(node) }
        var result = node
        if let children = node["children"].array { result["children"] = .array(try children.map { try transform($0,id:id,change:change) }) }
        return result
    }
    static func require(_ root: JSON, _ id: String) throws -> JSON {
        guard let node = nodes(root).first(where:{$0["node_id"].string == id}) else { throw MUPError("invalid_patch", "Node unavailable") }
        return node
    }
    static func remove(_ root: JSON, _ id: String) throws -> JSON {
        guard root["node_id"].string != id else { throw MUPError("invalid_patch", "Cannot remove root") }
        var result = root
        if let children = root["children"].array { result["children"] = .array(try children.filter {$0["node_id"].string != id}.map {try remove($0,id)}) }
        return result
    }
    public static func patch(_ document: JSON, operations: [JSON]) throws -> JSON {
        var result = document
        var root = document["root"]
        for op in operations {
            switch op["op"].string {
            case "set_props":
                let id = op["node_id"].string!; _ = try require(root,id)
                root = transform(root,id:id) { node in var n = node; n["props"] = .object((n["props"].object ?? [:]).merging(op["props"].object ?? [:]) {_,new in new}); return n }
            case "remove_node": let id = op["node_id"].string!; _ = try require(root,id); root = try remove(root,id)
            case "insert_node", "move_node":
                let parent = op["parent_id"].string!
                let node: JSON
                if op["op"].string == "move_node" {
                    let id = op["node_id"].string!; node = try require(root,id)
                    guard !nodes(node).contains(where:{$0["node_id"].string == parent}) else {throw MUPError("invalid_patch","Cannot create cycle")}
                    root = try remove(root,id)
                } else { node = op["node"] }
                guard let parentType=try require(root,parent)["type"].string, ["stack", "canvas"].contains(parentType) else {throw MUPError("invalid_patch","Parent must be a stack or canvas")}
                root = try transform(root,id:parent) { n in
                    var updated = n; var children = n["children"].array ?? []
                    guard let index = op["index"].int, index <= children.count else {throw MUPError("invalid_patch","Index out of range")}
                    children.insert(node,at:index); updated["children"] = .array(children); return updated
                }
            default: throw MUPError("invalid_patch", "Unsupported operation")
            }
        }
        result["root"] = root
        try validate(result)
        return result
    }
}
