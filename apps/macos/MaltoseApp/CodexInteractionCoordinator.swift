import AppKit

/// Only callbacks from native human controls can produce scoped approval answers.
@MainActor final class CodexInteractionCoordinator {
    typealias Answer = Result<UserViewValue, CodexRPCFailure>
    typealias Presenter = @MainActor (CodexServerRequest, @escaping (Answer) -> Void) -> (() -> Void)
    var present: Presenter = CodexInteractionCoordinator.showSheet
    var send: ((CodexServerRequest, Answer) -> Bool)?
    var onIssue: ((String) -> Void)?
    private var queue: [CodexServerRequest] = []
    private var active: CodexServerRequest?
    private var cancel: (() -> Void)?
    private var generation = UUID()

    func receive(_ request: CodexServerRequest) {
        guard !(active.map { $0.id == request.id && $0.connectionID == request.connectionID } ?? false),
              !queue.contains(where: { $0.id == request.id && $0.connectionID == request.connectionID }) else { return }
        queue.append(request); next()
    }

    func resolved(_ id: CodexRPCID) {
        queue.removeAll { $0.id == id }
        if active?.id == id {
            generation = UUID(); active = nil
            let close = cancel; cancel = nil; close?(); next()
        }
    }

    func reset() {
        generation = UUID(); queue.removeAll(); active = nil
        let close = cancel; cancel = nil; close?()
    }

    private func next() {
        guard active == nil, !queue.isEmpty else { return }
        let request = queue.removeFirst(), token = generation
        active = request
        cancel = present(request) { [weak self] answer in
            guard let self, token == self.generation, self.active?.id == request.id,
                  self.active?.connectionID == request.connectionID else { return }
            self.active = nil; self.cancel = nil
            if self.send?(request, answer) != true { self.onIssue?("Codex 的確認已失效或連線中斷；請先核對任務狀態。") }
            self.next()
        }
    }

    private static func showSheet(_ request: CodexServerRequest, completion: @escaping (Answer) -> Void) -> () -> Void {
        let alert = NSAlert()
        alert.alertStyle = .warning
        let params = request.params
        var answer: (NSApplication.ModalResponse) -> Answer
        switch request.method {
        case "item/commandExecution/requestApproval", "item/fileChange/requestApproval":
            let command = request.method == "item/commandExecution/requestApproval"
            let network = params["networkApprovalContext"]?.objectValue
            alert.messageText = network != nil ? "Codex 要求連線" : command ? "Codex 要求執行操作" : "Codex 要求修改檔案"
            var details = params["reason"]?.stringValue ?? "請確認本次操作範圍。"
            if let network { details += "\n連線：\(network["protocol"]?.stringValue ?? "")://\(network["host"]?.stringValue ?? "")" }
            if let value = params["command"]?.stringValue { details += "\n操作：\(value)" }
            if let cwd = params["cwd"]?.stringValue { details += "\n工作目錄：\(cwd)" }
            if let root = params["grantRoot"]?.stringValue { details += "\n修改範圍：\(root)" }
            if let permissions = params["additionalPermissions"], permissions != .null {
                let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                if let data = try? encoder.encode(permissions) { details += "\n本次額外權限：\n" + String(decoding: data, as: UTF8.self) }
            }
            alert.accessoryView = textPreview(details)
            let decisions = params["availableDecisions"]?.arrayValue
            let allow = decisions == nil || decisions!.contains(.string("accept"))
            alert.addButton(withTitle: "拒絕")
            if allow { alert.addButton(withTitle: "允許這次操作") }
            answer = { .success(.object(["decision": .string(allow && $0 == .alertSecondButtonReturn ? "accept" : "decline")])) }
        case "item/permissions/requestApproval":
            alert.messageText = "Codex 要求額外權限"
            alert.informativeText = "確認以下範圍；允許僅適用於目前回合。"
            let permissions = params["permissions"] ?? .object([:])
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            alert.accessoryView = textPreview(String(decoding: (try? encoder.encode(permissions)) ?? Data(), as: UTF8.self))
            alert.addButton(withTitle: "拒絕"); alert.addButton(withTitle: "允許此回合")
            answer = { .success(.object(["permissions": $0 == .alertSecondButtonReturn ? permissions : .object([:]), "scope": .string("turn")])) }
        case "item/tool/requestUserInput":
            guard let questions = params["questions"]?.arrayValue, !questions.isEmpty, questions.count <= 8 else {
                Task { @MainActor in completion(.failure(.init(code: -32602, message: "Codex 問題格式不正確。"))) }; return {}
            }
            let questionIDs = questions.compactMap { $0["id"]?.stringValue }
            guard questionIDs.count == questions.count, Set(questionIDs).count == questionIDs.count else {
                Task { @MainActor in completion(.failure(.init(code: -32602, message: "Codex 問題識別碼重複。"))) }; return {}
            }
            alert.messageText = "Codex 有問題需要你回答"
            let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 10
            var fields: [(String, () -> String)] = []
            for question in questions {
                guard let id = question["id"]?.stringValue, let text = question["question"]?.stringValue else {
                    Task { @MainActor in completion(.failure(.init(code: -32602, message: "Codex 問題缺少識別碼或內容。"))) }; return {}
                }
                let label = NSTextField(wrappingLabelWithString: text); label.preferredMaxLayoutWidth = 460; stack.addArrangedSubview(label)
                if question["isSecret"] == .boolean(true) {
                    let field = NSSecureTextField(frame: .init(x: 0, y: 0, width: 460, height: 24))
                    stack.addArrangedSubview(field); fields.append((id, { field.stringValue }))
                } else {
                    let field = NSComboBox(frame: .init(x: 0, y: 0, width: 460, height: 26)); field.isEditable = true
                    for option in question["options"]?.arrayValue ?? [] {
                        if let label = option["label"]?.stringValue { field.addItem(withObjectValue: label) }
                        if let description = option["description"]?.stringValue {
                            let info = NSTextField(wrappingLabelWithString: "\(option["label"]?.stringValue ?? "")：\(description)")
                            info.preferredMaxLayoutWidth = 460; info.font = .systemFont(ofSize: 11); stack.addArrangedSubview(info)
                        }
                    }
                    stack.addArrangedSubview(field); fields.append((id, { field.stringValue }))
                }
            }
            alert.accessoryView = stack
            alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "送出回答")
            answer = { response in
                guard response == .alertSecondButtonReturn else { return .failure(.init(code: -32000, message: "使用者取消回答；不要視為同意。")) }
                return .success(.object(["answers": .object(Dictionary(uniqueKeysWithValues: fields.map { ($0.0, .object(["answers": .strings([$0.1()])])) }))]))
            }
        default:
            alert.messageText = "Codex 要求額外互動"
            alert.informativeText = "目前尚未支援這類確認。關閉後會將無法處理的狀態回傳 Codex；麥芽糖保持暫停。"
            alert.addButton(withTitle: "關閉")
            answer = { _ in .failure(.init(code: -32601, message: "Maltose does not yet support this interaction type.")) }
        }
        guard let window = NSApp.keyWindow ?? NSApp.windows.first(where: { $0.isVisible && !$0.isSheet }) else {
            Task { @MainActor in completion(.failure(.init(code: -32000, message: "沒有可用的人員確認窗口。"))) }; return {}
        }
        alert.beginSheetModal(for: window) { completion(answer($0)) }
        return { [weak window] in window?.endSheet(alert.window, returnCode: .abort) }
    }

    private static func textPreview(_ text: String) -> NSView {
        let scroll = NSScrollView(frame: .init(x: 0, y: 0, width: 500, height: 220))
        scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
        let view = NSTextView(frame: scroll.bounds); view.isEditable = false; view.isSelectable = true
        view.isVerticallyResizable = true; view.autoresizingMask = [.width]; view.string = text
        scroll.documentView = view; return scroll
    }
}
