import Foundation

enum AgentRecipient: String, Codable { case maltose, codex }

/// A mention is a leading command token, never an occurrence in quotes/code/prose.
/// Selecting/reading a panel is deliberately absent from this routing decision.
struct AgentComposerMessage: Equatable {
    var explicitRecipient: AgentRecipient?
    var body: String

    init(_ input: String) {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        explicitRecipient = nil; body = text
        if let line = input.components(separatedBy: .newlines).first(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }),
           line.hasPrefix("    ") || line.hasPrefix("\t") {
            body = input.trimmingCharacters(in: .newlines); return
        }
        for recipient in [AgentRecipient.codex, .maltose] {
            let prefix = "@\(recipient.rawValue)"
            guard text.lowercased().hasPrefix(prefix) else { continue }
            var suffix = String(text.dropFirst(prefix.count))
            guard suffix.isEmpty || suffix.first?.isWhitespace == true || suffix.first == ":" || suffix.first == "：" else { continue }
            if suffix.first == ":" || suffix.first == "：" { suffix.removeFirst() }
            explicitRecipient = recipient
            body = suffix.trimmingCharacters(in: .whitespacesAndNewlines)
            return
        }
    }

    func recipient(current: AgentRecipient) -> AgentRecipient { explicitRecipient ?? current }
}
