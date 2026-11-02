import AppKit

struct RuntimeApprovalRequest: Decodable {
    struct Action: Decodable { var id: String; var label: String }
    var block_id: String
    var block_type: String?
    var title: String
    var content: String
    var status: String
    var actions: [Action]
    var value: [String: String]

    var domain: String? {
        for (domain, prefix, key) in [("filesystem", "filesystem-approval-", "approval_id"),
                                      ("execution", "execution-approval-", "approval_id"),
                                      ("knowledge", "knowledge-proposal-", "proposal_id")] {
            if let id = value[key], !id.isEmpty, block_id == prefix + id { return domain }
        }
        return nil
    }

    static func decodeEvent(_ data: Data) -> Self? {
        struct Envelope: Decodable { struct Event: Decodable { var type: String; var payload: RuntimeApprovalRequest }; var event: Event }
        guard let envelope = try? JSONDecoder().decode(Envelope.self, from: data),
              envelope.event.type == "native_approval",
              let domain = envelope.event.payload.domain else { return nil }
        let request = envelope.event.payload
        if request.status == "pending", Set(request.actions.map(\.id)) != Set([domain + ".approve", domain + ".reject"]) { return nil }
        return request
    }
}

/// Human controls send scoped decisions back to the existing runtime approval managers.
/// Transcript text and Agent tool calls cannot invoke this coordinator's decision callback.
@MainActor final class RuntimeApprovalCoordinator {
    typealias Presenter = @MainActor (RuntimeApprovalRequest, @escaping (Bool, String?) -> Void) -> (() -> Void)
    var present: Presenter = RuntimeApprovalCoordinator.showSheet
    var send: ((String, [String: String], @escaping (Bool, String?) -> Void) -> Bool)?
    var onIssue: ((String) -> Void)?
    private var queue: [RuntimeApprovalRequest] = []
    private var seen: Set<String> = []
    private var active: RuntimeApprovalRequest?
    private var cancelPresentation: (() -> Void)?
    private var generation = UUID()

    func receive(_ data: Data) {
        guard let request = RuntimeApprovalRequest.decodeEvent(data) else { return }
        if request.status != "pending" {
            if !["approved", "rejected", "published"].contains(request.status) {
                onIssue?(request.title + "：" + request.content)
            }
            seen.insert(request.block_id)
            queue.removeAll { $0.block_id == request.block_id }
            if active?.block_id == request.block_id {
                generation = UUID(); active = nil
                cancelPresentation?(); cancelPresentation = nil
                next()
            }
            return
        }
        guard seen.insert(request.block_id).inserted else { return }
        queue.append(request)
        next()
    }

    func reset() {
        generation = UUID(); queue.removeAll(); seen.removeAll(); active = nil
        cancelPresentation?(); cancelPresentation = nil
    }

    private func next() {
        guard active == nil, !queue.isEmpty else { return }
        let request = queue.removeFirst()
        active = request
        let token = generation
        cancelPresentation = present(request) { [weak self] approved, reason in
            guard let self, self.generation == token, self.active?.block_id == request.block_id, let domain = request.domain else { return }
            self.cancelPresentation = nil
            var value = request.value
            if domain == "knowledge" && !approved { value["reason"] = reason?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false ? reason : "使用者在 Maltose 中拒絕此提案。" }
            let accepted = self.send?(domain + (approved ? ".approve" : ".reject"), value) { [weak self] ok, message in
                guard let self, self.generation == token else { return }
                if !ok {
                    self.seen.remove(request.block_id)
                    self.onIssue?(message ?? "確認未成功，請核對操作狀態後再繼續。")
                }
                self.active = nil; self.next()
            } ?? false
            if !accepted {
                self.seen.remove(request.block_id)
                self.onIssue?("主 Agent 已離線，決定尚未送出；沒有自動重送。")
                self.active = nil; self.next()
            }
        }
    }

    private static func showSheet(_ request: RuntimeApprovalRequest, completion: @escaping (Bool, String?) -> Void) -> () -> Void {
        let alert = NSAlert()
        alert.messageText = request.title
        alert.informativeText = request.content
        alert.alertStyle = .warning
        alert.addButton(withTitle: "拒絕")
        alert.addButton(withTitle: "允許這次操作")
        var reason: NSTextField?
        if request.domain == "knowledge" {
            let field = NSTextField(frame: .init(x: 0, y: 0, width: 360, height: 24))
            field.placeholderString = "拒絕原因（選填）"
            alert.accessoryView = field; reason = field
        }
        guard let window = NSApp.keyWindow ?? NSApp.windows.first(where: { $0.isVisible && !$0.isSheet }) else {
            // The main workspace normally exists first; losing it must never approve a request.
            Task { @MainActor in completion(false, "沒有可用的確認窗口。") }
            return {}
        }
        alert.beginSheetModal(for: window) { response in
            completion(response == .alertSecondButtonReturn, reason?.stringValue)
        }
        return { [weak window] in window?.endSheet(alert.window, returnCode: .abort) }
    }
}
