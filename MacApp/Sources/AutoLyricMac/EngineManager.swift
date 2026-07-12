import Foundation

/// Pure retry policy for engine startup: allows a fixed number of launch
/// attempts (start + one restart), then reports permanent failure.
struct EngineStartPolicy {
    let maxAttempts: Int
    private(set) var attemptsMade = 0

    init(maxAttempts: Int = 2) {
        self.maxAttempts = maxAttempts
    }

    /// Returns true if another launch attempt is allowed, consuming one slot.
    mutating func beginAttempt() -> Bool {
        guard attemptsMade < maxAttempts else { return false }
        attemptsMade += 1
        return true
    }

    mutating func reset() {
        attemptsMade = 0
    }
}

/// Locates the repository layout (engine script, venv python, logs).
struct EngineEnvironment {
    let repoRoot: URL

    var engineScript: URL { repoRoot.appendingPathComponent("Engine/engine.py") }
    var venvPython: URL { repoRoot.appendingPathComponent("Engine/.venv/bin/python") }
    var engineLog: URL { repoRoot.appendingPathComponent("Logs/engine.log") }

    /// Repo root: env override, then derived from this source file's location,
    /// then upward search from the working directory.
    static func locate() -> EngineEnvironment? {
        let fm = FileManager.default
        if let override = ProcessInfo.processInfo.environment["AUTOLYRIC_ROOT"] {
            let url = URL(fileURLWithPath: override)
            if fm.fileExists(atPath: url.appendingPathComponent("Engine/engine.py").path) {
                return EngineEnvironment(repoRoot: url)
            }
        }
        // …/MacApp/Sources/AutoLyricMac/EngineManager.swift -> repo root is 4 levels up.
        let fromSource = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        if fm.fileExists(atPath: fromSource.appendingPathComponent("Engine/engine.py").path) {
            return EngineEnvironment(repoRoot: fromSource)
        }
        var dir = URL(fileURLWithPath: fm.currentDirectoryPath)
        for _ in 0..<6 {
            if fm.fileExists(atPath: dir.appendingPathComponent("Engine/engine.py").path) {
                return EngineEnvironment(repoRoot: dir)
            }
            dir.deleteLastPathComponent()
        }
        return nil
    }
}

/// Starts, supervises, and stops the local Python engine so the user never
/// needs a separate Terminal window.
@MainActor
final class EngineManager: ObservableObject {
    enum State: Equatable {
        case stopped
        case starting
        case running
        case failed(String)
    }

    static let shared = EngineManager()

    @Published private(set) var state: State = .stopped

    private let port = 8765
    private var process: Process?
    private var policy = EngineStartPolicy()
    private var startTask: Task<Void, Never>?

    var healthURL: URL { URL(string: "http://127.0.0.1:\(port)/health")! }

    func startIfNeeded() {
        guard startTask == nil, state != .running else { return }
        startTask = Task { [weak self] in
            await self?.startWithRetry()
            self?.startTask = nil
        }
    }

    private func startWithRetry() async {
        guard let env = EngineEnvironment.locate() else {
            state = .failed("Could not locate the repository root (Engine/engine.py).")
            AppLog.shared.append("Engine start failed: repository root not found.")
            return
        }
        guard FileManager.default.fileExists(atPath: env.venvPython.path) else {
            state = .failed("Python venv missing. Run: python3.12 -m venv Engine/.venv && Engine/.venv/bin/pip install -r Engine/requirements.txt")
            return
        }

        // If a previous engine instance is already healthy (e.g. relaunch), adopt it.
        if await probeHealth() {
            state = .running
            AppLog.shared.append("Adopted an already-running engine on 127.0.0.1:\(port).")
            return
        }

        policy.reset()
        while policy.beginAttempt() {
            state = .starting
            AppLog.shared.append("Starting engine (attempt \(policy.attemptsMade)/\(policy.maxAttempts))…")
            do {
                try launchProcess(env: env)
            } catch {
                AppLog.shared.append("Engine launch error: \(error.localizedDescription)")
                terminateProcess()
                continue
            }
            if await waitForHealth(timeout: 15) {
                state = .running
                AppLog.shared.append("Engine healthy on 127.0.0.1:\(port).")
                return
            }
            AppLog.shared.append("Engine did not become healthy in time; stopping it.")
            terminateProcess()
        }
        state = .failed("Engine failed to start after \(policy.maxAttempts) attempts. See Logs/engine.log.")
        AppLog.shared.append("Engine failed to start after \(policy.maxAttempts) attempts.")
    }

    private func launchProcess(env: EngineEnvironment) throws {
        let proc = Process()
        proc.executableURL = env.venvPython
        proc.arguments = [
            env.engineScript.path,
            "serve",
            "--port", String(port),
            "--parent-pid", String(ProcessInfo.processInfo.processIdentifier),
        ]
        proc.currentDirectoryURL = env.repoRoot

        FileManager.default.createFile(atPath: env.engineLog.path, contents: nil)
        if let log = try? FileHandle(forWritingTo: env.engineLog) {
            log.seekToEndOfFile()
            proc.standardOutput = log
            proc.standardError = log
        }

        proc.terminationHandler = { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.process === proc else { return }
                self.process = nil
                if self.state == .running {
                    self.state = .failed("Engine exited unexpectedly. See Logs/engine.log.")
                    AppLog.shared.append("Engine exited unexpectedly.")
                }
            }
        }

        try proc.run()
        process = proc
    }

    private func terminateProcess() {
        guard let proc = process else { return }
        proc.terminationHandler = nil
        if proc.isRunning {
            proc.terminate()
        }
        process = nil
    }

    /// Stop the engine cleanly (called on app exit).
    func stop() {
        startTask?.cancel()
        startTask = nil
        terminateProcess()
        state = .stopped
    }

    private func waitForHealth(timeout: TimeInterval) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if Task.isCancelled { return false }
            if await probeHealth() { return true }
            try? await Task.sleep(for: .milliseconds(400))
        }
        return false
    }

    private func probeHealth() async -> Bool {
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 1.0
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["status"] as? String == "ok" else {
            return false
        }
        return true
    }
}
