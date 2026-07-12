// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "AutoLyricMac",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "AutoLyricMac",
            path: "Sources/AutoLyricMac"
        ),
        .testTarget(
            name: "AutoLyricMacTests",
            dependencies: ["AutoLyricMac"],
            path: "Tests/AutoLyricMacTests"
        )
    ]
)
