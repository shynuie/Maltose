import AppKit
import XCTest
@testable import MaltoseApp

/// Launch the built product in a disposable UI-only App, so fullscreen has an
/// actual NSApplication.run lifecycle instead of a command-line XCTest process.
@MainActor enum WorkspaceApplicationFixture {
    struct Snapshot: Decodable {
        struct Window: Decodable {
            var screenID: String
            var nativeFullscreen: Bool
            var rootNativeFullscreen: Bool
            var opaque: Bool
        }
        var schemaVersion: Int
        var nonce: String
        var eligibleScreens: [String]
        var windows: [Window]
        var failures: [String]
        var transitioning: Bool
        var applicationRunning: Bool
        var diagnostics: [String]
    }

    static func nativeFullscreenSnapshot() async throws -> Snapshot {
        let testBundle = Bundle(for: WorkspaceNativeTests.self).bundleURL
        let binaryDirectory = testBundle.deletingLastPathComponent()
        let executable = binaryDirectory.appendingPathComponent("MaltoseApp")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw RuntimeLaunchError.unavailable("Build the product executable before the desktop fixture")
        }
        let nonce = UUID().uuidString
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-native-app-" + nonce)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = directory.appendingPathComponent("Maltose UI Fixture.app")
        let contents = app.appendingPathComponent("Contents"), binaries = contents.appendingPathComponent("MacOS")
        try FileManager.default.createDirectory(at: binaries, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: executable, to: binaries.appendingPathComponent("MaltoseApp"))
        let resources = binaryDirectory.appendingPathComponent("Maltose_MaltoseApp.bundle")
        if FileManager.default.fileExists(atPath: resources.path) {
            let copied = binaries.appendingPathComponent(resources.lastPathComponent)
            try FileManager.default.copyItem(at: resources, to: copied)
            let info: [String: Any] = ["CFBundleIdentifier": "local.maltose.test-resources", "CFBundleName": "Maltose_MaltoseApp", "CFBundlePackageType": "BNDL"]
            try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: copied.appendingPathComponent("Info.plist"))
            try sign(copied)
        }
        let bundleID = "local.maltose.fixture." + nonce.lowercased()
        let info: [String: Any] = ["CFBundleExecutable": "MaltoseApp", "CFBundleIdentifier": bundleID,
            "CFBundleName": "Maltose UI Fixture", "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "LSMinimumSystemVersion": "14.0"]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: contents.appendingPathComponent("Info.plist"))
        try sign(app)
        let output = directory.appendingPathComponent("snapshot.json")
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.createsNewApplicationInstance = true; configuration.activates = true
        configuration.arguments = ["--ui-only", "--workspace-test-snapshot=" + output.path, "--workspace-test-nonce=" + nonce]
        configuration.environment = ["MALTOSE_DATA_DIR": directory.appendingPathComponent("unused-data").path]
        let application = try await NSWorkspace.shared.openApplication(at: app, configuration: configuration)
        defer {
            if !application.isTerminated { application.forceTerminate() }
        }
        let deadline = Date().addingTimeInterval(35)
        var snapshot: Snapshot?
        while Date() < deadline {
            if let data = try? Data(contentsOf: output), let value = try? JSONDecoder().decode(Snapshot.self, from: data), value.nonce == nonce {
                snapshot = value; break
            }
            if application.isTerminated { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        let value = try XCTUnwrap(snapshot, "UI-only product did not produce the scoped native snapshot")
        XCTAssertEqual(value.schemaVersion, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent("unused-data").path), "UI-only fixture must not initialize Agent data")
        let shutdown = Date().addingTimeInterval(5)
        while !application.isTerminated, Date() < shutdown { try await Task.sleep(for: .milliseconds(50)) }
        XCTAssertTrue(application.isTerminated, "UI-only fixture must exit without leaving an App instance")
        return value
    }

    private static func sign(_ url: URL) throws {
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        process.arguments = ["--force", "--sign", "-", url.path]
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        try process.run(); process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw RuntimeLaunchError.unavailable("Cannot sign isolated desktop fixture") }
    }
}
