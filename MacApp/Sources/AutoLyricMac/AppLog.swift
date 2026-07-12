import Foundation

/// In-app activity log shown at the bottom of the main window.
@MainActor
final class AppLog: ObservableObject {
    static let shared = AppLog()

    @Published private(set) var lines: [String] = []

    func append(_ line: String) {
        let ts = Date().formatted(date: .omitted, time: .standard)
        lines.append("[\(ts)] \(line)")
        if lines.count > 300 {
            lines.removeFirst(lines.count - 300)
        }
    }
}
