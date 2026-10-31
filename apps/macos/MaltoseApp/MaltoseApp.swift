import SwiftUI

@main struct MaltoseApp: App {
    @NSApplicationDelegateAdaptor(WorkspaceAppDelegate.self) var appDelegate
    var body: some Scene {
        Settings { EmptyView() }
            .commands {
                CommandGroup(replacing: .appSettings) {}
                CommandGroup(replacing: .newItem) {}
                CommandMenu("工作空間") {
                    Button("等大排列") { appDelegate.workspace?.showGrid() }
                        .keyboardShortcut("1", modifiers: .command)
                    Button("切換原生全螢幕") { appDelegate.workspace?.enterFullscreenForActiveWindow() }
                        .keyboardShortcut("f", modifiers: [.control, .command])
                    Button("顯示所有窗口") { appDelegate.workspace?.showWindows() }
                }
                CommandMenu("面板") {
                    Button("核心動畫測試…") { appDelegate.workspace?.showCoreAnimationTest() }
                        .keyboardShortcut("0", modifiers: [.command, .option])
                }
            }
    }
}

@MainActor final class WorkspaceAppDelegate: NSObject, NSApplicationDelegate {
    var workspace: WorkspaceWindowManager?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let previewCount = CommandLine.arguments.first(where: { $0.hasPrefix("--panel-count=") })
            .flatMap { Int($0.dropFirst("--panel-count=".count)) }
        let samples = previewCount.map(WorkspacePanel.previewSamples(count:)) ?? WorkspacePanel.samples
        workspace = WorkspaceWindowManager(catalog: samples, automaticallyFullscreen: !CommandLine.arguments.contains("--windowed"))
        workspace?.synchronize()
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        workspace?.showWindows()
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) { workspace?.stop() }
}
