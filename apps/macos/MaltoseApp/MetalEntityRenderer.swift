import AppKit
import Metal
import MetalKit
import QuartzCore
import simd

private struct EntityUniforms {
    var motion: SIMD4<Float>
    var response: SIMD4<Float>
    var attention: SIMD4<Float>
    var style: SIMD4<Float>
    var event: SIMD4<Float>
}

@MainActor final class MetalEntityRenderer: NSObject, MTKViewDelegate {
    private let device: MTLDevice
    private let commandQueue: MTLCommandQueue
    private let particlePipeline: MTLRenderPipelineState
    private let filamentPipeline: MTLRenderPipelineState
    private let corePhotonPipeline: MTLRenderPipelineState
    private let particleBuffer: MTLBuffer
    private let linkBuffer: MTLBuffer
    private let maxParticleCount = 5_000
    private let maxFilamentCount = 1_000
    private let parameterLock = NSLock()
    private weak var view: MTKView?
    private var targets = EntityVisualParameters.defaults
    private var current = EntityVisualParameters.defaults
    private var targetParticleCount = 1_400
    private var targetFilamentCount = 300
    private var targetStyle = EntityVisualStyle.idle
    private var currentStyle = SIMD4<Float>(1, 0, 0, 0)
    private var currentExecuteStyle: Float = 0
    private var elapsed: Float = 0
    private var lastFrameTime = CACurrentMediaTime()
    private var eventStrength: Float = 0
    private var eventKind: Float = 0
    private var statisticsFrames = 0
    private var statisticsStart = CACurrentMediaTime()
    var onStatistics: ((Int, CGSize, Int) -> Void)?

    init?(view: MTKView) {
        guard let device = view.device ?? MTLCreateSystemDefaultDevice(),
              let commandQueue = device.makeCommandQueue() else { return nil }
        self.device = device
        self.commandQueue = commandQueue
        self.view = view

        let particleSeeds = Self.makeParticleSeeds(count: maxParticleCount)
        let links = Self.makeLinks(from: particleSeeds, count: maxFilamentCount)
        guard let particleBuffer = particleSeeds.withUnsafeBytes({ bytes in
            device.makeBuffer(bytes: bytes.baseAddress!, length: bytes.count, options: .storageModeShared)
        }), let linkBuffer = links.withUnsafeBytes({ bytes in
            device.makeBuffer(bytes: bytes.baseAddress!, length: bytes.count, options: .storageModeShared)
        }) else { return nil }
        self.particleBuffer = particleBuffer
        self.linkBuffer = linkBuffer

        do {
            let library = try device.makeLibrary(source: Self.shaderSource, options: nil)
            guard let particleVertex = library.makeFunction(name: "particleVertex"),
                  let particleFragment = library.makeFunction(name: "particleFragment"),
                  let filamentVertex = library.makeFunction(name: "filamentVertex"),
                  let filamentFragment = library.makeFunction(name: "filamentFragment"),
                  let corePhotonVertex = library.makeFunction(name: "corePhotonVertex"),
                  let corePhotonFragment = library.makeFunction(name: "corePhotonFragment") else { return nil }
            particlePipeline = try Self.makePipeline(device: device, vertex: particleVertex, fragment: particleFragment, topology: .triangle)
            filamentPipeline = try Self.makePipeline(device: device, vertex: filamentVertex, fragment: filamentFragment, topology: .line)
            corePhotonPipeline = try Self.makePipeline(device: device, vertex: corePhotonVertex, fragment: corePhotonFragment, topology: .triangle)
        } catch {
            NSLog("Maltose visual entity Metal setup failed: %@", String(describing: error))
            return nil
        }

        super.init()
        view.device = device
        view.delegate = self
        view.colorPixelFormat = .bgra8Unorm
        view.clearColor = MTLClearColor(red: 0.008, green: 0.014, blue: 0.026, alpha: 0)
        view.preferredFramesPerSecond = 60
        view.isPaused = false
        view.enableSetNeedsDisplay = false
    }

    private static func makePipeline(device: MTLDevice, vertex: MTLFunction, fragment: MTLFunction,
                                     topology: MTLPrimitiveTopologyClass) throws -> MTLRenderPipelineState {
        let descriptor = MTLRenderPipelineDescriptor()
        descriptor.vertexFunction = vertex
        descriptor.fragmentFunction = fragment
        descriptor.colorAttachments[0].pixelFormat = .bgra8Unorm
        descriptor.inputPrimitiveTopology = topology
        if let attachment = descriptor.colorAttachments[0] {
            attachment.isBlendingEnabled = true
            attachment.rgbBlendOperation = .add
            attachment.alphaBlendOperation = .add
            attachment.sourceRGBBlendFactor = .sourceAlpha
            attachment.destinationRGBBlendFactor = .one
            attachment.sourceAlphaBlendFactor = .one
            attachment.destinationAlphaBlendFactor = .oneMinusSourceAlpha
        }
        return try device.makeRenderPipelineState(descriptor: descriptor)
    }

    func setTargets(parameters: EntityVisualParameters, particleCount: Int, filamentCount: Int, style: EntityVisualStyle) {
        parameterLock.lock(); defer { parameterLock.unlock() }
        targets = parameters.clamped()
        targetParticleCount = min(maxParticleCount, max(300, particleCount))
        targetFilamentCount = min(maxFilamentCount, max(0, filamentCount))
        targetStyle = style
    }

    func trigger(event: EntityEvent) {
        parameterLock.lock(); defer { parameterLock.unlock() }
        eventStrength = 1
        eventKind = event == .success ? 1 : -1
    }

    func clearEvent() {
        parameterLock.lock(); defer { parameterLock.unlock() }
        eventStrength = 0
        eventKind = 0
    }

    func stop() { view?.delegate = nil; view?.isPaused = true }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {}

    func draw(in view: MTKView) {
        guard view.window?.isVisible != false,
              let drawable = view.currentDrawable,
              let pass = view.currentRenderPassDescriptor,
              let commandBuffer = commandQueue.makeCommandBuffer(),
              let encoder = commandBuffer.makeRenderCommandEncoder(descriptor: pass) else { return }

        let now = CACurrentMediaTime()
        let deltaTime = Float(min(1.0 / 30.0, max(0, now - lastFrameTime)))
        lastFrameTime = now
        elapsed += deltaTime

        parameterLock.lock()
        let target = targets
        let style = targetStyle
        let particleCount = min(maxParticleCount, targetParticleCount)
        let baseFilamentCount = min(min(maxFilamentCount, targetFilamentCount), particleCount / 2)
        eventStrength = max(0, eventStrength - deltaTime / 1.15)
        let event = SIMD4<Float>(eventStrength, eventKind, currentExecuteStyle, 0)
        parameterLock.unlock()

        smooth(current: &current, toward: target, deltaTime: deltaTime)
        smoothStyle(toward: style, deltaTime: deltaTime)
        let filamentCount = min(particleCount / 2,
                                Int(Float(baseFilamentCount) * (0.18 + current.complexity * 0.82)))
        let viewportHeight = max(1, Float(view.drawableSize.height))
        let aspect = Float(view.drawableSize.width / max(1, view.drawableSize.height))
        let uniforms = EntityUniforms(
            motion: SIMD4(current.energy, current.coherence, current.complexity, current.focus),
            response: SIMD4(current.arousal, current.expansion, current.audioLevel, elapsed),
            attention: SIMD4(current.attentionX, current.attentionY, aspect, viewportHeight),
            style: currentStyle,
            event: event
        )

        encoder.setVertexBuffer(particleBuffer, offset: 0, index: 0)
        encoder.setVertexBytes([uniforms], length: MemoryLayout<EntityUniforms>.stride, index: 1)
        encoder.setFragmentBytes([uniforms], length: MemoryLayout<EntityUniforms>.stride, index: 1)

        encoder.setRenderPipelineState(filamentPipeline)
        encoder.setVertexBuffer(linkBuffer, offset: 0, index: 2)
        if filamentCount > 0 { encoder.drawPrimitives(type: .line, vertexStart: 0, vertexCount: 2, instanceCount: filamentCount) }

        let ambientPhotonCount = max(180, particleCount * 2 / 5)
        let corePhotonCount = max(600, particleCount * 3 / 5)
        encoder.setRenderPipelineState(particlePipeline)
        encoder.drawPrimitives(type: .triangleStrip, vertexStart: 0, vertexCount: 4, instanceCount: ambientPhotonCount)

        encoder.setRenderPipelineState(corePhotonPipeline)
        encoder.drawPrimitives(type: .triangleStrip, vertexStart: 0, vertexCount: 4, instanceCount: corePhotonCount)

        encoder.endEncoding()
        commandBuffer.present(drawable)
        commandBuffer.commit()

        statisticsFrames += 1
        let statisticsDelta = now - statisticsStart
        if statisticsDelta >= 0.5 {
            let fps = Int((Double(statisticsFrames) / statisticsDelta).rounded())
            statisticsFrames = 0
            statisticsStart = now
            let resolution = view.drawableSize
            onStatistics?(fps, resolution, ambientPhotonCount + corePhotonCount)
        }
    }

    private func smooth(current: inout EntityVisualParameters, toward target: EntityVisualParameters, deltaTime dt: Float) {
        func approach(_ value: inout Float, _ goal: Float, _ tau: Float) {
            let factor = 1 - exp(-dt / max(0.001, tau))
            value += (goal - value) * factor
        }
        approach(&current.energy, target.energy, 0.34)
        approach(&current.coherence, target.coherence, 0.72)
        approach(&current.complexity, target.complexity, 0.56)
        approach(&current.focus, target.focus, 0.28)
        approach(&current.arousal, target.arousal, 0.22)
        approach(&current.expansion, target.expansion, 0.82)
        let gatedAudio = target.audioLevel < 0.025 ? 0 : target.audioLevel
        approach(&current.audioLevel, gatedAudio, target.audioLevel > current.audioLevel ? 0.055 : 0.24)
        approach(&current.attentionX, target.attentionX, 0.40)
        approach(&current.attentionY, target.attentionY, 0.40)
    }

    private func smoothStyle(toward style: EntityVisualStyle, deltaTime dt: Float) {
        let tau: Float = 0.48
        let factor = 1 - exp(-dt / tau)
        let targetIndex = style.rawValue
        for index in 0..<4 {
            let goal: Float = targetIndex == index ? 1 : 0
            currentStyle[index] += (goal - currentStyle[index]) * factor
        }
        let executeGoal: Float = targetIndex == 4 ? 1 : 0
        currentExecuteStyle += (executeGoal - currentExecuteStyle) * factor
    }

    private static func makeParticleSeeds(count: Int) -> [SIMD4<Float>] {
        var random = StableRandom(seed: 0x4D414C544F5345)
        return (0..<count).map { _ in
            let z = random.nextFloat(in: -1...1)
            let angle = random.nextFloat(in: 0...(2 * .pi))
            let radius = sqrt(max(0, 1 - z * z))
            let speed = random.nextFloat(in: 0.55...1.45)
            return SIMD4(radius * cos(angle), radius * sin(angle), z, speed)
        }
    }

    private static func makeLinks(from seeds: [SIMD4<Float>], count: Int) -> [SIMD4<UInt32>] {
        guard !seeds.isEmpty else { return [] }
        return (0..<count).map { index in
            let a = index % seeds.count
            var best = (a + 1 + (index * 7 % 13)) % seeds.count
            var bestDistance = Float.greatestFiniteMagnitude
            for offset in 1...20 {
                let b = (a + offset + 1) % seeds.count
                let delta = SIMD3(seeds[a].x - seeds[b].x, seeds[a].y - seeds[b].y, seeds[a].z - seeds[b].z)
                let distance = simd_length_squared(delta)
                if distance < bestDistance { best = b; bestDistance = distance }
            }
            return SIMD4(UInt32(a), UInt32(best), 0, 0)
        }
    }

    private struct StableRandom {
        private var state: UInt64
        init(seed: UInt64) { state = seed }
        mutating func nextFloat(in range: ClosedRange<Float>) -> Float {
            state = 2862933555777941757 &* state &+ 3037000493
            let normalized = Float((state >> 40) & 0xFFFFFF) / Float(0xFFFFFF)
            return range.lowerBound + (range.upperBound - range.lowerBound) * normalized
        }
    }

    private static let shaderSource = #"""
    #include <metal_stdlib>
    using namespace metal;

    struct Uniforms {
        float4 motion;     // energy, coherence, complexity, focus
        float4 response;   // arousal, expansion, audio, elapsed
        float4 attention;  // x, y, aspect, drawable height
        float4 style;      // idle, listening, thinking, speaking; executing is event.z
        float4 event;      // strength, kind, unused, unused
    };

    struct Varying {
        float4 position [[position]];
        float2 uv;
        float4 color;
    };

    float3 entityPosition(uint index, device const float4 *seeds, constant Uniforms& u) {
        float4 seed = seeds[index];
        float energy = u.motion.x;
        float coherence = u.motion.y;
        float complexity = u.motion.z;
        float time = u.response.w;
        float phase = time * (0.11 + energy * 0.16) * seed.w;
        float c = cos(phase);
        float s = sin(phase);
        float3 point = float3(seed.x * c - seed.y * s, seed.x * s + seed.y * c, seed.z);
        float idle = u.style.x;
        float listening = u.style.y;
        float thinking = u.style.z;
        float speaking = u.style.w;
        float executing = u.event.z;
        float turbulence = (0.006 + complexity * 0.032 + (1.0 - coherence) * 0.062) * (0.35 + energy * 0.65);
        turbulence *= 0.35 + thinking * 2.1 + executing * 0.65 + speaking * 0.40;
        float3 flow = float3(
            sin(time * 0.47 + seed.y * 8.1 + seed.z * 3.7),
            cos(time * 0.39 + seed.x * 7.3 - seed.z * 4.2),
            sin(time * 0.31 + seed.x * 5.4 + seed.y * 6.8)
        );
        point = normalize(point + flow * turbulence);
        float localBreath = sin(time * (0.65 + u.response.x * 0.65) + seed.w * 4.0 + seed.z * 2.7);
        float listeningWave = sin(time * 3.0 - (seed.x + seed.y) * 7.5 + seed.z * 2.0);
        float speechWave = sin(time * 8.0 + seed.w * 11.0 + seed.z * 3.0);
        float executionWave = sin(time * (2.2 + energy * 2.4) + seed.x * 12.0 - seed.y * 8.0);
        float radius = 0.23 + u.response.y * 0.22 + localBreath * (0.008 + u.motion.x * 0.013);
        radius += listening * listeningWave * 0.070;
        radius += speaking * speechWave * (0.035 + u.response.z * 0.055);
        radius += executing * executionWave * 0.035;
        radius += thinking * sin(time * 1.7 + seed.x * 16.0 + seed.y * 9.0) * 0.048;
        radius += u.event.x * (u.event.y > 0.0 ? 0.045 : -0.016);
        float3 position = point * radius;
        float focusBias = u.motion.w * 0.065;
        position.xy += u.attention.xy * focusBias;
        position += flow * (u.response.z * 0.018 + u.motion.x * 0.009) * (0.45 + thinking * 1.5 + executing * 0.35);
        position.xy += float2(-position.y, position.x) * executionWave * executing * 0.24;
        position.xy += float2(position.x, position.y) * listeningWave * listening * 0.12;
        position += flow * thinking * 0.026;
        return position;
    }

    float2 quadCorner(uint id) {
        switch (id % 4) {
            case 0: return float2(-1.0, -1.0);
            case 1: return float2( 1.0, -1.0);
            case 2: return float2(-1.0,  1.0);
            default: return float2( 1.0,  1.0);
        }
    }

    float3 particleColor(float seed, float depth, float energy, constant Uniforms& u) {
        float3 cyan = float3(0.23, 0.88, 1.0);
        float3 azure = float3(0.20, 0.48, 1.0);
        float3 violet = float3(0.62, 0.48, 1.0);
        float3 color = mix(cyan, azure, smoothstep(0.16, 0.76, seed));
        color = mix(color, violet, smoothstep(0.77, 0.99, seed) * 0.58);
        color = mix(color, float3(0.24, 0.88, 1.0), u.style.y * 0.38);
        color = mix(color, float3(0.75, 0.43, 1.0), u.style.z * 0.78);
        color = mix(color, float3(0.27, 0.66, 1.0), u.style.w * 0.50);
        color = mix(color, float3(0.22, 0.96, 0.88), u.event.z * 0.62);
        return color * (0.62 + depth * 0.28 + energy * 0.20);
    }

    vertex Varying particleVertex(uint vertexID [[vertex_id]], uint instanceID [[instance_id]],
                                  device const float4 *seeds [[buffer(0)]], constant Uniforms& u [[buffer(1)]]) {
        Varying out;
        float4 seed = seeds[instanceID];
        float3 p = entityPosition(instanceID, seeds, u);
        float2 corner = quadCorner(vertexID);
        float depth = clamp((p.z + 0.55) / 1.1, 0.0, 1.0);
        float listeningScan = exp(-pow((length(p) - (0.34 + sin(u.response.w * 1.8) * 0.13)) / 0.038, 2.0)) * u.style.y;
        float speechPulse = max(0.0, sin(u.response.w * 8.0 + length(p) * 38.0)) * u.style.w * u.response.z;
        float particleSize = (1.2 + u.motion.x * 1.9 + u.response.z * 1.2 + listeningScan * 3.0) * (0.58 + depth * 0.60) * (0.65 + seed.w * 0.35);
        float2 offset = float2(corner.x / max(u.attention.z, 0.1), corner.y) * (particleSize * 2.0 / max(u.attention.w, 1.0));
        out.position = float4(float2(p.x / max(u.attention.z, 0.1), p.y) + offset, 0.42 + depth * 0.12, 1.0);
        out.uv = corner;
        float3 color = particleColor(fract(seed.w * 0.71 + seed.x * 0.31 + 0.5), depth, u.motion.x, u);
        color = mix(color, float3(0.36, 0.98, 1.0), listeningScan * 0.86);
        color = mix(color, float3(0.70, 0.84, 1.0), speechPulse * 0.58);
        float alpha = (0.16 + u.motion.x * 0.22 + u.response.z * 0.18) * (0.40 + depth * 0.6);
        alpha = min(0.95, alpha + listeningScan * 0.78 + speechPulse * 0.34);
        out.color = float4(color, alpha);
        return out;
    }

    fragment float4 particleFragment(Varying in [[stage_in]]) {
        float r = length(in.uv);
        float alpha = (1.0 - smoothstep(0.10, 1.0, r)) * in.color.a;
        return float4(in.color.rgb, alpha);
    }

    vertex Varying filamentVertex(uint vertexID [[vertex_id]], uint instanceID [[instance_id]],
                                  device const float4 *seeds [[buffer(0)]], constant Uniforms& u [[buffer(1)]],
                                  device const uint4 *links [[buffer(2)]]) {
        Varying out;
        uint4 link = links[instanceID];
        uint particleID = vertexID == 0 ? link.x : link.y;
        float3 p = entityPosition(particleID, seeds, u);
        float styleTempo = u.style.y * 2.6 + u.style.z * 1.3 + u.style.w * 3.4 + u.event.z * 2.4;
        float pulse = 0.5 + 0.5 * sin(u.response.w * (1.1 + u.motion.x * 2.0 + styleTempo) + float(instanceID) * 0.17);
        out.position = float4(p.x / max(u.attention.z, 0.1), p.y, 0.5, 1.0);
        out.uv = float2(float(vertexID), pulse);
        float3 filament = mix(float3(0.16, 0.65, 0.98), float3(0.55, 0.40, 0.95), float(instanceID % 7) / 7.0);
        float alpha = (0.025 + u.motion.z * 0.10 + pulse * u.motion.x * 0.10) * (0.45 + u.motion.y * 0.55);
        alpha *= 0.5 + u.style.z * 1.15 + u.event.z * 0.65 + u.style.y * (0.6 + pulse * 0.8);
        alpha += u.event.x * (u.event.y > 0.0 ? 0.20 : 0.06);
        out.color = float4(filament, alpha);
        return out;
    }

    fragment float4 filamentFragment(Varying in [[stage_in]]) {
        return in.color;
    }

    vertex Varying corePhotonVertex(uint vertexID [[vertex_id]], uint instanceID [[instance_id]],
                                    device const float4 *seeds [[buffer(0)]], constant Uniforms& u [[buffer(1)]]) {
        Varying out;
        float2 corner = quadCorner(vertexID);
        float4 seed = seeds[instanceID];
        float randomRadius = fract(sin(dot(seed.xyz + float3(float(instanceID) * 0.013, 1.7, 3.1), float3(127.1, 311.7, 74.7))) * 43758.5453);
        float radius = (0.008 + pow(randomRadius, 0.72) * (0.078 + u.response.y * 0.048));
        float angle = seed.w * 6.2831853 + u.response.w * (0.22 + u.motion.x * 0.38) * (0.45 + randomRadius);
        float3 flow = float3(
            sin(u.response.w * 1.2 + seed.y * 10.0 + seed.z * 6.0),
            cos(u.response.w * 0.9 + seed.x * 8.0 - seed.z * 7.0),
            sin(u.response.w * 0.7 + seed.x * 5.0 + seed.y * 4.0)
        );
        float3 point = float3(cos(angle) * seed.x - sin(angle) * seed.y,
                              sin(angle) * seed.x + cos(angle) * seed.y,
                              seed.z);
        point = normalize(point + flow * (0.18 + u.style.z * 0.45 + u.event.z * 0.22));
        float wave = sin(u.response.w * (2.4 + u.style.y * 2.2 + u.style.w * 3.8 + u.event.z * 2.8)
                         + randomRadius * 19.0 + seed.z * 5.0);
        radius *= 0.84 + 0.16 * wave;
        radius += u.style.w * u.response.z * wave * 0.10;
        radius += u.style.y * sin(u.response.w * 3.0 + randomRadius * 18.0) * 0.035;
        radius += u.style.z * sin(u.response.w * 4.0 + seed.x * 18.0) * 0.022;
        radius += u.event.z * sin(u.response.w * 5.0 + seed.y * 16.0) * 0.030;
        radius += u.event.x * (u.event.y > 0.0 ? 0.035 : -0.012);
        float3 position = point * radius;
        position.xy += u.attention.xy * u.motion.w * 0.035;
        position.xy += float2(-position.y, position.x) * u.event.z * wave * 0.32;
        float depth = clamp((position.z + 0.15) / 0.30, 0.0, 1.0);
        // Keep each core photon's size independent from state, audio, and event intensity.
        float particleSize = 1.55 * (0.58 + randomRadius * 0.60);
        float2 offset = float2(corner.x / max(u.attention.z, 0.1), corner.y)
                      * (particleSize * 2.0 / max(u.attention.w, 1.0));
        out.position = float4(float2(position.x / max(u.attention.z, 0.1), position.y) + offset, 0.79 + depth * 0.18, 1.0);
        out.uv = corner;
        float3 color = mix(float3(0.30, 0.91, 1.0), float3(0.50, 0.47, 1.0), randomRadius * 0.56);
        color = mix(color, float3(0.73, 0.40, 1.0), u.style.z * 0.78);
        color = mix(color, float3(0.20, 0.97, 0.91), u.event.z * 0.40);
        color = mix(color, float3(0.96, 1.0, 1.0), (1.0 - randomRadius) * 0.35);
        float brightness = (0.42 + randomRadius * 0.62 + u.motion.x * 0.24 + abs(wave) * 0.28);
        float alpha = (0.28 + randomRadius * 0.30 + u.motion.x * 0.20 + u.response.z * 0.18)
                    * (0.76 + u.style.y * 0.12 + u.style.w * 0.18 + u.event.x * 0.18);
        out.color = float4(color * brightness, alpha);
        return out;
    }

    fragment float4 corePhotonFragment(Varying in [[stage_in]]) {
        float distance = length(in.uv);
        float glow = exp(-distance * distance * 6.5);
        float photon = 1.0 - smoothstep(0.20, 0.98, distance);
        float alpha = max(photon * in.color.a, glow * in.color.a * 0.55);
        return float4(in.color.rgb, alpha);
    }
    """#
}
