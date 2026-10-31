import AppKit
import SwiftUI

struct ConversationSession: Identifiable {
    struct Message: Identifiable {
        enum Speaker: Equatable { case user, assistant }
        let id: String
        let speaker: Speaker
        let text: String
    }

    let id: String
    let title: String
    let updatedAt: String
    let messages: [Message]
    var preview: String { messages.last?.text ?? "" }
}

@MainActor final class ConversationHistoryModel: ObservableObject {
    @Published private(set) var presentationMode: WorkspaceMode = .grid
    @Published private(set) var currentSessionID: String

    let sessions: [ConversationSession]

    init(sessions: [ConversationSession] = ConversationHistoryModel.samples) {
        self.sessions = sessions
        self.currentSessionID = sessions.first?.id ?? ""
    }

    var currentSession: ConversationSession? {
        sessions.first { $0.id == currentSessionID }
    }

    var allowsSessionSelection: Bool { presentationMode == .focused }
    var usesWideLayout: Bool { presentationMode != .grid }

    func configure(mode: WorkspaceMode) { presentationMode = mode }

    func selectSession(_ session: ConversationSession) {
        guard allowsSessionSelection else { return }
        currentSessionID = session.id
    }

    static let samples: [ConversationSession] = [
        .init(id: "workspace-layout", title: "工作空間的面板排列方式", updatedAt: "剛剛", messages: [
            .init(id: "wl-u1", speaker: .user, text: "我想讓面板像 iOS 主畫面一樣，拖曳時周圍面板會自動挪位。"),
            .init(id: "wl-a1", speaker: .assistant, text: "可以先用固定格位編號，從左到右、由上到下處理衝突。一般面板依序向後移動，跨兩格的形象面板則保留固定位置。\n\n例如可以用這段 Swift 表示格位：\n\n```swift\nlet columns = 3\nlet nextSlot = currentSlot + 1\n```\n\n更多格式可參考[Markdown 指南](https://commonmark.org/help/)。"),
            .init(id: "wl-u2", speaker: .user, text: "只有一般面板支持自動挪位，形象面板維持原位。"),
            .init(id: "wl-a2", speaker: .assistant, text: "已把這個規則記入面板排列計畫。")
        ]),
        .init(id: "glass-material", title: "調整面板 glass 的透明度", updatedAt: "10 分鐘前", messages: [
            .init(id: "gm-u1", speaker: .user, text: "面板能再透明一些嗎？現在有點偏白。"),
            .init(id: "gm-a1", speaker: .assistant, text: "一般狀態先降到 2%，高光狀態降到 5%，再檢查未聚焦窗口的呈現。")
        ]),
        .init(id: "agent-identity", title: "Agent 形象核心動畫", updatedAt: "昨天", messages: [
            .init(id: "ai-u1", speaker: .user, text: "核心的部分，我想改用高密度的光子來表示，不要只用一顆球。"),
            .init(id: "ai-a1", speaker: .assistant, text: "可以讓核心與周圍粒子使用接近的尺寸，再透過密度、速度和排列方式表達狀態。")
        ]),
        .init(id: "responsive-type", title: "不同面板尺寸的文字排版", updatedAt: "昨天", messages: [
            .init(id: "rt-u1", speaker: .user, text: "全局模式下面板大小會變化，希望一行大約顯示二十個中文字；太窄就不顯示文字。"),
            .init(id: "rt-a1", speaker: .assistant, text: "我會用實際字級估算欄寬，低於可讀門檻時隱藏文字，避免硬縮字造成難以閱讀。")
        ]),
        .init(id: "scroll-routing", title: "面板內的滾動行為", updatedAt: "3 天前", messages: [
            .init(id: "sr-u1", speaker: .user, text: "面板在全局模式跟單一窗口時都要支援滾動。"),
            .init(id: "sr-a1", speaker: .assistant, text: "在面板內容上使用一般滾動瀏覽聊天；工作區空白處仍可滾動網格，Ctrl 加滾動繼續縮放。")
        ]),
        .init(id: "visual-study", title: "深色工作空間的視覺方向", updatedAt: "4 天前", messages: [
            .init(id: "vs-u1", speaker: .user, text: "窗口底色先設為黑色，glass 不要再偏藍。"),
            .init(id: "vs-a1", speaker: .assistant, text: "收到，工作空間維持深色底，面板外層改為低透明度的中性玻璃。")
        ]),
        .init(id: "multi-display", title: "多螢幕與窗口分配", updatedAt: "1 週前", messages: [
            .init(id: "md-u1", speaker: .user, text: "多屏幕時面板要像 macOS 一樣支援拖動到不同窗口。"),
            .init(id: "md-a1", speaker: .assistant, text: "面板移到目標窗口後，會使用該窗口自己的全局網格尺寸與排列狀態。")
        ]),
        .init(id: "panel-selection", title: "面板選取與批次移動", updatedAt: "1 週前", messages: [
            .init(id: "ps-u1", speaker: .user, text: "選哪個面板，哪個面板會高光。然後支持多選面板，一次性移動到別的窗口。"),
            .init(id: "ps-a1", speaker: .assistant, text: "已保留面板本身的選取高光，並沿用 Command 點選來增減多選集合。")
        ]),
        .init(id: "global-columns", title: "全局模式的預設欄數", updatedAt: "2 週前", messages: [
            .init(id: "gc-u1", speaker: .user, text: "系統開啟後，寬屏幕默認 col 數為 4，長屏幕默認為 2。"),
            .init(id: "gc-a1", speaker: .assistant, text: "窗口建立時會讀取各自長寬比，套用預設欄數並保留該窗口自己的縮放狀態。")
        ]),
        .init(id: "new-panel", title: "新增面板種類的設計流程", updatedAt: "2 週前", messages: [
            .init(id: "np-u1", speaker: .user, text: "接下來我們開始設計各種面板吧。"),
            .init(id: "np-a1", speaker: .assistant, text: "先從不接 Agent 的純 UI 面板開始，確認資訊層級與操作方式後再逐一接上資料。")
        ])
    ]
}

struct ConversationHistoryPanelView: View {
    @ObservedObject var model: ConversationHistoryModel

    var body: some View {
        GeometryReader { geometry in
            let layout = ConversationHistoryLayout(width: geometry.size.width, focused: model.usesWideLayout)
            if layout.showsText, let session = model.currentSession {
                if model.allowsSessionSelection {
                    let sidebarWidth = min(260, max(180, geometry.size.width * 0.22))
                    HStack(spacing: 0) {
                        sessionSidebar(width: sidebarWidth, fontSize: layout.fontSize)
                            .frame(width: sidebarWidth)
                        Rectangle().fill(.white.opacity(0.10)).frame(width: 1).padding(.vertical, 12)
                        transcript(session, availableWidth: max(1, geometry.size.width - sidebarWidth - 25), focused: true)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                } else {
                    transcript(session, availableWidth: layout.contentWidth, focused: model.usesWideLayout)
                        .frame(width: layout.contentWidth, height: geometry.size.height)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .background(Color.clear)
        .preferredColorScheme(.dark)
        .accessibilityIdentifier("conversation-chat-panel")
    }

    private func sessionSidebar(width: CGFloat, fontSize: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("SESSION").font(.system(size: 10, weight: .medium, design: .monospaced))
                    .tracking(2).foregroundStyle(.white.opacity(0.38))
                Text("對話").font(.system(size: 20, weight: .medium))
            }
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(model.sessions) { session in
                        Button { model.selectSession(session) } label: {
                            SessionRow(session: session, selected: session.id == model.currentSessionID,
                                       fontSize: fontSize)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("conversation-session-\(session.id)")
                    }
                }
            }
            .scrollIndicators(.hidden)
        }
        .frame(width: max(1, width - 24))
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .padding(.vertical, 20)
        .padding(.leading, 16)
        .padding(.trailing, 8)
        .foregroundStyle(Color(white: 0.88))
    }

    private func transcript(_ session: ConversationSession, availableWidth: CGFloat, focused: Bool) -> some View {
        let textLayout = ConversationHistoryLayout(width: availableWidth, focused: focused)
        return ConversationTranscript(session: session, fontSize: textLayout.fontSize)
            .frame(width: textLayout.contentWidth, height: nil)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.vertical, textLayout.verticalPadding)
            .foregroundStyle(Color(white: 0.88))
    }
}

private struct SessionRow: View {
    let session: ConversationSession
    let selected: Bool
    let fontSize: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(session.title).font(.system(size: fontSize * 0.88, weight: selected ? .medium : .regular))
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Text(session.updatedAt).font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.white.opacity(0.44)).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .background {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.white.opacity(selected ? 0.10 : 0.001))
        }
        .contentShape(RoundedRectangle(cornerRadius: 10))
    }
}

private struct ConversationTranscript: View {
    let session: ConversationSession
    let fontSize: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 9) {
                HStack(alignment: .firstTextBaseline) {
                    Text(session.title).font(.system(size: fontSize * 1.22, weight: .semibold)).lineLimit(2)
                    Spacer(minLength: 8)
                    Text("示意內容").font(.system(size: max(9, fontSize * 0.66), design: .monospaced))
                        .tracking(1).foregroundStyle(.white.opacity(0.36)).lineLimit(1)
                }
                Text("最近更新 · \(session.updatedAt)")
                    .font(.system(size: fontSize * 0.76)).foregroundStyle(.white.opacity(0.44))
                Rectangle().fill(.white.opacity(0.10)).frame(height: 1).padding(.top, 7)
            }
            .padding(.bottom, 24)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 26) {
                        ForEach(session.messages) { message in
                            ConversationMessageView(message: message, fontSize: fontSize)
                                .id(message.id)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
                .onAppear { scrollToLatest(using: proxy, session: session) }
                .onChange(of: session.id) { _, _ in scrollToLatest(using: proxy, session: session) }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .font(.system(size: fontSize))
        .foregroundStyle(Color(white: 0.88))
    }

    private func scrollToLatest(using proxy: ScrollViewProxy, session: ConversationSession) {
        guard let latestID = session.messages.last?.id else { return }
        DispatchQueue.main.async { proxy.scrollTo(latestID, anchor: .bottom) }
    }
}

private struct ConversationMessageView: View {
    let message: ConversationSession.Message
    let fontSize: CGFloat
    @State private var isHovered = false
    @State private var hoverExitGeneration = 0
    @State private var didCopy = false

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            if message.speaker == .user { Spacer(minLength: 28) }
            VStack(alignment: .leading, spacing: 8) {
                Text(message.speaker == .user ? "你" : "MALTOSE")
                    .font(.system(size: fontSize * 0.68, weight: .medium, design: .monospaced))
                    .tracking(1.2).foregroundStyle(.white.opacity(0.42))
                ConversationMarkdownContent(source: message.text, fontSize: fontSize)
                HStack {
                    Spacer()
                    Button {
                        copy(message.text)
                    } label: {
                        Label(didCopy ? "已複製" : "複製", systemImage: didCopy ? "checkmark" : "document.on.document")
                            .font(.system(size: max(10, fontSize * 0.68)))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.white.opacity(0.48))
                    .opacity(isHovered || didCopy ? 1 : 0)
                    .allowsHitTesting(isHovered || didCopy)
                    .accessibilityLabel(didCopy ? "已複製訊息" : "複製訊息")
                }
                .frame(height: max(14, fontSize * 0.82))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, message.speaker == .user ? 16 : 0)
            .padding(.vertical, message.speaker == .user ? 13 : 4)
            .background {
                if message.speaker == .user {
                    RoundedRectangle(cornerRadius: 16).fill(Color.white.opacity(0.075))
                }
            }
            if message.speaker == .assistant { Spacer(minLength: 28) }
        }
        .frame(maxWidth: .infinity, alignment: message.speaker == .user ? .trailing : .leading)
        .onHover(perform: updateHover)
    }

    private func updateHover(_ hovering: Bool) {
        hoverExitGeneration += 1
        let generation = hoverExitGeneration
        if hovering {
            isHovered = true
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.65) {
            guard hoverExitGeneration == generation else { return }
            isHovered = false
        }
    }

    private func copy(_ value: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        didCopy = pasteboard.setString(value, forType: .string)
        guard didCopy else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { didCopy = false }
    }
}

private struct ConversationMarkdownContent: View {
    let source: String
    let fontSize: CGFloat

    private var blocks: [MarkdownDocumentBlock] { MarkdownDocumentParser.parse(source) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(blocks) { block in
                switch block.content {
                case let .heading(level, text):
                    InlineMarkdownText(text)
                        .font(.system(size: fontSize * (level == 1 ? 1.35 : 1.16), weight: .semibold))
                case let .paragraph(text):
                    InlineMarkdownText(text).font(.system(size: fontSize)).lineSpacing(fontSize * 0.45)
                case let .bullet(text):
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(.white.opacity(0.58))
                        InlineMarkdownText(text).font(.system(size: fontSize)).lineSpacing(fontSize * 0.4)
                    }
                case let .quote(text):
                    HStack(alignment: .top, spacing: 10) {
                        RoundedRectangle(cornerRadius: 2).fill(.cyan.opacity(0.62)).frame(width: 3)
                        InlineMarkdownText(text).font(.system(size: fontSize)).foregroundStyle(.white.opacity(0.75))
                    }
                    .fixedSize(horizontal: false, vertical: true)
                case let .code(language, text):
                    ConversationCodeBlock(language: language, source: text, fontSize: fontSize)
                case let .table(rows):
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                            InlineMarkdownText(row.joined(separator: "   ·   ")).font(.system(size: fontSize * 0.9))
                        }
                    }
                case let .image(alt, _):
                    if !alt.isEmpty { InlineMarkdownText(alt).font(.system(size: fontSize)).foregroundStyle(.secondary) }
                case .divider:
                    Rectangle().fill(.white.opacity(0.12)).frame(height: 1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ConversationCodeBlock: View {
    let language: String?
    let source: String
    let fontSize: CGFloat
    @State private var didCopy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language?.uppercased() ?? "CODE")
                    .font(.system(size: 10, weight: .medium, design: .monospaced)).tracking(1)
                    .foregroundStyle(.white.opacity(0.48))
                Spacer()
                Button {
                    let pasteboard = NSPasteboard.general
                    pasteboard.clearContents()
                    didCopy = pasteboard.setString(source, forType: .string)
                    if didCopy { DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { didCopy = false } }
                } label: {
                    Label(didCopy ? "已複製" : "複製程式碼", systemImage: didCopy ? "checkmark" : "document.on.document")
                        .font(.system(size: 10))
                }
                .buttonStyle(.plain)
                .foregroundStyle(.white.opacity(0.58))
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            Rectangle().fill(.white.opacity(0.08)).frame(height: 1)
            ScrollView(.horizontal) {
                Text(source).font(.system(size: max(11, fontSize * 0.84), design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
            }
        }
        .background(Color.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 11))
    }
}
