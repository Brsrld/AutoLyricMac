import Foundation

/// Polls the local Python engine's health endpoint.
@MainActor
final class EngineClient: ObservableObject {
    enum Status: Equatable {
        case unknown
        case connected
        case offline
    }

    @Published private(set) var status: Status = .unknown

    private let healthURL = URL(string: "http://127.0.0.1:8765/health")!
    private var pollTask: Task<Void, Never>?

    func startPolling(interval: TimeInterval = 2.0) {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.checkHealth()
                try? await Task.sleep(for: .seconds(interval))
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func checkHealth() async {
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 1.5

        let newStatus: Status
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse,
               http.statusCode == 200,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
               json["status"] == "ok" {
                newStatus = .connected
            } else {
                newStatus = .offline
            }
        } catch {
            newStatus = .offline
        }

        if newStatus != status {
            status = newStatus
            // Mirror status to stdout so the launch terminal shows connectivity.
            print("[EngineClient] status -> \(newStatus)")
        }
    }
}
