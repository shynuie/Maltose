import AppKit
import SwiftUI

/// UI-only model. Content has no dependency on the Host or an Agent document.
struct WorkspacePanel: Identifiable {
    enum Kind { case canvas, notes, chart, table }
    let id: String
    let title: String
    let kind: Kind

    @MainActor func makeContentView() -> NSView {
        let view = NSHostingView(rootView: WorkspaceSampleContent(panel: self))
        view.sizingOptions = []
        return view
    }

    static let samples: [WorkspacePanel] = [
        .init(id: "canvas", title: "畫布", kind: .canvas),
        .init(id: "notes", title: "筆記", kind: .notes),
        .init(id: "chart", title: "圖表", kind: .chart),
        .init(id: "table", title: "資料", kind: .table)
    ]

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
            case .chart:
                Canvas { context, size in
                    for row in 0...4 {
                        let y = size.height * CGFloat(row) / 4
                        var line = Path(); line.move(to: CGPoint(x: 0, y: y)); line.addLine(to: CGPoint(x: size.width, y: y))
                        context.stroke(line, with: .color(.white.opacity(0.07)), lineWidth: 1)
                    }
                    var curve = Path()
                    for i in 0...100 {
                        let t = CGFloat(i) / 100
                        let point = CGPoint(x: t * size.width, y: size.height * (0.55 - 0.20 * sin(t * 9) - 0.12 * t))
                        if i == 0 { curve.move(to: point) } else { curve.addLine(to: point) }
                    }
                    context.stroke(curve, with: .color(Color(red: 0.38, green: 0.80, blue: 0.82)), lineWidth: 2)
                }.accessibilityLabel("示意曲線圖，無外部資料")
                HStack { Text("00:00"); Spacer(); Text("06:00"); Spacer(); Text("12:00") }.font(.caption).foregroundStyle(.secondary)
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
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .foregroundStyle(Color(white: 0.88))
        .background(Color(red: 0.035, green: 0.052, blue: 0.075))
        .preferredColorScheme(.dark)
    }
}
