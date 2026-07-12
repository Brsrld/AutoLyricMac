import Foundation

/// Client-side YouTube URL validation, mirroring the engine's rules so the
/// UI can gate actions instantly without a round trip.
enum YouTubeURLValidator {
    /// Returns the 11-character video id for a well-formed YouTube URL, else nil.
    static func videoID(from string: String) -> String? {
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 2048,
              let components = URLComponents(string: trimmed),
              let scheme = components.scheme?.lowercased(),
              scheme == "http" || scheme == "https" else {
            return nil
        }
        var host = (components.host ?? "").lowercased()
        if host.hasPrefix("www.") { host.removeFirst(4) }

        var candidate: String?
        switch host {
        case "youtube.com", "m.youtube.com", "music.youtube.com":
            if components.path == "/watch" {
                candidate = components.queryItems?.first(where: { $0.name == "v" })?.value
            } else {
                let parts = components.path.split(separator: "/").map(String.init)
                if parts.count == 2, ["shorts", "embed", "live"].contains(parts[0]) {
                    candidate = parts[1]
                }
            }
        case "youtu.be":
            let parts = components.path.split(separator: "/").map(String.init)
            if parts.count == 1 { candidate = parts[0] }
        default:
            return nil
        }

        guard let id = candidate,
              id.count == 11,
              id.allSatisfy({ ($0.isASCII && ($0.isLetter || $0.isNumber)) || $0 == "-" || $0 == "_" }) else {
            return nil
        }
        return id
    }
}

/// Metadata returned by the engine's /inspect endpoint.
struct SourceMetadata: Decodable, Equatable {
    let valid: Bool
    let videoId: String?
    let title: String?
    let uploader: String?
    let duration: Double?
    let thumbnailUrl: String?
    let originalUrl: String?
}

/// Result payload of an analysis job (Phase 2).
struct AnalysisResult: Decodable, Equatable {
    let tempoBpm: Double
    let trackDuration: Double
    let beatCount: Int
    let sectionCount: Int
    let segmentStart: Double
    let segmentEnd: Double
    let score: Double
    let reasons: [String]
}

/// Status of an engine job (audio ingestion or analysis).
struct JobStatus: Decodable, Equatable {
    let jobId: String
    let kind: String?
    let state: String       // queued|downloading|converting|analyzing|verifying|done|error|cancelled
    let progress: Double
    let message: String
    let errorCode: String?
    let audioPath: String?
    let audioDuration: Double?
    let audioFormat: String?
    let result: AnalysisResult?

    var isTerminal: Bool { ["done", "error", "cancelled"].contains(state) }
}

/// A structured error surfaced by the engine.
struct EngineAPIError: Error, LocalizedError, Decodable {
    let errorCode: String?
    let message: String?

    var errorDescription: String? { message ?? "The engine reported an error." }
}

/// Talks to the local Python engine over 127.0.0.1 and polls its health.
@MainActor
final class EngineClient: ObservableObject {
    enum Status: Equatable {
        case unknown
        case connected
        case offline
    }

    @Published private(set) var status: Status = .unknown

    private let baseURL = URL(string: "http://127.0.0.1:8765")!
    private var pollTask: Task<Void, Never>?

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    // MARK: - Health polling

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
        var request = URLRequest(url: baseURL.appendingPathComponent("health"))
        request.timeoutInterval = 1.5

        let newStatus: Status
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse,
               http.statusCode == 200,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               json["status"] as? String == "ok" {
                newStatus = .connected
            } else {
                newStatus = .offline
            }
        } catch {
            newStatus = .offline
        }

        if newStatus != status {
            status = newStatus
        }
    }

    // MARK: - API calls

    /// Fetch metadata for a URL without downloading media.
    func inspect(url: String) async throws -> SourceMetadata {
        try await post(path: "inspect", body: ["url": url], timeout: 40)
    }

    /// Start an authorized audio-download job; returns the job id.
    func createJob(url: String, authorized: Bool) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["url": url, "authorized": authorized],
                                              timeout: 15)
        return created.jobId
    }

    /// Start an analysis + segment-selection job on an ingested job's audio.
    func createAnalyzeJob(sourceJobId: String, targetSeconds: Int,
                          startOverride: Double?) async throws -> String {
        struct Created: Decodable { let jobId: String }
        var body: [String: Any] = ["kind": "analyze",
                                   "source_job_id": sourceJobId,
                                   "target_seconds": targetSeconds]
        if let startOverride {
            body["start_override"] = startOverride
        }
        let created: Created = try await post(path: "jobs", body: body, timeout: 15)
        return created.jobId
    }

    func jobStatus(id: String) async throws -> JobStatus {
        var request = URLRequest(url: baseURL.appendingPathComponent("jobs/\(id)"))
        request.timeoutInterval = 5
        let (data, response) = try await URLSession.shared.data(for: request)
        return try Self.decode(data: data, response: response)
    }

    func cancelJob(id: String) async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent("jobs/\(id)/cancel"))
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        _ = try await URLSession.shared.data(for: request)
    }

    // MARK: - Plumbing

    private func post<T: Decodable>(path: String, body: [String: Any], timeout: TimeInterval) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        return try Self.decode(data: data, response: response)
    }

    private static func decode<T: Decodable>(data: Data, response: URLResponse) throws -> T {
        guard let http = response as? HTTPURLResponse else {
            throw EngineAPIError(errorCode: "network", message: "No response from engine.")
        }
        guard (200..<300).contains(http.statusCode) else {
            if let apiError = try? decoder.decode(EngineAPIError.self, from: data) {
                throw apiError
            }
            throw EngineAPIError(errorCode: "engine_error",
                                 message: "Engine returned HTTP \(http.statusCode).")
        }
        return try decoder.decode(T.self, from: data)
    }
}
