import AppKit
import MetalKit
import SwiftUI

struct EntityVisualParameters: Equatable {
    var energy: Float = 0.20
    var coherence: Float = 0.82
    var complexity: Float = 0.35
    var focus: Float = 0.28
    var arousal: Float = 0.22
    var expansion: Float = 0.38
    var audioLevel: Float = 0.0
    var attentionX: Float = 0.0
    var attentionY: Float = 0.0

    static let defaults = EntityVisualParameters()

    func clamped() -> EntityVisualParameters {
        var result = self
        result.energy = energy.clamped(to: 0...1)
        result.coherence = coherence.clamped(to: 0...1)
        result.complexity = complexity.clamped(to: 0...1)
        result.focus = focus.clamped(to: 0...1)
        result.arousal = arousal.clamped(to: 0...1)
        result.expansion = expansion.clamped(to: 0...1)
        result.audioLevel = audioLevel.clamped(to: 0...1)
        result.attentionX = attentionX.clamped(to: -1...1)
        result.attentionY = attentionY.clamped(to: -1...1)
        return result
    }
}

private extension Float {
    func clamped(to range: ClosedRange<Float>) -> Float { min(range.upperBound, max(range.lowerBound, self)) }
}

enum EntityPreset: String, CaseIterable, Identifiable, Codable {
    case idle, listening, thinking, speaking, executing
    var id: String { rawValue }
    var title: String {
        switch self {
        case .idle: "待機"
        case .listening: "聆聽"
        case .thinking: "思考"
        case .speaking: "說話"
        case .executing: "執行"
        }
    }
    var symbol: String {
        switch self {
        case .idle: "moon.stars"
        case .listening: "waveform"
        case .thinking: "sparkle"
        case .speaking: "wave.3.right"
        case .executing: "arrow.trianglehead.2.clockwise.rotate.90"
        }
    }
    var visualStyle: EntityVisualStyle { EntityVisualStyle(rawValue: Self.allCases.firstIndex(of: self) ?? 0) ?? .idle }
    var parameters: EntityVisualParameters {
        switch self {
        case .idle:
            .init(energy: 0.10, coherence: 0.96, complexity: 0.12, focus: 0.18,
                  arousal: 0.10, expansion: 0.22, audioLevel: 0, attentionX: 0, attentionY: 0)
        case .listening:
            .init(energy: 0.46, coherence: 0.80, complexity: 0.38, focus: 0.94,
                  arousal: 0.42, expansion: 0.46, audioLevel: 0.32, attentionX: 0, attentionY: 0.12)
        case .thinking:
            .init(energy: 0.68, coherence: 0.30, complexity: 0.98, focus: 0.92,
                  arousal: 0.76, expansion: 0.58, audioLevel: 0, attentionX: 0.08, attentionY: 0.14)
        case .speaking:
            .init(energy: 0.76, coherence: 0.72, complexity: 0.54, focus: 0.78,
                  arousal: 0.92, expansion: 0.74, audioLevel: 0.82, attentionX: 0, attentionY: 0)
        case .executing:
            .init(energy: 0.96, coherence: 0.88, complexity: 0.76, focus: 1.0,
                  arousal: 0.88, expansion: 0.66, audioLevel: 0.08, attentionX: 0.34, attentionY: -0.04)
        }
    }
}

enum EntityVisualStyle: Int, CaseIterable {
    case idle, listening, thinking, speaking, executing
}

enum EntityQuality: String, CaseIterable, Identifiable {
    case low, medium, high
    var id: String { rawValue }
    var title: String {
        switch self {
        case .low: "低"
        case .medium: "中"
        case .high: "高"
        }
    }
    var particleCount: Int {
        switch self {
        case .low: 420
        case .medium: 1_400
        case .high: 3_200
        }
    }
    var filamentCount: Int {
        switch self {
        case .low: 90
        case .medium: 300
        case .high: 720
        }
    }
}

enum EntityEvent: Equatable {
    case success, error
    var title: String { self == .success ? "成功" : "錯誤" }
}

@MainActor private final class EntityPlaygroundModel: ObservableObject {
    @Published var parameters = EntityVisualParameters.defaults
    @Published var preset: EntityPreset = .idle
    @Published var quality: EntityQuality = .medium
    @Published var isAudioSimulationEnabled = false
    @Published var eventLabel = ""
    @Published var fps = 0
    @Published var renderResolution = "—"
    @Published var displayedParticleCount = EntityQuality.medium.particleCount

    private weak var renderer: MetalEntityRenderer?
    private var simulationStart = Date().timeIntervalSinceReferenceDate
    @Published var hasManualOverrides = false

    var statusTitle: String { hasManualOverrides ? "自訂" : preset.title }

    func apply(_ preset: EntityPreset) {
        self.preset = preset
        hasManualOverrides = false
        withAnimation(.easeInOut(duration: 0.65)) { parameters = preset.parameters }
        renderer?.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
    }

    func setParameter(_ keyPath: WritableKeyPath<EntityVisualParameters, Float>, to value: Double) {
        var updated = parameters
        updated[keyPath: keyPath] = Float(value)
        parameters = updated.clamped()
        hasManualOverrides = true
        renderer?.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
    }

    func setQuality(_ quality: EntityQuality) {
        self.quality = quality
        renderer?.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
    }

    func attach(_ renderer: MetalEntityRenderer) {
        self.renderer = renderer
        renderer.onStatistics = { [weak self] fps, size, count in
            Task { @MainActor in
                self?.fps = fps
                self?.renderResolution = "\(Int(size.width)) × \(Int(size.height)) px"
                self?.displayedParticleCount = count
            }
        }
        renderer.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
    }

    func detach(_ renderer: MetalEntityRenderer) {
        if self.renderer === renderer { self.renderer = nil }
        renderer.stop()
    }

    func trigger(_ event: EntityEvent) {
        eventLabel = event == .success ? "成功脈衝" : "受控擾動"
        renderer?.trigger(event: event)
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(1.8))
            if self.eventLabel == (event == .success ? "成功脈衝" : "受控擾動") { self.eventLabel = "" }
        }
    }

    func reset() {
        preset = .idle
        quality = .medium
        isAudioSimulationEnabled = false
        eventLabel = ""
        hasManualOverrides = false
        simulationStart = Date().timeIntervalSinceReferenceDate
        withAnimation(.easeInOut(duration: 0.65)) { parameters = EntityVisualParameters.defaults }
        renderer?.clearEvent()
        renderer?.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
    }

    func updateMockAudio(now: TimeInterval) {
        guard isAudioSimulationEnabled else { return }
        let t = now - simulationStart
        var updated = parameters
        let envelope = 0.5 + 0.5 * sin(t * 1.9)
        updated.audioLevel = Float(max(0, (0.12 + 0.76 * envelope) * (0.55 + 0.45 * sin(t * 4.3))))
        parameters = updated
        renderer?.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
    }

    func toggleAudioSimulation() {
        isAudioSimulationEnabled.toggle()
        if isAudioSimulationEnabled {
            simulationStart = Date().timeIntervalSinceReferenceDate
        } else {
            var updated = parameters
            updated.audioLevel = 0
            parameters = updated
            renderer?.setTargets(parameters: parameters, particleCount: quality.particleCount, filamentCount: quality.filamentCount, style: preset.visualStyle)
        }
    }
}

private struct EntityParameterControl: Identifiable {
    let title: String
    let keyPath: WritableKeyPath<EntityVisualParameters, Float>
    let range: ClosedRange<Double>
    var id: String { title }
}

struct AgentCoreAnimationTestView: View {
    @StateObject private var model = EntityPlaygroundModel()

    private let controls: [EntityParameterControl] = [
        .init(title: "Energy", keyPath: \.energy, range: 0...1),
        .init(title: "Coherence", keyPath: \.coherence, range: 0...1),
        .init(title: "Complexity", keyPath: \.complexity, range: 0...1),
        .init(title: "Focus", keyPath: \.focus, range: 0...1),
        .init(title: "Arousal", keyPath: \.arousal, range: 0...1),
        .init(title: "Expansion", keyPath: \.expansion, range: 0...1),
        .init(title: "Audio level", keyPath: \.audioLevel, range: 0...1),
        .init(title: "Attention X", keyPath: \.attentionX, range: -1...1),
        .init(title: "Attention Y", keyPath: \.attentionY, range: -1...1)
    ]

    var body: some View {
        VStack(spacing: 0) {
            header
            HStack(spacing: 0) {
                entityView
                Rectangle().fill(.white.opacity(0.08)).frame(width: 1)
                controlsPanel
                    .frame(width: 310)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .padding(22)
        .foregroundStyle(Color(white: 0.9))
        .background(Color(red: 0.025, green: 0.039, blue: 0.059))
        .preferredColorScheme(.dark)
        .task(id: model.isAudioSimulationEnabled) {
            guard model.isAudioSimulationEnabled else { return }
            while !Task.isCancelled {
                model.updateMockAudio(now: Date().timeIntervalSinceReferenceDate)
                try? await Task.sleep(for: .milliseconds(33))
            }
        }
        .accessibilityElement(children: .contain)
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 5) {
                Text("Maltose Visual Entity")
                    .font(.system(size: 18, weight: .semibold))
                Text("連續程序動畫 · Metal Playground")
                    .font(.system(size: 10, design: .monospaced))
                    .tracking(0.8)
                    .foregroundStyle(.white.opacity(0.44))
            }
            Spacer()
            HStack(spacing: 14) {
                statistic("FPS", value: model.fps > 0 ? "\(model.fps)" : "—")
                statistic("PARTICLES", value: model.displayedParticleCount.formatted())
                statistic("RENDER", value: model.renderResolution)
            }
        }
        .padding(.bottom, 14)
    }

    private var entityView: some View {
        ZStack(alignment: .bottomLeading) {
            MetalVisualEntityView(parameters: model.parameters,
                                  particleCount: model.quality.particleCount,
                                  filamentCount: model.quality.filamentCount,
                                  model: model)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 7) {
                    Circle().fill(.cyan.opacity(0.9)).frame(width: 5, height: 5)
                    Text(model.statusTitle.uppercased())
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .tracking(1.3)
                }
                if !model.eventLabel.isEmpty {
                    Text(model.eventLabel).font(.system(size: 10, design: .monospaced)).foregroundStyle(.cyan.opacity(0.78))
                }
            }
            .foregroundStyle(.white.opacity(0.55))
            .padding(14)
            .allowsHitTesting(false)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black.opacity(0.20))
        .accessibilityLabel("Maltose Visual Entity 即時渲染區")
    }

    private var controlsPanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    sectionTitle("STATE PRESETS")
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 7) {
                        ForEach(EntityPreset.allCases) { preset in
                            Button { model.apply(preset) } label: {
                                Label(preset.title, systemImage: preset.symbol)
                                    .font(.system(size: 10, weight: .medium))
                                    .frame(maxWidth: .infinity, minHeight: 30)
                                    .foregroundStyle(model.preset == preset ? .white : .white.opacity(0.62))
                                    .background(model.preset == preset ? .cyan.opacity(0.18) : .white.opacity(0.045),
                                                in: RoundedRectangle(cornerRadius: 7, style: .continuous))
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("切換到\(preset.title)預設")
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 5) {
                    sectionTitle("VISUAL PARAMETERS")
                    ForEach(controls) { control in
                        parameterSlider(control)
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    sectionTitle("EVENTS & AUDIO")
                    HStack(spacing: 7) {
                        eventButton("成功", symbol: "checkmark", tint: .cyan) { model.trigger(.success) }
                        eventButton("錯誤", symbol: "exclamationmark", tint: .purple) { model.trigger(.error) }
                    }
                    Button {
                        model.toggleAudioSimulation()
                    } label: {
                        Label(model.isAudioSimulationEnabled ? "停止音訊模擬" : "模擬音訊輸入",
                              systemImage: model.isAudioSimulationEnabled ? "pause.fill" : "waveform")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.white.opacity(0.72))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                }

                VStack(alignment: .leading, spacing: 7) {
                    sectionTitle("QUALITY")
                    Picker("渲染品質", selection: Binding(get: { model.quality }, set: { model.setQuality($0) })) {
                        ForEach(EntityQuality.allCases) { quality in
                            Text("\(quality.title) · \(quality.particleCount.formatted())").tag(quality)
                        }
                    }
                    .pickerStyle(.segmented)
                    .accessibilityLabel("渲染品質")
                    Button("重設預設值", systemImage: "arrow.counterclockwise") { model.reset() }
                        .font(.system(size: 10))
                        .buttonStyle(.plain)
                        .foregroundStyle(.white.opacity(0.55))
                        .padding(.top, 3)
                }
            }
            .padding(.leading, 16)
            .padding(.trailing, 3)
            .padding(.vertical, 5)
        }
        .scrollIndicators(.hidden)
    }

    private func parameterSlider(_ control: EntityParameterControl) -> some View {
        let binding = Binding<Double>(
            get: { Double(model.parameters[keyPath: control.keyPath]) },
            set: { model.setParameter(control.keyPath, to: $0) }
        )
        return VStack(spacing: 1) {
            HStack {
                Text(control.title).foregroundStyle(.white.opacity(0.63))
                Spacer()
                Text(String(format: control.range.lowerBound < 0 ? "%+.2f" : "%.2f", binding.wrappedValue))
                    .monospacedDigit().foregroundStyle(.white.opacity(0.38))
            }
            .font(.system(size: 9, design: .monospaced))
            Slider(value: binding, in: control.range)
                .tint(.cyan.opacity(0.76))
                .accessibilityLabel(control.title)
        }
    }

    private func eventButton(_ title: String, symbol: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.system(size: 10, weight: .medium))
                .frame(maxWidth: .infinity, minHeight: 30)
                .foregroundStyle(tint.opacity(0.88))
                .background(tint.opacity(0.09), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title).font(.system(size: 8, weight: .semibold, design: .monospaced))
            .tracking(1.2).foregroundStyle(.white.opacity(0.36))
    }

    private func statistic(_ title: String, value: String) -> some View {
        VStack(alignment: .trailing, spacing: 4) {
            Text(title).font(.system(size: 7, weight: .medium, design: .monospaced)).tracking(1).foregroundStyle(.white.opacity(0.34))
            Text(value).font(.system(size: 9, design: .monospaced)).foregroundStyle(.white.opacity(0.66))
        }
    }
}

@MainActor final class AgentIdentityAnimationModel: ObservableObject {
    static let shared = AgentIdentityAnimationModel()

    @Published private(set) var preset: EntityPreset = .idle
    private weak var renderer: MetalEntityRenderer?
    private var testTask: Task<Void, Never>?

    private init() {}

    func attach(_ renderer: MetalEntityRenderer) {
        self.renderer = renderer
        apply(preset)
    }

    func detach(_ renderer: MetalEntityRenderer) {
        if self.renderer === renderer { self.renderer = nil }
        renderer.stop()
    }

    func runStateTest() {
        testTask?.cancel()
        testTask = Task { @MainActor [weak self] in
            guard let self else { return }
            for state in EntityPreset.allCases {
                guard !Task.isCancelled else { return }
                self.apply(state)
                do { try await Task.sleep(for: .seconds(3)) }
                catch { return }
            }
            guard !Task.isCancelled else { return }
            self.apply(.idle)
            self.testTask = nil
        }
    }

    func setState(_ preset: EntityPreset) {
        testTask?.cancel()
        testTask = nil
        apply(preset)
    }

    private func apply(_ preset: EntityPreset) {
        self.preset = preset
        var parameters = preset.parameters
        if preset == .idle { parameters.expansion = 0.42 }
        renderer?.setTargets(parameters: parameters, particleCount: EntityQuality.medium.particleCount,
                             filamentCount: EntityQuality.medium.filamentCount, style: preset.visualStyle)
    }
}

struct AgentIdentityPanelView: View {
    @ObservedObject private var model = AgentIdentityAnimationModel.shared

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            MetalVisualEntityView(parameters: model.preset == .idle ? idleParameters : model.preset.parameters,
                                  particleCount: EntityQuality.medium.particleCount,
                                  filamentCount: EntityQuality.medium.filamentCount,
                                  model: nil,
                                  identityModel: model)
            HStack(spacing: 7) {
                Circle().fill(.cyan.opacity(0.86)).frame(width: 5, height: 5)
                Text("MALTOSE · \(model.preset.title.uppercased())")
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .tracking(1.1)
                    .foregroundStyle(.white.opacity(0.48))
            }
            .padding(18)
            .allowsHitTesting(false)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.clear)
        .preferredColorScheme(.dark)
        .accessibilityLabel("Maltose 形象面板，\(model.preset.title)動畫")
    }

    private var idleParameters: EntityVisualParameters {
        var parameters = EntityPreset.idle.parameters
        parameters.expansion = 0.42
        return parameters
    }
}

private struct MetalVisualEntityView: NSViewRepresentable {
    let parameters: EntityVisualParameters
    let particleCount: Int
    let filamentCount: Int
    let model: EntityPlaygroundModel?
    var identityModel: AgentIdentityAnimationModel? = nil

    func makeCoordinator() -> Coordinator { Coordinator(model: model, identityModel: identityModel) }

    func makeNSView(context: Context) -> MTKView {
        let view = MTKView(frame: .zero, device: MTLCreateSystemDefaultDevice())
        view.colorPixelFormat = .bgra8Unorm
        view.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
        view.isPaused = false
        view.enableSetNeedsDisplay = false
        view.preferredFramesPerSecond = 60
        view.framebufferOnly = true
        view.layer?.isOpaque = false
        if let renderer = MetalEntityRenderer(view: view) {
            context.coordinator.renderer = renderer
            if let model {
                model.attach(renderer)
            } else if let identityModel {
                identityModel.attach(renderer)
            } else {
                renderer.setTargets(parameters: parameters, particleCount: particleCount,
                                    filamentCount: filamentCount, style: .idle)
            }
        }
        return view
    }

    func updateNSView(_ view: MTKView, context: Context) {
        context.coordinator.renderer?.setTargets(parameters: parameters, particleCount: particleCount,
                                                  filamentCount: filamentCount,
                                                  style: model?.preset.visualStyle ?? identityModel?.preset.visualStyle ?? .idle)
    }

    static func dismantleNSView(_ view: MTKView, coordinator: Coordinator) {
        if let renderer = coordinator.renderer {
            if let model = coordinator.model { model.detach(renderer) }
            else if let identityModel = coordinator.identityModel { identityModel.detach(renderer) }
            else { renderer.stop() }
        }
        view.delegate = nil
    }

    @MainActor final class Coordinator {
        let model: EntityPlaygroundModel?
        let identityModel: AgentIdentityAnimationModel?
        var renderer: MetalEntityRenderer?
        init(model: EntityPlaygroundModel?, identityModel: AgentIdentityAnimationModel?) {
            self.model = model
            self.identityModel = identityModel
        }
    }
}
