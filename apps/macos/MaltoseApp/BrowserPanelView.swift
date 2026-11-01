import AppKit
import SwiftUI
import WebKit

@MainActor final class BrowserPanelModel: ObservableObject {
    @Published var addressDraft = ""
    @Published private(set) var currentURL: URL?
    @Published private(set) var pageTitle = "網頁"
    @Published private(set) var previewImage: NSImage?
    @Published private(set) var isLoading = false
    @Published private(set) var canGoBack = false
    @Published private(set) var canGoForward = false
    @Published private(set) var isPreview = true
    @Published private(set) var loadMessage: String?

    private weak var webView: WKWebView?
    private var pendingTestPage = false
    private var isTestPage = false

    init(initialAddress: String? = nil) {
        guard let initialAddress, let url = Self.destination(for: initialAddress) else { return }
        addressDraft = url.absoluteString
        currentURL = url
        pageTitle = url.host ?? "網頁"
    }

    func configure(preview: Bool) {
        guard preview != isPreview else { return }
        isPreview = preview
        guard preview, let webView else { return }
        webView.takeSnapshot(with: nil) { [weak self, weak webView] image, _ in
            Task { @MainActor in
                guard let self else { return }
                if let image { self.previewImage = image }
                if let webView {
                    Task { @MainActor in
                        _ = try? await webView.evaluateJavaScript("document.querySelectorAll('video').forEach(video => video.pause())")
                        webView.stopLoading()
                    }
                }
            }
        }
    }

    func loadAddress() {
        guard let url = Self.destination(for: addressDraft) else {
            loadMessage = "請輸入有效的網址或搜尋內容"
            return
        }
        loadMessage = nil
        isTestPage = false
        currentURL = url
        addressDraft = url.absoluteString
        previewImage = nil
        if let webView { webView.load(URLRequest(url: url)) }
    }

    func goBack() { webView?.goBack() }
    func goForward() { webView?.goForward() }
    func reload() { webView?.reload() }
    func stopLoading() {
        webView?.stopLoading()
        isLoading = false
    }

    func reloadOrStop() {
        if isLoading {
            stopLoading()
        }
        else { webView?.reload() }
    }

    func attach(_ webView: WKWebView) {
        self.webView = webView
        if pendingTestPage {
            pendingTestPage = false
            loadTestPage(in: webView)
        } else if let currentURL, !isTestPage {
            webView.load(URLRequest(url: currentURL))
        }
    }

    func didStart(_ webView: WKWebView) {
        isLoading = true
        loadMessage = nil
        updateNavigationState(webView)
    }

    func didFinish(_ webView: WKWebView) {
        isLoading = false
        currentURL = webView.url ?? currentURL
        addressDraft = currentURL?.absoluteString ?? addressDraft
        pageTitle = webView.title?.isEmpty == false ? webView.title! : (currentURL?.host ?? "網頁")
        loadMessage = nil
        updateNavigationState(webView)
        capturePreview(from: webView)
    }

    func didFail(_ webView: WKWebView, message: String) {
        isLoading = false
        loadMessage = message
        updateNavigationState(webView)
        capturePreview(from: webView)
    }

    func simulateTestPage() {
        isTestPage = true
        addressDraft = "https://maltose.invalid/agent-test"
        currentURL = URL(string: addressDraft)
        pageTitle = "Maltose 網頁測試"
        previewImage = nil
        if let webView { loadTestPage(in: webView) }
        else { pendingTestPage = true }
    }

    func userViewDetails() async -> [String: UserViewValue] {
        var details: [String: UserViewValue] = [
            "pageTitle": .string(pageTitle),
            "url": currentURL.map { .string($0.absoluteString) } ?? .null,
            "isLoading": .boolean(isLoading),
            "isPreview": .boolean(isPreview),
            "hasBackHistory": .boolean(canGoBack),
            "hasForwardHistory": .boolean(canGoForward)
        ]
        guard let webView else { return details }
        let script = #"""
        (() => {
          const selectedText = window.getSelection()?.toString()?.trim() || "";
          const nodes = [...document.querySelectorAll("h1,h2,h3,p,li")];
          const visibleText = nodes.filter(node => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight
              && style.visibility !== "hidden" && style.display !== "none";
          }).map(node => node.innerText.trim()).filter(Boolean).join("\n").slice(0, 2400);
          const video = document.querySelector("video");
          const media = video ? { currentTime: video.currentTime, duration: video.duration, paused: video.paused } : null;
          return JSON.stringify({ selectedText, visibleText, scrollY: window.scrollY, viewportHeight: window.innerHeight, media });
        })()
        """#
        if let encoded = try? await webView.evaluateJavaScript(script) as? String,
           let data = encoded.data(using: .utf8),
           let context = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            details["selectedText"] = .string(context["selectedText"] as? String ?? "")
            details["visibleTextExcerpt"] = .string(context["visibleText"] as? String ?? "")
            details["scrollY"] = .number(context["scrollY"] as? Double ?? 0)
            details["viewportHeight"] = .number(context["viewportHeight"] as? Double ?? 0)
            if let media = context["media"] as? [String: Any] {
                details["media"] = .object([
                    "currentTime": .number(media["currentTime"] as? Double ?? 0),
                    "duration": .number(media["duration"] as? Double ?? 0),
                    "isPaused": .boolean(media["paused"] as? Bool ?? true)
                ])
            }
        }
        return details
    }

    static func destination(for input: String) -> URL? {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }

        if var components = URLComponents(string: text),
           let scheme = components.scheme?.lowercased() {
            guard ["http", "https"].contains(scheme), components.host != nil else { return nil }
            components.scheme = scheme
            return components.url
        }

        if !text.contains(where: \.isWhitespace), text.contains("."),
           let url = URL(string: "https://\(text)"), url.host != nil {
            return url
        }

        var search = URLComponents(string: "https://duckduckgo.com/")
        search?.queryItems = [URLQueryItem(name: "q", value: text)]
        return search?.url
    }

    private func updateNavigationState(_ webView: WKWebView) {
        canGoBack = webView.canGoBack
        canGoForward = webView.canGoForward
    }

    private func capturePreview(from webView: WKWebView) {
        webView.takeSnapshot(with: nil) { [weak self] image, _ in
            guard let image else { return }
            Task { @MainActor in self?.previewImage = image }
        }
    }

    private func loadTestPage(in webView: WKWebView) {
        isLoading = true
        webView.loadHTMLString("""
        <!doctype html><html><meta name="viewport" content="width=device-width,initial-scale=1">
        <body style="margin:0;background:#101820;color:#e8eef2;font:18px -apple-system;padding:8vw">
        <h1>Maltose 網頁測試</h1><p>這是一個離線測試頁面。</p>
        <a href="https://maltose.invalid/agent-test/next">測試頁面連結</a>
        </body></html>
        """, baseURL: URL(string: "https://maltose.invalid/agent-test"))
    }
}

struct BrowserPanelView: View {
    @ObservedObject var model: BrowserPanelModel

    var body: some View {
        Group {
            if model.isPreview {
                preview
            } else {
                VStack(spacing: 0) {
                    toolbar
                    BrowserWebView(model: model)
                    if let loadMessage = model.loadMessage {
                        Text(loadMessage)
                            .font(.system(size: 12))
                            .foregroundStyle(.white.opacity(0.68))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 14).padding(.vertical, 8)
                            .background(.black.opacity(0.28))
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.clear)
        .preferredColorScheme(.dark)
        .accessibilityIdentifier("browser-panel")
    }

    private var preview: some View {
        ZStack {
            if model.currentURL != nil, model.previewImage == nil {
                BrowserWebView(model: model)
                    .frame(width: 960, height: 540)
                    .opacity(0.001)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
            if let image = model.previewImage {
                Image(nsImage: image).resizable().scaledToFill().clipped()
                    .overlay(.black.opacity(0.24))
            } else {
                LinearGradient(colors: [Color(red: 0.08, green: 0.12, blue: 0.16), .black], startPoint: .topLeading, endPoint: .bottomTrailing)
            }
            VStack(spacing: 10) {
                Image(systemName: model.currentURL == nil ? "safari" : "doc.text.image")
                    .font(.system(size: 25, weight: .light))
                    .foregroundStyle(.cyan.opacity(0.88))
                Text(model.pageTitle).font(.system(size: 15, weight: .medium)).lineLimit(1)
                Text(model.currentURL?.host ?? "雙擊玻璃外框以瀏覽網頁")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.62)).lineLimit(1)
            }
            .padding(16)
            .foregroundStyle(.white.opacity(0.9))
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if model.isLoading {
                ProgressView().controlSize(.small).tint(.white).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing).padding(14)
            }
        }
        .clipped()
        .accessibilityLabel("網頁預覽：\(model.pageTitle)")
    }

    private var toolbar: some View {
        HStack(spacing: 8) {
            Button(action: model.goBack) { Image(systemName: "chevron.left") }
                .disabled(!model.canGoBack).help("返回")
            Button(action: model.goForward) { Image(systemName: "chevron.right") }
                .disabled(!model.canGoForward).help("前進")
            Button(action: model.reloadOrStop) {
                Image(systemName: model.isLoading ? "xmark" : "arrow.clockwise")
            }
            .help(model.isLoading ? "停止載入" : "重新載入")

            TextField("輸入網址或搜尋…", text: $model.addressDraft)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .padding(.horizontal, 11).padding(.vertical, 8)
                .background(.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 9))
                .onSubmit(model.loadAddress)
                .accessibilityLabel("網址或搜尋")

            Button(action: model.loadAddress) { Image(systemName: "arrow.right") }
                .help("前往")
        }
        .buttonStyle(BrowserToolbarButtonStyle())
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(.black.opacity(0.38))
    }
}

private struct BrowserWebView: NSViewRepresentable {
    @ObservedObject var model: BrowserPanelModel

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        model.attach(webView)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if webView.navigationDelegate !== context.coordinator {
            webView.navigationDelegate = context.coordinator
            webView.uiDelegate = context.coordinator
        }
    }

    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.takeSnapshot(with: nil) { [weak model = coordinator.model, weak webView] image, _ in
            Task { @MainActor in
                if let image { model?.storePreview(image) }
                webView?.stopLoading()
                webView?.navigationDelegate = nil
                webView?.uiDelegate = nil
            }
        }
    }

    @MainActor final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let model: BrowserPanelModel
        init(model: BrowserPanelModel) { self.model = model }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            model.didStart(webView)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            model.didFinish(webView)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            model.didFail(webView, message: "載入失敗：\(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            model.didFail(webView, message: "無法開啟此網頁：\(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url, let scheme = url.scheme?.lowercased() else {
                decisionHandler(.cancel)
                return
            }
            if ["http", "https", "about"].contains(scheme) {
                decisionHandler(.allow)
            } else if ["mailto", "tel"].contains(scheme) {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.cancel)
            }
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            guard navigationAction.targetFrame == nil,
                  let url = navigationAction.request.url,
                  ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return nil }
            webView.load(URLRequest(url: url))
            return nil
        }
    }
}

private struct BrowserToolbarButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(.white.opacity(configuration.isPressed ? 0.48 : 0.82))
            .frame(width: 30, height: 30)
            .contentShape(Rectangle())
    }
}

private extension BrowserPanelModel {
    func storePreview(_ image: NSImage) { previewImage = image }
}
