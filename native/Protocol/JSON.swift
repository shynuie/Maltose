import Foundation
public enum JSON: Codable, Sendable, Equatable {
    case null, bool(Bool), number(Double), string(String), array([JSON]), object([String: JSON])
    public init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self), n.isFinite { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSON].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSON].self)) }
    }
    public func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self { case .null: try c.encodeNil(); case .bool(let b): try c.encode(b); case .number(let n): try c.encode(n); case .string(let s): try c.encode(s); case .array(let a): try c.encode(a); case .object(let o): try c.encode(o) }
    }
    public subscript(_ key: String) -> JSON { get { object?[key] ?? .null } set { var o = object ?? [:]; o[key] = newValue; self = .object(o) } }
    public var object: [String:JSON]? { if case .object(let o) = self { o } else { nil } }
    public var array: [JSON]? { if case .array(let a) = self { a } else { nil } }
    public var string: String? { if case .string(let s) = self { s } else { nil } }
    public var number: Double? { if case .number(let n) = self { n } else { nil } }
    public var int: Int? { number.flatMap { $0 >= 0 && $0 < Double(Int.max) && $0.rounded() == $0 ? Int($0) : nil } }
    public var bool: Bool? { if case .bool(let b) = self { b } else { nil } }
    public static func decode(_ data: Data) throws -> JSON { try JSONDecoder().decode(JSON.self, from: data) }
    public func data() throws -> Data { let e = JSONEncoder(); e.outputFormatting = [.sortedKeys]; return try e.encode(self) }
    public static func s(_ s: String) -> JSON { .string(s) }
    public static func n(_ n: Int) -> JSON { .number(Double(n)) }
}
public struct MUPError: Error, Sendable {
    public let code: String
    public let message: String
    public init(_ code: String, _ message: String) { self.code = code; self.message = message }
    public var json: JSON { .object(["code":.s(code),"message":.s(message),"details":.object([:])]) }
}
public func timestamp() -> String { ISO8601DateFormatter().string(from: Date()) }
