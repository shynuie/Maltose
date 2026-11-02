import SwiftUI

struct WorkProgressRing: View {
    var state: WorkProgressState
    var fraction: Double?
    var size: CGFloat = 30
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var rotating = false
    @State private var showCheck = false
    @State private var displayedFraction: Double?
    @State private var appeared = false
    private var color: Color {
        switch state {
        case .completed: .green
        case .failed: .orange
        case .paused, .needsInput, .uncertain: .yellow
        case .cancelled: .secondary
        default: .cyan
        }
    }
    var body: some View {
        ZStack {
            if showCheck {
                Image(systemName: "checkmark").font(.system(size: size * 0.58, weight: .semibold))
                    .foregroundStyle(color).transition(.opacity.combined(with: .scale(scale: 0.8)))
            } else {
                Circle().stroke(.white.opacity(0.12), lineWidth: 2.5)
                Circle().trim(from: 0, to: CGFloat(max(0, min(1, displayedFraction ?? fraction ?? 0.24))))
                    .stroke(color, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .rotationEffect(.degrees(-90 + (fraction == nil && state.animated && rotating && !reduceMotion ? 360 : 0)))
                    .animation(fraction == nil && state.animated && !reduceMotion ? .linear(duration: 1.4).repeatForever(autoreverses: false) : .default, value: rotating)
                if state == .paused { Image(systemName: "pause.fill").font(.system(size: size * 0.30)).foregroundStyle(color) }
                if state == .failed || state == .uncertain { Image(systemName: "exclamationmark").font(.system(size: size * 0.40, weight: .semibold)).foregroundStyle(color) }
                if state == .cancelled { Image(systemName: "xmark").font(.system(size: size * 0.34)).foregroundStyle(color) }
            }
        }
        .padding(2).frame(width: size, height: size)
        .onAppear { rotating = true }
        .task(id: state) {
            if state == .completed {
                if appeared && !reduceMotion {
                    withAnimation(.easeOut(duration: 0.18)) { displayedFraction = 1 }
                    try? await Task.sleep(for: .milliseconds(220))
                    guard !Task.isCancelled else { return }
                }
                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.18)) { showCheck = true }
            } else {
                showCheck = false; displayedFraction = fraction
                rotating = false; DispatchQueue.main.async { rotating = true }
            }
            appeared = true
        }
        .onChange(of: fraction) { _, value in if state != .completed { displayedFraction = value } }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.28), value: state)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.28), value: fraction)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.title)
        .accessibilityValue(fraction.map { "\(Int(($0 * 100).rounded()))%" } ?? "進度尚無法估算")
    }
}

struct TaskProgressPanelView: View {
    @ObservedObject var model: AgentWorkMonitor
    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width < 420
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("任務進度").font(.system(size: 23, weight: .medium))
                    Spacer()
                    Text("\(model.roots.count) 個任務").font(.system(size: 12)).foregroundStyle(.secondary)
                }
                if model.roots.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Image(systemName: "circle.dashed").font(.system(size: 28)).foregroundStyle(.white.opacity(0.4))
                        Text("等待下一個任務").font(.system(size: 17))
                        Text("多步驟任務會在這裡顯示，可展開查看子任務。").font(.system(size: 13)).foregroundStyle(.secondary)
                    }.padding(.top, 18)
                    Spacer()
                } else {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 0) {
                                ForEach(model.rows) { row in
                                    taskRow(row, compact: compact).id(row.id)
                                }
                            }
                        }
                        .scrollIndicators(.automatic)
                        .onAppear {
                            if let value = model.selectedTaskID { proxy.scrollTo("task:\(value)", anchor: .top) }
                        }
                        .onChange(of: model.selectionRevision) { _, _ in
                            if let value = model.selectedTaskID { withAnimation { proxy.scrollTo("task:\(value)", anchor: .top) } }
                        }
                    }
                }
            }
            .padding(compact ? 20 : 28)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .foregroundStyle(Color(white: 0.90))
        }
    }
    private func taskRow(_ row: AgentWorkMonitor.Row, compact: Bool) -> some View {
        let node = row.node, primary = row.depth == 0
        return HStack(alignment: .top, spacing: compact ? 9 : 13) {
            Button { model.toggle(node.id) } label: {
                Image(systemName: model.collapsed.contains(node.id) ? "chevron.right" : "chevron.down")
                    .font(.system(size: 10, weight: .semibold)).foregroundStyle(.white.opacity(0.50))
                    .frame(width: 13, height: primary ? 34 : 24)
                    .contentShape(Rectangle())
            }.buttonStyle(.plain).opacity(node.children.isEmpty ? 0 : 1).disabled(node.children.isEmpty)
                .accessibilityLabel((model.collapsed.contains(node.id) ? "展開" : "收起") + node.title)
            WorkProgressRing(state: node.state, fraction: node.fraction, size: primary ? 34 : 24)
            VStack(alignment: .leading, spacing: 6) {
                Text(node.title).font(.system(size: primary ? 17 : 14, weight: primary ? .medium : .regular))
                    .lineLimit(primary ? 3 : 2).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    Text(node.state.title)
                    if !node.engine.isEmpty { Text(node.engine).foregroundStyle(.white.opacity(0.35)) }
                    if let fraction = node.fraction, node.state != .completed { Text("\(Int((fraction * 100).rounded()))%").monospacedDigit() }
                }.font(.system(size: 11)).foregroundStyle(.white.opacity(0.5))
                if !node.detail.isEmpty {
                    Text(node.detail).font(.system(size: 12)).foregroundStyle(.white.opacity(0.45)).lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.leading, CGFloat(min(row.depth, 8)) * (compact ? 12 : 19))
        .padding(.vertical, primary ? 16 : 11)
        .overlay(alignment: .bottom) { if primary { Rectangle().fill(.white.opacity(0.08)).frame(height: 1) } }
        .accessibilityElement(children: .contain)
    }
}

struct AgentActivityPanelView: View {
    @ObservedObject var model: AgentWorkMonitor
    private let bottom = "activity-bottom"
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("工作日誌").font(.system(size: 23, weight: .medium))
                Spacer()
                Text("本次啟動").font(.system(size: 12)).foregroundStyle(.secondary)
            }
            if model.entries.isEmpty {
                Text("Agent 開始工作後，這裡會顯示正在執行的動作。").font(.system(size: 14)).foregroundStyle(.secondary)
                    .padding(.top, 18)
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 19) {
                            ForEach(model.entries) { entry in
                                HStack(alignment: .top, spacing: 13) {
                                    Text(entry.date, style: .time).font(.system(size: 11, design: .monospaced))
                                        .foregroundStyle(.white.opacity(0.35)).frame(width: 64, alignment: .leading)
                                    Circle().fill(entry.failed ? Color.orange : Color.cyan.opacity(0.65)).frame(width: 5, height: 5).padding(.top, 5)
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(entry.engine).font(.system(size: 11, weight: .medium)).foregroundStyle(.white.opacity(0.45))
                                        Text(entry.text + (entry.repetitions > 1 ? " ×\(entry.repetitions)" : ""))
                                            .font(.system(size: 14)).fixedSize(horizontal: false, vertical: true)
                                        if let id = entry.taskID {
                                            Button("查看任務 ↗") { model.selectTask(id) }.buttonStyle(.plain)
                                                .font(.system(size: 11)).foregroundStyle(.cyan.opacity(0.85))
                                        }
                                    }
                                    Spacer(minLength: 0)
                                }
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                            .background(ConversationScrollObserver(state: model.scrollState))
                        Color.clear.frame(height: 1).id(bottom)
                    }
                    .scrollIndicators(.automatic)
                    .onAppear { follow(proxy) }
                    .onChange(of: model.entries) { _, _ in follow(proxy) }
                }
            }
        }
        .padding(28).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .foregroundStyle(Color(white: 0.90))
    }
    private func follow(_ proxy: ScrollViewProxy) {
        guard model.scrollState.shouldFollow() else { return }
        DispatchQueue.main.async {
            guard model.scrollState.shouldFollow() else { return }
            proxy.scrollTo(bottom, anchor: .bottom)
        }
    }
}
