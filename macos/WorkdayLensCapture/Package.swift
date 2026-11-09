// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "WorkdayLensCapture",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "WorkdayLensCapture", targets: ["WorkdayLensCapture"])
    ],
    targets: [
        .executableTarget(
            name: "WorkdayLensCapture"
        )
    ]
)
