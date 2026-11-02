import SwiftUI

@MainActor final class WorkspaceChromeModel: ObservableObject {
    var onPresentationChange: (() -> Void)?
    var onTestCommand: (() -> Void)?
    var onSubmitText: ((String) -> Bool)?
    @Published var recipient = "Maltose"
    @Published var panelCount = 0
    @Published var status = "就緒"
    @Published var tipsExpanded = false { didSet { if oldValue != tipsExpanded { onPresentationChange?() } } }
    @Published var settingsPresented = false { didSet { if oldValue != settingsPresented { onPresentationChange?() } } }
    @Published var draft = ""

    func submitDraft() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        if text.lowercased() == "test" {
            draft = ""; onTestCommand?(); return
        }
        if onSubmitText?(draft) == true { draft = "" }
    }

    func closeOverlays() {
        tipsExpanded = false
        settingsPresented = false
    }
}

struct WorkspaceTopChrome: View {
    @ObservedObject var model: WorkspaceChromeModel

    var body: some View {
        HStack(spacing: 14) {
            Circle().fill(Color.cyan.opacity(0.85)).frame(width: 7, height: 7)
                .shadow(color: .cyan.opacity(0.35), radius: 8)
            Text("MALTOSE").font(.system(size: 11, weight: .semibold, design: .monospaced)).tracking(2)
            Text("工作空間").font(.system(size: 13, weight: .medium))
            Text("· \(model.status)").font(.system(size: 12)).foregroundStyle(.white.opacity(0.54))
            Spacer(minLength: 8)
            Text("\(model.panelCount) 個面板").font(.system(size: 11, design: .monospaced)).foregroundStyle(.white.opacity(0.52))
            Button {
                withAnimation(.easeInOut(duration: 0.18)) { model.tipsExpanded.toggle() }
                model.settingsPresented = false
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: "lightbulb")
                    Text("使用提示")
                    Image(systemName: model.tipsExpanded ? "chevron.up" : "chevron.down").font(.system(size: 9, weight: .semibold))
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.white.opacity(0.82))
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(.white.opacity(0.07), in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("使用提示")
        }
        .foregroundStyle(.white.opacity(0.92))
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(LinearGradient(colors: [.black.opacity(0.42), .black.opacity(0.12)], startPoint: .top, endPoint: .bottom))
    }
}

struct WorkspaceBottomChrome: View {
    @ObservedObject var model: WorkspaceChromeModel

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "command")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.white.opacity(0.48))
            Text(model.recipient).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
            TextField("輸入想法或指令…", text: $model.draft, axis: .vertical)
                .lineLimit(1...3)
                .textFieldStyle(.plain)
                .font(.system(size: 14))
                .foregroundStyle(.white.opacity(0.92))
                .accessibilityLabel("空間輸入")
                .onSubmit { model.submitDraft() }
            Button {
                model.tipsExpanded = false
                model.settingsPresented.toggle()
            } label: {
                Image(systemName: "gearshape")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.white.opacity(0.78))
                    .frame(width: 34, height: 34)
                    .background(.white.opacity(0.07), in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("設定")
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(.ultraThinMaterial.opacity(0.8), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(.white.opacity(0.12), lineWidth: 1))
        .frame(maxWidth: 760)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 24)
        .background(LinearGradient(colors: [.black.opacity(0.08), .black.opacity(0.45)], startPoint: .top, endPoint: .bottom))
    }
}

struct WorkspaceTipsDropdown: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "sparkle").foregroundStyle(.cyan)
                Text("快速提示").font(.system(size: 14, weight: .semibold))
                Spacer()
                Text("ESC 關閉").font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.42))
            }
            VStack(alignment: .leading, spacing: 10) {
                tip("Ctrl + 滾輪", "縮放所有面板；一般滾動瀏覽整個網格。")
                tip("拖曳空白處", "框選多個面板；按住 Command 可加入既有選取。")
                tip("雙擊玻璃邊框", "放大或還原面板，回到全局模式時會保留網格位置。")
                tip("拖曳玻璃邊框", "把面板移至另一個螢幕的窗口。")
            }
        }
        .padding(18)
        .foregroundStyle(.white.opacity(0.92))
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.13), lineWidth: 1))
        .frame(maxWidth: 420)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .contain)
    }

    private func tip(_ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(title).font(.system(size: 11, weight: .medium, design: .monospaced)).foregroundStyle(.cyan.opacity(0.9)).frame(width: 112, alignment: .leading)
            Text(detail).font(.system(size: 12)).foregroundStyle(.white.opacity(0.7)).fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct WorkspaceSettingsPlaceholder: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("空間設定", systemImage: "gearshape").font(.system(size: 15, weight: .semibold))
            Text("偏好設定入口已就緒。設定項目會在後續設計階段加入。")
                .font(.system(size: 12)).foregroundStyle(.white.opacity(0.68))
        }
        .padding(18)
        .foregroundStyle(.white.opacity(0.92))
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.13), lineWidth: 1))
        .frame(maxWidth: 360, alignment: .leading)
    }
}
