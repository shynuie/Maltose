import Foundation
import CryptoKit

/// Runtime-produced receipts, captured after a registered tool returns. These
/// fields are absent from model-facing planning/panel tool schemas.
struct ProductToolObservation: Codable {
    let id: String
    let tool: String
    let arguments: [String: UserViewValue]
    let result: UserViewValue
    let truncated: Bool

    func evidence(executionID: String) throws -> ProductEvidence {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(self)
        guard id.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil, tool.utf8.count <= 128,
              data.count <= 32000 else { throw CodexTaskStoreError.invalid("工具觀察超出有界合約。") }
        var kind: ProductEvidence.Kind = .execution
        var verdict: ProductEvidence.Verdict = .unknown
        var blocks = false
        var key: String?
        var invalidates = false
        if !truncated {
            if tool == "read_file", let body = result["text"]?.stringValue,
               result["root"] == arguments["root"], result["path"]?.stringValue != nil,
               result["bytes"] == .number(Double(body.utf8.count)) {
                kind = .sourceRead; verdict = .passed
                key = "file:\(result["root"]?.stringValue ?? ""):\(result["path"]?.stringValue ?? "")"
            } else if tool == "maltose_read_panel", result["ok"] == .boolean(true),
                      result["result"]?.objectValue?.isEmpty == false, !Self.isTruncated(result) {
                kind = .artifact; verdict = .passed
                key = "panel:\(arguments["panelID"]?.stringValue ?? "")"
            } else if tool == "read_web_page", PublicWebSourceReceipt.valid(arguments:arguments,result:result) {
                kind = .sourceRead; verdict = .passed
                key = "web:\(result["sourceID"]?.stringValue ?? ""):\(result["pageIndex"]?.numberValue ?? 0):\(result["tableSelection"]?.stringValue ?? "text")"
            } else if tool == "get_current_datetime", result["iso8601"]?.stringValue != nil {
                kind = .sourceRead; verdict = .passed; key = "time:\(arguments["timezone"]?.stringValue ?? "local")"
            } else if ["search_web", "web_search"].contains(tool), result["complete"] == .boolean(true), result["granularity"] == .string("search_results"),
                      let sources = result["sources"]?.arrayValue, !sources.isEmpty, sources.count <= 25,
                      sources.allSatisfy({ $0["url"]?.stringValue != nil && $0["title"]?.stringValue != nil && $0["snippet"]?.stringValue != nil }) {
                // Actual search results are observable sources for finding links;
                // they do not establish that the underlying pages were read.
                kind = .sourceRead; verdict = .passed
            } else if ["write_file", "create_file", "replace_file_text", "copy_file"].contains(tool),
                      let root = result["root"]?.stringValue, let path = result["path"]?.stringValue {
                key = "file:\(root):\(path)"; invalidates = true
            } else if tool.hasPrefix("maltose_"), result["ok"] == .boolean(true), let id = arguments["panelID"]?.stringValue,
                      !["maltose_read_panel", "maltose_get_user_view", "maltose_list_capabilities"].contains(tool) {
                key = "panel:\(id)"; invalidates = true
            } else if tool == "execute_command", let argv = arguments["argv"]?.arrayValue?.compactMap(\.stringValue), Self.isTestCommand(argv) {
                var scope = arguments; scope.removeValue(forKey: "approval_id"); scope.removeValue(forKey: "timeout_seconds")
                let digest = SHA256.hash(data: try encoder.encode(scope)).map { String(format: "%02x", $0) }.joined()
                key = "command:\(digest)"
                kind = .verification
                if result["status"] == .string("completed"), result["exit_code"] == .number(0),
                   result["stdout"]?.stringValue != nil, result["stderr"]?.stringValue != nil {
                    verdict = .passed
                } else if ["failed", "timed_out", "output_limit_exceeded"].contains(result["status"]?.stringValue ?? "") {
                    verdict = .failed; blocks = true
                }
            }
        }
        // Receipt success means the operation was observed. A separate semantic
        // review must establish whether its content covers a human criterion.
        return .init(id: "tool:\(id)", executionID: executionID, kind: kind, source: .observed,
            verdict: verdict, detail: String(decoding: data, as: UTF8.self), blocksCompletion: blocks, checkKey: key, invalidatesPriorEvidence: invalidates)
    }

    private static func isTestCommand(_ argv: [String]) -> Bool {
        guard let first = argv.first else { return false }
        let name = URL(fileURLWithPath: first).lastPathComponent
        if ["pytest", "pytest-3"].contains(name) { return !argv.contains("--version") && !argv.contains("--help") }
        if name.hasPrefix("python"), argv.count >= 3, argv[1] == "-m", ["unittest", "pytest"].contains(argv[2]) {
            return !argv.contains("--version") && !argv.contains("--help")
        }
        return argv.count >= 2 && ["swift", "cargo", "npm", "yarn", "pnpm", "go"].contains(name) && argv[1] == "test"
    }
    private static func isTruncated(_ value: UserViewValue) -> Bool {
        if let object = value.objectValue {
            return object["truncated"] == .boolean(true) || object.values.contains(where: isTruncated)
        }
        return value.arrayValue?.contains(where: isTruncated) ?? false
    }
}

struct ProductAssessment: Codable, Equatable {
    struct Check: Codable, Equatable { let criterion: String; let evidenceIDs: [String] }
    let status: String
    let summary: String
    let checks: [Check]
    let remaining: [String]
    let resolvedFailures: [String: String]
    let explanation: String

    var completionReview: ProductCompletionReview {
        .init(checks: checks.map { .init(criterion: $0.criterion, evidenceIDs: $0.evidenceIDs) },
              resolvedFailures: resolvedFailures, explanation: explanation)
    }
    func validate() throws {
        func text(_ value: String, limit: Int) -> Bool { !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.utf8.count <= limit }
        guard ["completed", "partial", "needs_input"].contains(status), text(summary, limit: 2000), text(explanation, limit: 2000),
              checks.count <= 288, checks.allSatisfy({ text($0.criterion, limit: 64000) && (1...64).contains($0.evidenceIDs.count) && $0.evidenceIDs.allSatisfy({ text($0, limit: 512) }) }),
              remaining.count <= 64, remaining.allSatisfy({ text($0, limit: 16000) }), resolvedFailures.count <= 128,
              resolvedFailures.allSatisfy({ text($0.key, limit: 512) && text($0.value, limit: 512) }),
              status == "completed" ? remaining.isEmpty : !remaining.isEmpty else { throw CodexTaskStoreError.invalid("成果核對格式不正確。") }
    }
}
