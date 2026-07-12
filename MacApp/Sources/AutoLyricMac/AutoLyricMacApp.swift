import SwiftUI

@main
struct AutoLyricMacApp: App {
    init() {
        // Unbuffered stdout so status prints appear immediately when piped to a log.
        setvbuf(stdout, nil, _IONBF, 0)
        // Running as a SwiftPM executable (no .app bundle yet), so promote
        // the process to a regular GUI app so the window appears and gets focus.
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    var body: some Scene {
        WindowGroup("AutoLyricMac") {
            ContentView()
                .frame(minWidth: 480, minHeight: 420)
        }
        .windowResizability(.contentSize)
    }
}
