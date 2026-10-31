// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "MaltoseUIHost", platforms: [.macOS(.v14)],
    products: [.library(name: "MaltoseCore", targets: ["MaltoseCore"]), .executable(name: "MaltoseApp", targets: ["MaltoseApp"]), .executable(name: "MaltoseHost", targets: ["MaltoseHost"])],
    targets: [
        .systemLibrary(name: "CSQLite", path: "native/CSQLite", pkgConfig: "sqlite3"),
        .target(name: "MaltoseCore", dependencies: ["CSQLite"], path: "native", exclude: ["CSQLite"], resources: [.copy("Protocol/Schemas")]),
        .executableTarget(name: "MaltoseApp", dependencies: ["MaltoseCore"], path: "apps/macos/MaltoseApp", resources: [.copy("Resources")]),
        .executableTarget(name: "MaltoseHost", dependencies: ["MaltoseCore"], path: "apps/headless"),
        .testTarget(name: "MaltoseUITests", dependencies: ["MaltoseApp", "MaltoseCore"], path: "tests/e2e"),
        .testTarget(name: "MaltoseCoreTests", dependencies: ["MaltoseCore"], path: "tests/native")
    ])
