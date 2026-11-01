import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct GalleryImage: Identifiable {
    enum Source {
        case sample(Int)
        case remote(URL)
        case local(Data)
    }

    let id: String
    let title: String
    let source: Source

    var sampleAspectRatio: CGFloat {
        guard case .sample(let index) = source else { return 16.0 / 9.0 }
        return [1.60, 0.78, 1.0, 1.78, 1.32, 0.72][index % 6]
    }
}

@MainActor final class ImageGalleryModel: ObservableObject {
    @Published private(set) var images: [GalleryImage]
    @Published private(set) var selectedIndex = 0
    @Published private(set) var expandedIndex: Int?
    @Published private(set) var workspaceMode: WorkspaceMode = .grid
    @Published private(set) var zoomScale: CGFloat = 1
    @Published private(set) var panOffset = CGSize.zero
    @Published private var intrinsicAspectRatios: [String: CGFloat] = [:]

    private var zoomStart: CGFloat = 1
    private var panStart = CGSize.zero

    init(images: [GalleryImage] = GalleryImage.samples) {
        self.images = images
    }

    var selectedImage: GalleryImage? { images.indices.contains(selectedIndex) ? images[selectedIndex] : nil }
    var showsCarousel: Bool { workspaceMode != .grid }
    var previousIndex: Int? { selectedIndex > 0 ? selectedIndex - 1 : nil }
    var nextIndex: Int? { selectedIndex + 1 < images.count ? selectedIndex + 1 : nil }

    func aspectRatio(for image: GalleryImage) -> CGFloat {
        if case .sample = image.source { return image.sampleAspectRatio }
        return intrinsicAspectRatios[image.id] ?? image.sampleAspectRatio
    }

    func recordAspectRatio(_ ratio: CGFloat, for imageID: String) {
        guard ratio.isFinite, ratio > 0 else { return }
        intrinsicAspectRatios[imageID] = ratio
    }

    func configure(mode: WorkspaceMode) {
        workspaceMode = mode
        if mode == .grid { collapse() }
    }

    func selectImage(at index: Int) {
        guard images.indices.contains(index) else { return }
        selectedIndex = index
        resetZoom()
    }

    func move(by offset: Int) {
        selectImage(at: selectedIndex + offset)
    }

    func expandImage(at index: Int) {
        guard images.indices.contains(index) else { return }
        selectedIndex = index
        expandedIndex = index
        resetZoom()
    }

    func collapse() {
        expandedIndex = nil
        resetZoom()
    }

    @discardableResult func addRemoteImage(_ text: String) -> Bool {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else { return false }
        append(GalleryImage(id: UUID().uuidString,
                            title: url.lastPathComponent.isEmpty ? url.host ?? "URL 圖片" : url.lastPathComponent,
                            source: .remote(url)))
        return true
    }

    func addLocalImage(_ url: URL) { try? importLocalImage(url) }

    /// Shared file-loading path; Agent callers receive the error instead of silent failure.
    func importLocalImage(_ url: URL) throws {
        let hasScope = url.startAccessingSecurityScopedResource()
        defer { if hasScope { url.stopAccessingSecurityScopedResource() } }
        try importImageData(Data(contentsOf: url), title: url.lastPathComponent)
    }

    func importImageData(_ data: Data, title: String) throws {
        guard NSImage(data: data) != nil else {
            throw NSError(domain: "MaltoseImageGallery", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "無法辨識此圖片檔案。"])
        }
        append(GalleryImage(id: UUID().uuidString, title: title, source: .local(data)))
    }

    func beginMagnification() { zoomStart = zoomScale }
    func updateMagnification(_ factor: CGFloat) {
        zoomScale = min(6, max(1, zoomStart * factor))
        if zoomScale == 1 { panOffset = .zero }
    }
    func beginPan() { panStart = panOffset }
    func updatePan(_ translation: CGSize) {
        guard zoomScale > 1 else { return }
        panOffset = CGSize(width: panStart.width + translation.width,
                           height: panStart.height + translation.height)
    }
    func endPan(viewport: CGSize, content: CGSize) {
        let maxX = max(0, (content.width * zoomScale - viewport.width) / 2)
        let maxY = max(0, (content.height * zoomScale - viewport.height) / 2)
        panOffset = CGSize(width: min(maxX, max(-maxX, panOffset.width)),
                           height: min(maxY, max(-maxY, panOffset.height)))
    }

    func constrainPan(to viewport: CGSize) {
        guard let image = selectedImage else { return }
        let sourceAspect = aspectRatio(for: image)
        let viewportAspect = viewport.width / max(viewport.height, 1)
        let fittedSize = sourceAspect > viewportAspect
            ? CGSize(width: viewport.width, height: viewport.width / sourceAspect)
            : CGSize(width: viewport.height * sourceAspect, height: viewport.height)
        endPan(viewport: viewport, content: fittedSize)
    }

    private func append(_ image: GalleryImage) {
        images.append(image)
        selectImage(at: images.count - 1)
    }

    private func resetZoom() {
        zoomScale = 1
        panOffset = .zero
        zoomStart = 1
        panStart = .zero
    }
}

extension GalleryImage {
    static var samples: [GalleryImage] {
        let names = ["1.jpeg", "2.jpeg", "3.jpg", "4.jpeg", "5.jpg", "6.jpeg"]
        let bundled = names.enumerated().compactMap { index, name -> GalleryImage? in
            guard let url = Bundle.main.resourceURL?.appendingPathComponent("GallerySamples", isDirectory: true)
                .appendingPathComponent(name),
                  let data = try? Data(contentsOf: url) else { return nil }
            return GalleryImage(id: "sample-image-\(index + 1)", title: "範例圖片 \(index + 1)", source: .local(data))
        }
        guard bundled.count == names.count else {
            return (0..<6).map { index in
                GalleryImage(id: "sample-image-\(index + 1)", title: "範例圖片 \(index + 1)", source: .sample(index))
            }
        }
        return bundled
    }
}

struct ImageGalleryPanelView: View {
    @ObservedObject var model: ImageGalleryModel
    @State private var showingFilePicker = false
    @State private var showingURLSheet = false
    @State private var urlDraft = ""
    @State private var isPanning = false
    @State private var previewDragX: CGFloat = 0

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topTrailing) {
                if let expandedIndex = model.expandedIndex, model.images.indices.contains(expandedIndex) {
                    galleryImage(at: expandedIndex, expanded: true, size: geometry.size)
                        .frame(width: geometry.size.width, height: geometry.size.height)
                } else if model.showsCarousel {
                    carousel(size: geometry.size)
                } else if let image = model.selectedImage {
                    GalleryImageFrame(image: image, model: model, scale: 1, offset: .zero)
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .contentShape(Rectangle())
                        .onTapGesture(count: 2) { model.expandImage(at: model.selectedIndex) }
                }

                if model.showsCarousel && model.expandedIndex == nil {
                    HStack(spacing: 8) {
                        Button { showingURLSheet = true } label: {
                            Image(systemName: "link").frame(width: 30, height: 30)
                        }.help("加入 URL 圖片")
                        Button { showingFilePicker = true } label: {
                            Image(systemName: "plus").frame(width: 30, height: 30)
                        }.help("加入本機圖片")
                    }
                    .buttonStyle(GalleryControlStyle())
                    .padding(14)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.clear)
            .contentShape(Rectangle())
        }
        .background(Color.clear)
        .preferredColorScheme(.dark)
        .accessibilityIdentifier("image-gallery-panel")
        .fileImporter(isPresented: $showingFilePicker, allowedContentTypes: [.image], allowsMultipleSelection: true) { result in
            if case .success(let urls) = result { urls.forEach(model.addLocalImage) }
        }
        .sheet(isPresented: $showingURLSheet) {
            VStack(alignment: .leading, spacing: 16) {
                Text("加入網路圖片").font(.headline)
                TextField("https://…", text: $urlDraft).textFieldStyle(.roundedBorder)
                    .onSubmit(addURL)
                HStack {
                    Spacer()
                    Button("取消") { showingURLSheet = false }
                    Button("加入", action: addURL).keyboardShortcut(.defaultAction)
                }
            }
            .padding(22)
            .frame(width: 420)
        }
    }

    private func carousel(size: CGSize) -> some View {
        let mainWidth = min(size.width * 0.46, size.height * (16.0 / 9.0) * 0.82)
        let sideWidth = mainWidth * 0.36
        let gap = max(12, size.width * 0.012)
        let stride = (mainWidth + sideWidth) / 2 + gap
        return GeometryReader { geometry in
            ZStack {
                ForEach(model.images.indices, id: \.self) { index in
                    carouselCard(at: index,
                                 center: CGPoint(x: geometry.size.width / 2, y: geometry.size.height / 2),
                                 stride: stride,
                                 mainWidth: mainWidth,
                                 sideWidth: sideWidth)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(carouselDragGesture(stride: stride))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func carouselCard(at index: Int, center: CGPoint, stride: CGFloat,
                              mainWidth: CGFloat, sideWidth: CGFloat) -> some View {
        let relativePosition = CGFloat(index - model.selectedIndex) + previewDragX / stride
        let distance = abs(relativePosition)
        let sizeProgress = min(distance, 1)
        let width = mainWidth + (sideWidth - mainWidth) * sizeProgress
        let opacity = min(1, max(0, 1.6 - distance))
        let isAdjacent = abs(index - model.selectedIndex) == 1

        return galleryImage(at: index, expanded: false,
                            size: CGSize(width: width, height: width * 9 / 16))
            .contentShape(Rectangle())
            .opacity(opacity)
            .position(x: center.x + relativePosition * stride, y: center.y)
            .zIndex(2 - distance)
            .allowsHitTesting(distance < 1.15)
            .onTapGesture {
                guard isAdjacent else { return }
                withAnimation(.easeInOut(duration: 0.28)) { model.selectImage(at: index) }
            }
            .accessibilityLabel(index == model.selectedIndex ? model.images[index].title : (index < model.selectedIndex ? "上一張圖片" : "下一張圖片"))
    }

    private func carouselDragGesture(stride: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 8)
            .onChanged { value in
                guard model.showsCarousel, model.expandedIndex == nil,
                      model.images.count > 1,
                      abs(value.translation.width) > abs(value.translation.height) * 1.15 else { return }
                let minDrag = -CGFloat(model.images.count - 1 - model.selectedIndex) * stride
                let maxDrag = CGFloat(model.selectedIndex) * stride
                previewDragX = min(maxDrag, max(minDrag, value.translation.width))
            }
            .onEnded { value in
                guard model.showsCarousel, model.expandedIndex == nil,
                      abs(value.translation.width) > abs(value.translation.height) * 1.15 else {
                    withAnimation(.easeOut(duration: 0.18)) { previewDragX = 0 }
                    return
                }

                let requestedSteps = Int((-previewDragX / stride).rounded())
                let targetIndex = min(model.images.count - 1,
                                      max(0, model.selectedIndex + requestedSteps))
                withAnimation(.easeInOut(duration: 0.24)) {
                    model.selectImage(at: targetIndex)
                    previewDragX = 0
                }
            }
    }

    @ViewBuilder private func galleryImage(at index: Int, expanded: Bool, size: CGSize) -> some View {
        let image = model.images[index]
        let frame = GalleryImageFrame(image: image, model: model,
                                      scale: expanded ? model.zoomScale : 1,
                                      offset: expanded ? model.panOffset : .zero)
            .frame(width: size.width, height: size.height)
            .clipped()
            .onTapGesture(count: 2) {
                if expanded { model.collapse() } else { model.expandImage(at: index) }
            }
        if expanded {
            frame.gesture(magnificationGesture).simultaneousGesture(panGesture(in: size, image: image))
        } else {
            frame
        }
    }

    private var magnificationGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                if value.magnification == 1 { model.beginMagnification() }
                model.updateMagnification(value.magnification)
            }
    }

    private func panGesture(in size: CGSize, image: GalleryImage) -> some Gesture {
        DragGesture(minimumDistance: 3)
            .onChanged { value in
                if !isPanning { model.beginPan(); isPanning = true }
                model.updatePan(value.translation)
            }
            .onEnded { _ in
                isPanning = false
                model.constrainPan(to: size)
            }
    }

    private func addURL() {
        if model.addRemoteImage(urlDraft) {
            urlDraft = ""
            showingURLSheet = false
        }
    }
}

private struct GalleryImageFrame: View {
    let image: GalleryImage
    let model: ImageGalleryModel?
    let scale: CGFloat
    let offset: CGSize
    @State private var loadedImage: NSImage?
    @State private var failed = false
    @State private var isLoading = false

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                if case .sample(let index) = image.source {
                    GallerySampleArtwork(index: index)
                        .aspectRatio(image.sampleAspectRatio, contentMode: .fit)
                        .frame(maxWidth: geometry.size.width, maxHeight: geometry.size.height)
                        .scaleEffect(scale)
                        .offset(offset)
                } else if let loadedImage {
                    Image(nsImage: loadedImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .scaleEffect(scale)
                        .offset(offset)
                } else if failed {
                    VStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle").font(.title2)
                        Text("無法載入圖片").font(.caption)
                    }
                    .foregroundStyle(.white.opacity(0.62))
                } else if isLoading {
                    ProgressView().controlSize(.small).tint(.white.opacity(0.7))
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .clipped()
        }
        .task(id: image.id) { await loadImage() }
        .onChange(of: loadedImage?.size) { _, size in
            guard let size else { return }
            model?.recordAspectRatio(size.width / max(size.height, 1), for: image.id)
        }
    }

    @MainActor private func loadImage() async {
        switch image.source {
        case .sample:
            return
        case .local(let data):
            loadedImage = NSImage(data: data)
            failed = loadedImage == nil
        case .remote(let url):
            isLoading = true
            defer { isLoading = false }
            do {
                let (data, response) = try await URLSession.shared.data(from: url)
                guard (response as? HTTPURLResponse)?.statusCode ?? 200 < 400 else { failed = true; return }
                loadedImage = NSImage(data: data)
                failed = loadedImage == nil
            } catch {
                failed = true
            }
        }
    }
}

private struct GallerySampleArtwork: View {
    let index: Int

    private var colors: [Color] {
        [
            [Color(red: 0.10, green: 0.22, blue: 0.38), Color(red: 0.35, green: 0.66, blue: 0.72)],
            [Color(red: 0.35, green: 0.15, blue: 0.27), Color(red: 0.91, green: 0.48, blue: 0.35)],
            [Color(red: 0.12, green: 0.28, blue: 0.25), Color(red: 0.56, green: 0.70, blue: 0.46)],
            [Color(red: 0.10, green: 0.14, blue: 0.34), Color(red: 0.47, green: 0.42, blue: 0.78)],
            [Color(red: 0.34, green: 0.25, blue: 0.12), Color(red: 0.84, green: 0.67, blue: 0.38)],
            [Color(red: 0.11, green: 0.25, blue: 0.34), Color(red: 0.27, green: 0.63, blue: 0.69)]
        ][index % 6]
    }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack {
                LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing)
                Circle().fill(colors[1].opacity(0.8))
                    .frame(width: min(size.width, size.height) * 0.31)
                    .blur(radius: min(size.width, size.height) * 0.035)
                    .position(x: size.width * 0.72, y: size.height * 0.28)
                Path { path in
                    path.move(to: CGPoint(x: 0, y: size.height * 0.78))
                    path.addLine(to: CGPoint(x: size.width * 0.29, y: size.height * (0.30 + CGFloat(index % 3) * 0.08)))
                    path.addLine(to: CGPoint(x: size.width * 0.55, y: size.height * 0.81))
                    path.addLine(to: CGPoint(x: size.width * 0.78, y: size.height * 0.45))
                    path.addLine(to: CGPoint(x: size.width, y: size.height * 0.78))
                    path.addLine(to: CGPoint(x: size.width, y: size.height))
                    path.addLine(to: CGPoint(x: 0, y: size.height))
                    path.closeSubpath()
                }
                .fill(Color.black.opacity(0.34))
                VStack(alignment: .leading, spacing: 5) {
                    Spacer()
                    Text("MALTOSE · IMAGE STUDY")
                        .font(.system(size: max(8, size.width * 0.022), weight: .medium, design: .monospaced))
                        .tracking(1.8)
                    Text(String(format: "%02d", index + 1))
                        .font(.system(size: max(18, size.width * 0.085), weight: .light, design: .rounded))
                }
                .foregroundStyle(.white.opacity(0.82))
                .padding(size.width * 0.06)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            }
        }
    }
}

private struct GalleryControlStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(.white.opacity(configuration.isPressed ? 0.62 : 0.84))
            .background(.ultraThinMaterial, in: Circle())
            .overlay(Circle().stroke(.white.opacity(0.12), lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
    }
}
