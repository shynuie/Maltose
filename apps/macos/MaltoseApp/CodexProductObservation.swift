import Foundation
import CryptoKit

/// Saved at SDK item/started, never inferred from the latest user requirement
/// when a delayed completion or thread snapshot arrives.
struct CodexProductObservationOrigin: Codable {
    let itemID: String
    let itemType: String
    let executionID: String
    let requirementsRevision: Int
    let planVersion: Int
    let command: String?
}

enum CodexProductObservation {
    static func originID(turn: String, item: String) -> String { "codex-start:\(turn):\(item)" }

    static func evidence(item: UserViewValue, origin: CodexProductObservationOrigin, messageID: String,
                         worktree: String, scope: String) throws -> ProductEvidence {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let raw = try encoder.encode(item)
        let identity = SHA256.hash(data: Data((origin.executionID + ":" + messageID).utf8)).map { String(format: "%02x", $0) }.joined()
        if item["type"] == .string("commandExecution"), let command = item["command"]?.stringValue,
           origin.command == command, item["cwd"]?.stringValue == worktree,
           let argv = testArguments(command), raw.count <= 24000,
           let output = item["aggregatedOutput"]?.stringValue {
            let status = item["status"]?.stringValue ?? "unknown"
            let code = item["exitCode"]
            let normalized = ProductToolObservation(id: String(identity.prefix(32)), tool: "execute_command",
                arguments: ["argv": .strings(argv), "cwd": .string(worktree)],
                result: .object(["status": .string(status == "completed" && code == .number(0) ? "completed" : status == "failed" || (code != nil && code != .null && code != .number(0)) ? "failed" : "unknown"),
                    "exit_code": code ?? .null, "stdout": .string(output), "stderr": .string(""),
                    "outputSource": .string("codex_aggregatedOutput"), "rawMessageID": .string(messageID)]), truncated: false)
            var proof = try normalized.evidence(executionID: origin.executionID)
            proof = .init(id: proof.id, executionID: proof.executionID, kind: proof.kind, source: proof.source,
                verdict: proof.verdict, detail: proof.detail, blocksCompletion: proof.blocksCompletion, checkKey: proof.checkKey,
                invalidatesPriorEvidence: proof.invalidatesPriorEvidence, scopeID: scope)
            return proof
        }
        let detail = raw.count <= 24000 ? String(decoding: raw, as: UTF8.self) : "SDK 紀錄超出觀察預算；完整內容保存在 \(messageID)，未作為完成證據。"
        return .init(id: "sdk:\(identity)", executionID: origin.executionID, kind: .execution, source: .observed,
            verdict: .unknown, detail: detail, scopeID: scope,
            invalidatesVerification: item["type"] == .string("fileChange"))
    }

    /// Parse a single literal command, optionally wrapped in sh/zsh -c/-lc.
    /// No shell expansion/evaluation. Compound commands remain observations,
    /// never passing tests merely because their final echo returned zero.
    static func testArguments(_ command: String) -> [String]? {
        guard command.utf8.count <= 16000, !command.contains("$"), !command.contains("`"), !command.contains("\n"),
              var words = words(command) else { return nil }
        if words.count == 3, ["sh", "bash", "zsh"].contains(URL(fileURLWithPath: words[0]).lastPathComponent), ["-c", "-lc"].contains(words[1]) {
            guard let inner = self.words(words[2]) else { return nil }; words = inner
        }
        if words.count > 2, URL(fileURLWithPath: words[0]).lastPathComponent == "uv", words[1] == "run" { words.removeFirst(2) }
        guard let first = words.first else { return nil }
        let name = URL(fileURLWithPath: first).lastPathComponent
        let valid = (["pytest", "pytest-3"].contains(name) ||
            (name.hasPrefix("python") && words.count >= 3 && words[1] == "-m" && ["unittest", "pytest"].contains(words[2])) ||
            (["swift", "cargo", "npm", "yarn", "pnpm", "go"].contains(name) && words.count >= 2 && words[1] == "test"))
            && !words.contains("--help") && !words.contains("--version")
        return valid ? words : nil
    }

    private static func words(_ source: String) -> [String]? {
        var result: [String] = [], word = "", quote: Character?, escaped = false, started = false
        for character in source {
            if escaped { word.append(character); escaped = false; started = true; continue }
            if character == "\\", quote != "'" { escaped = true; started = true; continue }
            if let current = quote {
                if character == current { quote = nil } else { word.append(character) }
                continue
            }
            if character == "'" || character == "\"" { quote = character; started = true; continue }
            if ";&|<>()\r".contains(character) { return nil }
            if character.isWhitespace {
                if started { result.append(word); word = ""; started = false }
            } else { word.append(character); started = true }
        }
        guard quote == nil, !escaped else { return nil }
        if started { result.append(word) }
        return result.count <= 256 ? result : nil
    }
}
