import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        EngineManager.shared.startIfNeeded()
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Stop the engine cleanly; its parent-pid watchdog is the backstop.
        EngineManager.shared.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

@main
struct AutoLyricMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

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
            ContentView(engineManager: EngineManager.shared)
                .frame(minWidth: 520, minHeight: 640)
        }
        .windowResizability(.contentSize)
    }
}
