import AppKit
import SwiftUI

enum UserViewValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case boolean(Bool)
    case strings([String])
    case object([String: UserViewValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String].self) { self = .strings(value) }
        else { self = .object(try container.decode([String: UserViewValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .string(value): try container.encode(value)
        case let .number(value): try container.encode(value)
        case let .boolean(value): try container.encode(value)
        case let .strings(value): try container.encode(value)
        case let .object(value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

struct UserViewSnapshot: Codable, Equatable {
    var schemaVersion: Int
    var capturedAt: String
    var activeScreenID: String?
    var workspaces: [UserWorkspaceView]
}

enum UserViewCaptureError: LocalizedError {
    case workspaceUnavailable

    var errorDescription: String? { "目前沒有可讀取的工作空間。" }
}

struct UserWorkspaceView: Codable, Equatable, Identifiable {
    var id: String { screenID }
    var screenID: String
    var screenName: String
    var mode: String
    var isActive: Bool
    var primaryPanelID: String?
    var selectedPanelIDs: [String]
    var visiblePanelIDs: [String]
    var offscreenPanelIDs: [String]
    var overlays: [String]
    var globalGrid: [String: UserViewValue]
    var panels: [UserPanelView]
}

struct UserPanelView: Codable, Equatable, Identifiable {
    var id: String { panelID }
    var panelID: String
    var kind: String
    var title: String
    var presentation: String
    var isSelected: Bool
    var details: [String: UserViewValue]
}

@MainActor final class UserViewTestModel: ObservableObject {
    @Published private(set) var isSending = false
    @Published private(set) var response = "按下按鈕後，這裡會顯示 get_user_view 的回傳內容。"
    @Published private(set) var lastError: String?

    private let capture: () async throws -> UserViewSnapshot

    init(capture: @escaping () async throws -> UserViewSnapshot) {
        self.capture = capture
    }

    func send() {
        Task { @MainActor in await sendAndWait() }
    }

    func sendAndWait() async {
        guard !isSending else { return }
        isSending = true
        lastError = nil
        defer { isSending = false }
        do {
            let snapshot = try await capture()
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            encoder.dateEncodingStrategy = .iso8601
            let data = try encoder.encode(snapshot)
            response = String(decoding: data, as: UTF8.self)
        } catch {
            lastError = error.localizedDescription
            response = "擷取失敗：\(error.localizedDescription)"
        }
    }
}

struct UserViewTestWindow: View {
    @ObservedObject var model: UserViewTestModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("UI 感知測試").font(.system(size: 20, weight: .semibold))
                    Text("模擬呼叫 get_user_view，檢視 UI 回傳給 Agent 的目前視圖資訊。")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: model.send) {
                    Label(model.isSending ? "擷取中…" : "發送 get_user_view", systemImage: "paperplane.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.isSending)
                .accessibilityIdentifier("get-user-view-send")
            }

            ScrollView([.vertical, .horizontal]) {
                Text(model.response)
                    .font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                    .padding(14)
            }
            .background(Color.black.opacity(0.34), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(.white.opacity(0.10), lineWidth: 1))
        }
        .padding(18)
        .frame(minWidth: 760, minHeight: 560)
        .foregroundStyle(.white.opacity(0.90))
        .background(Color(red: 0.045, green: 0.055, blue: 0.07))
        .preferredColorScheme(.dark)
    }
}

@MainActor final class UserViewTestWindowController: NSWindowController {
    init(model: UserViewTestModel) {
        let root = NSHostingView(rootView: UserViewTestWindow(model: model))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 720),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Maltose · UI 感知測試"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(calibratedRed: 0.045, green: 0.055, blue: 0.07, alpha: 1)
        window.isOpaque = true
        window.appearance = NSAppearance(named: .darkAqua)
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenAuxiliary]
        window.contentView = root
        super.init(window: window)
        window.center()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func present() {
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
