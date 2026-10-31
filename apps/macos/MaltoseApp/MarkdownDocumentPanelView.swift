import AppKit
import SwiftUI

struct MarkdownDocumentBlock: Identifiable {
    enum Content {
        case heading(level: Int, text: String)
        case paragraph(String)
        case bullet(String)
        case quote(String)
        case code(language: String?, source: String)
        case table([[String]])
        case image(alt: String, source: String)
        case divider
    }

    let id: Int
    let content: Content
}

@MainActor final class MarkdownDocumentModel: ObservableObject {
    @Published private(set) var mode: WorkspaceMode = .grid
    let blocks: [MarkdownDocumentBlock]

    init(markdown: String? = nil) {
        let source = markdown ?? Self.loadBundledSample()
        blocks = MarkdownDocumentParser.parse(source)
    }

    func configure(mode: WorkspaceMode) { self.mode = mode }

    private static func loadBundledSample() -> String {
        guard let url = Bundle.module.url(forResource: "sample-document", withExtension: "md"),
              let markdown = try? String(contentsOf: url, encoding: .utf8) else {
            return "# Markdown 文件\n\n內建範例文件目前無法讀取。"
        }
        return markdown
    }
}

enum MarkdownDocumentParser {
    static func parse(_ markdown: String) -> [MarkdownDocumentBlock] {
        let lines = markdown.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var blocks: [MarkdownDocumentBlock] = []
        var index = 0

        func append(_ content: MarkdownDocumentBlock.Content) {
            blocks.append(MarkdownDocumentBlock(id: blocks.count, content: content))
        }

        while index < lines.count {
            let line = lines[index].trimmingCharacters(in: .whitespaces)
            if line.isEmpty { index += 1; continue }

            if line.hasPrefix("```") {
                let language = String(line.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                index += 1
                var codeLines: [String] = []
                while index < lines.count && !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                    codeLines.append(lines[index])
                    index += 1
                }
                if index < lines.count { index += 1 }
                append(.code(language: language.isEmpty ? nil : language,
                             source: codeLines.joined(separator: "\n")))
                continue
            }

            if let image = parseImage(line) {
                append(.image(alt: image.alt, source: image.source))
                index += 1
                continue
            }

            if let heading = parseHeading(line) {
                append(.heading(level: heading.level, text: heading.text))
                index += 1
                continue
            }

            if isDivider(line) {
                append(.divider)
                index += 1
                continue
            }

            if line.hasPrefix(">") {
                var quoteLines: [String] = []
                while index < lines.count {
                    let current = lines[index].trimmingCharacters(in: .whitespaces)
                    guard current.hasPrefix(">") else { break }
                    quoteLines.append(String(current.dropFirst()).trimmingCharacters(in: .whitespaces))
                    index += 1
                }
                append(.quote(quoteLines.joined(separator: " ")))
                continue
            }

            if index + 1 < lines.count, line.contains("|"), isTableSeparator(lines[index + 1]) {
                var rows = [tableCells(line)]
                index += 2
                while index < lines.count && lines[index].contains("|") && !lines[index].trimmingCharacters(in: .whitespaces).isEmpty {
                    rows.append(tableCells(lines[index]))
                    index += 1
                }
                append(.table(rows))
                continue
            }

            if let item = parseListItem(line) {
                append(.bullet(item))
                index += 1
                continue
            }

            var paragraph = [line]
            index += 1
            while index < lines.count {
                let next = lines[index].trimmingCharacters(in: .whitespaces)
                if next.isEmpty || beginsBlock(next, following: index + 1 < lines.count ? lines[index + 1] : nil) { break }
                paragraph.append(next)
                index += 1
            }
            append(.paragraph(paragraph.joined(separator: " ")))
        }
        return blocks
    }

    private static func beginsBlock(_ line: String, following: String?) -> Bool {
        if line.hasPrefix("```") || line.hasPrefix(">") || parseHeading(line) != nil
            || parseImage(line) != nil || isDivider(line) || parseListItem(line) != nil { return true }
        return line.contains("|") && following.map(isTableSeparator) == true
    }

    private static func parseHeading(_ line: String) -> (level: Int, text: String)? {
        let count = line.prefix(while: { $0 == "#" }).count
        guard (1...6).contains(count), line.dropFirst(count).first == " " else { return nil }
        return (count, String(line.dropFirst(count)).trimmingCharacters(in: .whitespaces))
    }

    private static func parseImage(_ line: String) -> (alt: String, source: String)? {
        guard line.hasPrefix("!["), let altEnd = line.range(of: "]("), line.last == ")" else { return nil }
        let alt = String(line[line.index(line.startIndex, offsetBy: 2)..<altEnd.lowerBound])
        let sourceStart = altEnd.upperBound
        let sourceEnd = line.index(before: line.endIndex)
        let source = String(line[sourceStart..<sourceEnd]).trimmingCharacters(in: .whitespaces)
        guard !source.isEmpty else { return nil }
        return (alt, source)
    }

    private static func parseListItem(_ line: String) -> String? {
        for prefix in ["- ", "* ", "+ "] where line.hasPrefix(prefix) {
            return String(line.dropFirst(prefix.count))
        }
        guard let dot = line.firstIndex(of: "."), dot > line.startIndex,
              line[..<dot].allSatisfy(\.isNumber), line.index(after: dot) < line.endIndex,
              line[line.index(after: dot)] == " " else { return nil }
        return String(line[line.index(dot, offsetBy: 2)...])
    }

    private static func isDivider(_ line: String) -> Bool {
        let compact = line.replacingOccurrences(of: " ", with: "")
        return compact.count >= 3 && (Set(compact) == ["-"] || Set(compact) == ["*"] || Set(compact) == ["_"])
    }

    private static func isTableSeparator(_ line: String) -> Bool {
        guard line.contains("|") else { return false }
        let cells = tableCells(line)
        return !cells.isEmpty && cells.allSatisfy { cell in
            let trimmed = cell.trimmingCharacters(in: .whitespaces)
            return trimmed.count >= 3 && trimmed.allSatisfy { $0 == "-" || $0 == ":" }
        }
    }

    private static func tableCells(_ line: String) -> [String] {
        var value = line.trimmingCharacters(in: .whitespaces)
        if value.hasPrefix("|") { value.removeFirst() }
        if value.hasSuffix("|") { value.removeLast() }
        return value.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
    }
}

struct MarkdownDocumentPanelView: View {
    @ObservedObject var model: MarkdownDocumentModel

    var body: some View {
        GeometryReader { geometry in
            let layout = MarkdownDocumentLayout(width: geometry.size.width, focused: model.mode != .grid)
            ScrollView {
                LazyVStack(spacing: 20) {
                    ForEach(model.blocks) { block in
                        let width = isImage(block) ? layout.imageWidth : layout.textColumnWidth
                        if isImage(block) || layout.showsText {
                            MarkdownDocumentBlockView(block: block, width: width, fontSize: layout.fontSize)
                                .frame(maxWidth: width, alignment: .leading)
                        }
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, model.mode == .grid ? 8 : 24)
                .padding(.horizontal, 4)
            }
            .scrollIndicators(.hidden)
        }
        .background(Color.clear)
        .preferredColorScheme(.dark)
        .accessibilityIdentifier("markdown-document-panel")
    }

    private func isImage(_ block: MarkdownDocumentBlock) -> Bool {
        if case .image = block.content { return true }
        return false
    }
}

private struct MarkdownDocumentBlockView: View {
    let block: MarkdownDocumentBlock
    let width: CGFloat
    let fontSize: CGFloat

    @ViewBuilder var body: some View {
        switch block.content {
        case let .heading(level, value):
            InlineMarkdownText(value)
                .font(.system(size: fontSize * headingScale(level), weight: .semibold))
                .frame(maxWidth: .infinity, alignment: .leading)
        case let .paragraph(value):
            InlineMarkdownText(value)
                .font(.system(size: fontSize)).lineSpacing(fontSize * 0.48)
                .frame(maxWidth: .infinity, alignment: .leading)
        case let .bullet(value):
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Circle().fill(.white.opacity(0.7)).frame(width: 4, height: 4).padding(.leading, 5)
                InlineMarkdownText(value).font(.system(size: fontSize)).lineSpacing(fontSize * 0.42)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        case let .quote(value):
            HStack(alignment: .top, spacing: 14) {
                RoundedRectangle(cornerRadius: 2).fill(.cyan.opacity(0.62)).frame(width: 3)
                InlineMarkdownText(value).font(.system(size: fontSize)).lineSpacing(fontSize * 0.45)
                    .foregroundStyle(.white.opacity(0.72))
            }
            .fixedSize(horizontal: false, vertical: true)
        case let .code(language, value):
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text(language?.uppercased() ?? "CODE")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .tracking(1).foregroundStyle(.white.opacity(0.45))
                    Spacer()
                }
                .padding(.horizontal, 14).padding(.top, 12)
                ScrollView(.horizontal) {
                    Text(value).font(.system(size: max(11, fontSize * 0.84), design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                }
            }
            .background(Color.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 12))
        case let .table(rows):
            MarkdownTable(rows: rows, fontSize: fontSize, maxWidth: width)
        case let .image(alt, source):
            BundledMarkdownImage(alt: alt, source: source, maxWidth: width)
        case .divider:
            Rectangle().fill(.white.opacity(0.13)).frame(height: 1).padding(.vertical, 4)
        }
    }

    private func headingScale(_ level: Int) -> CGFloat {
        switch level {
        case 1: 1.75
        case 2: 1.4
        case 3: 1.2
        default: 1.08
        }
    }
}

struct InlineMarkdownText: View {
    let source: String
    @State private var hasPointingHandCursor = false

    init(_ source: String) { self.source = source }

    private var renderedMarkdown: AttributedString {
        (try? AttributedString(markdown: source)) ?? AttributedString(source)
    }

    private var containsLink: Bool {
        renderedMarkdown.runs.contains { $0.link != nil }
    }

    var body: some View {
        Text(renderedMarkdown)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .tint(.cyan)
            .onHover { hovering in
                guard containsLink, hovering != hasPointingHandCursor else { return }
                hasPointingHandCursor = hovering
                if hovering { NSCursor.pointingHand.push() }
                else { NSCursor.pop() }
            }
            .onDisappear {
                if hasPointingHandCursor {
                    NSCursor.pop()
                    hasPointingHandCursor = false
                }
            }
    }
}

private struct MarkdownTable: View {
    let rows: [[String]]
    let fontSize: CGFloat
    let maxWidth: CGFloat

    private var columnCount: Int { max(1, rows.map(\.count).max() ?? 1) }
    private var columnWidth: CGFloat { min(260, max(1, maxWidth) / CGFloat(columnCount)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { rowIndex, row in
                HStack(alignment: .top, spacing: 0) {
                    ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                        InlineMarkdownText(cell)
                            .font(.system(size: fontSize * 0.86, weight: rowIndex == 0 ? .semibold : .regular))
                            .padding(.horizontal, 12).padding(.vertical, 10)
                            .frame(width: columnWidth, alignment: .leading)
                    }
                }
                Rectangle().fill(.white.opacity(0.10)).frame(height: 1)
            }
        }
        .frame(maxWidth: columnWidth * CGFloat(columnCount), alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 10))
    }
}

private struct BundledMarkdownImage: View {
    let alt: String
    let source: String
    let maxWidth: CGFloat
    @State private var copied = false

    private var image: NSImage? {
        let urlValue = URL(fileURLWithPath: source)
        let name = urlValue.deletingPathExtension().lastPathComponent
        let ext = urlValue.pathExtension
        guard !name.isEmpty, !ext.isEmpty,
              let resource = Bundle.module.url(forResource: name, withExtension: ext) else { return nil }
        return NSImage(contentsOf: resource)
    }

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxWidth: maxWidth)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .contextMenu {
                        Button("複製圖片", systemImage: "document.on.document") { copy(image) }
                    }
                    .accessibilityLabel(alt)
            } else {
                Label(alt.isEmpty ? "無法載入圖片" : alt, systemImage: "photo")
                    .font(.system(size: 13)).foregroundStyle(.white.opacity(0.48))
                    .frame(maxWidth: maxWidth, minHeight: 72)
                    .background(Color.white.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
            }
        }
        .overlay(alignment: .bottom) {
            if copied {
                Text("圖片已複製")
                    .font(.system(size: 12, weight: .medium))
                    .padding(.horizontal, 12).padding(.vertical, 7)
                    .background(.black.opacity(0.78), in: Capsule())
                    .padding(12)
            }
        }
    }

    private func copy(_ image: NSImage) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        copied = pasteboard.writeObjects([image])
        guard copied else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { copied = false }
    }
}
