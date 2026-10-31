import AppKit
import SwiftUI

/// UI-only model. Content has no dependency on the Host or an Agent document.
struct WorkspacePanel: Identifiable {
    enum Kind: Equatable {
        case canvas, notes, chart, table, conversationHistory, document, imageGallery, agentIdentity, agentCoreTest

        var allowsMultipleInstances: Bool {
            self != .agentIdentity && self != .conversationHistory && self != .agentCoreTest
        }

        var defaultInstanceTitle: String {
            switch self {
            case .canvas: "畫布"
            case .notes: "筆記"
            case .chart: "圖表"
            case .table: "資料"
            case .conversationHistory: "聊天"
            case .document: "文檔"
            case .imageGallery: "圖片"
            case .agentIdentity: "形象"
            case .agentCoreTest: "核心動畫測試"
            }
        }
    }
    let id: String
    let title: String
    let kind: Kind

    var globalGridRowSpan: Int {
        kind == .agentIdentity || kind == .conversationHistory ? 2 : 1
    }
    var supportsFocusedMode: Bool { kind != .agentIdentity }

    @MainActor func makeContentView(conversationHistoryModel: ConversationHistoryModel? = nil,
                                    markdownDocumentModel: MarkdownDocumentModel? = nil,
                                    chartModel: CSVLineChartModel? = nil,
                                    imageGalleryModel: ImageGalleryModel? = nil) -> NSView {
        let view: NSView
        switch kind {
        case .chart:
            let hostingView = NSHostingView(rootView: CSVLineChartPanelView(model: chartModel ?? CSVLineChartModel()))
            hostingView.wantsLayer = true
            hostingView.layer?.backgroundColor = NSColor.clear.cgColor
            hostingView.layer?.isOpaque = false
            view = hostingView
        case .conversationHistory:
            let model = conversationHistoryModel ?? ConversationHistoryModel()
            let hostingView = NSHostingView(rootView: ConversationHistoryPanelView(model: model))
            hostingView.wantsLayer = true
            hostingView.layer?.backgroundColor = NSColor.clear.cgColor
            hostingView.layer?.isOpaque = false
            view = hostingView
        case .document:
            let model = markdownDocumentModel ?? MarkdownDocumentModel()
            let hostingView = NSHostingView(rootView: MarkdownDocumentPanelView(model: model))
            hostingView.wantsLayer = true
            hostingView.layer?.backgroundColor = NSColor.clear.cgColor
            hostingView.layer?.isOpaque = false
            view = hostingView
        case .imageGallery:
            let hostingView = NSHostingView(rootView: ImageGalleryPanelView(model: imageGalleryModel ?? ImageGalleryModel()))
            hostingView.wantsLayer = true
            hostingView.layer?.backgroundColor = NSColor.clear.cgColor
            hostingView.layer?.isOpaque = false
            view = hostingView
        case .agentIdentity:
            let hostingView = NSHostingView(rootView: AgentIdentityPanelView())
            hostingView.wantsLayer = true
            hostingView.layer?.backgroundColor = NSColor.clear.cgColor
            hostingView.layer?.isOpaque = false
            view = hostingView
        case .agentCoreTest:
            view = NSHostingView(rootView: AgentCoreAnimationTestView())
        default:
            view = NSHostingView(rootView: WorkspaceSampleContent(panel: self))
        }
        (view as? NSHostingView<AgentCoreAnimationTestView>)?.sizingOptions = []
        (view as? NSHostingView<AgentIdentityPanelView>)?.sizingOptions = []
        (view as? NSHostingView<ConversationHistoryPanelView>)?.sizingOptions = []
        (view as? NSHostingView<MarkdownDocumentPanelView>)?.sizingOptions = []
        (view as? NSHostingView<CSVLineChartPanelView>)?.sizingOptions = []
        (view as? NSHostingView<ImageGalleryPanelView>)?.sizingOptions = []
        (view as? NSHostingView<WorkspaceSampleContent>)?.sizingOptions = []
        return view
    }

    static let samples: [WorkspacePanel] = [
        .init(id: "agent-identity", title: "形象", kind: .agentIdentity),
        .init(id: "chat", title: "聊天", kind: .conversationHistory),
        .init(id: "document", title: "文檔", kind: .document),
        .init(id: "gallery", title: "圖片", kind: .imageGallery),
        .init(id: "canvas", title: "畫布", kind: .canvas),
        .init(id: "notes", title: "筆記", kind: .notes),
        .init(id: "chart", title: "圖表", kind: .chart),
        .init(id: "table", title: "資料", kind: .table)
    ]

    static let agentCoreTest = WorkspacePanel(id: "agent-core-test", title: "核心動畫測試", kind: .agentCoreTest)

    static func previewSamples(count: Int) -> [WorkspacePanel] {
        let kinds: [Kind] = [.canvas, .notes, .chart, .table]
        let titles = ["畫布", "筆記", "圖表", "資料"]
        return (0..<max(0, count)).map { index in
            let kindIndex = index % kinds.count
            return WorkspacePanel(id: String(format: "sample-%02d", index + 1),
                                  title: "\(titles[kindIndex]) \(String(format: "%02d", index + 1))",
                                  kind: kinds[kindIndex])
        }
    }
}

private struct WorkspaceSampleContent: View {
    let panel: WorkspacePanel
    @State private var note = "從一個面板開始。\n\n內容會隨空間重新排列；縮圖保留完整畫面的比例。\n\n你可以在這裡輸入文字，試試放大與切換後是否保留。"
    @State private var selected = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack {
                Text(panel.title).font(.system(size: 21, weight: .medium))
                Spacer()
                Text("UI STUDY / 01").font(.system(size: 10, design: .monospaced)).tracking(2).foregroundStyle(.secondary)
            }
            switch panel.kind {
            case .notes:
                TextEditor(text: $note).font(.system(size: 16)).scrollContentBackground(.hidden)
                    .accessibilityLabel("示範筆記")
            case .canvas:
                GeometryReader { geometry in
                    let wide = geometry.size.width > 480
                    let layout = wide ? AnyLayout(HStackLayout(spacing: 30)) : AnyLayout(VStackLayout(spacing: 24))
                    layout {
                        RoundedRectangle(cornerRadius: 0).fill(Color(red: 0.24, green: 0.49, blue: 0.70))
                            .overlay(Text("輸入").font(.title3))
                        Image(systemName: wide ? "arrow.right" : "arrow.down").foregroundStyle(.secondary)
                        Circle().fill(Color(red: 0.30, green: 0.64, blue: 0.67))
                            .overlay(Text(selected ? "已選取" : "輸出").font(.title3))
                            .onTapGesture { selected.toggle() }.accessibilityLabel(selected ? "輸出已選取" : "輸出")
                    }.padding(32).frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            case .table:
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(0..<8) { index in
                            HStack {
                                Text(String(format: "%02d", index + 1)).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                                Text(["工作空間", "面板排列", "內容尺寸", "互動狀態"][index % 4])
                                Spacer()
                                Text(index % 2 == 0 ? "進行中" : "待確認").foregroundStyle(.secondary)
                            }.padding(.vertical, 18)
                            Divider().overlay(.white.opacity(0.04))
                        }
                    }
                }
            case .chart, .conversationHistory, .document, .imageGallery, .agentCoreTest, .agentIdentity:
                EmptyView()
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .foregroundStyle(Color(white: 0.88))
        .background(Color(red: 0.035, green: 0.052, blue: 0.075))
        .preferredColorScheme(.dark)
    }
}
