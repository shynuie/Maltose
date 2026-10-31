// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "MaltoseWorkspace", platforms: [.macOS(.v14)],
    products: [.executable(name: "MaltoseApp", targets: ["MaltoseApp"])],
    targets: [
        .executableTarget(name: "MaltoseApp", path: "apps/macos/MaltoseApp", resources: [.process("Resources")]),
        .testTarget(name: "MaltoseUITests", dependencies: ["MaltoseApp"], path: "tests/e2e")
    ])
