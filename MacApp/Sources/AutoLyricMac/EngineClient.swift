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

/// Splits a YouTube title like "Artist - Song (Official Video)" into an
/// artist/title guess for lyric search; falls back to the uploader.
enum SongTitleParser {
    static func guess(title: String?, uploader: String?) -> (artist: String, title: String) {
        let raw = (title ?? "").trimmingCharacters(in: .whitespaces)
        let channel = (uploader ?? "")
            .replacingOccurrences(of: " - Topic", with: "")
            .trimmingCharacters(in: .whitespaces)
        for separator in [" - ", " – ", " — ", " | "] {
            if let range = raw.range(of: separator) {
                let artist = String(raw[..<range.lowerBound]).trimmingCharacters(in: .whitespaces)
                let song = String(raw[range.upperBound...]).trimmingCharacters(in: .whitespaces)
                if !artist.isEmpty && !song.isEmpty {
                    return (artist, song)
                }
            }
        }
        return (channel, raw)
    }
}

/// Result payload of a terminal job. Different job kinds fill different
/// fields, so everything is optional and decoding stays tolerant.
struct JobResult: Decodable, Equatable {
    // analyze (Phase 2)
    let tempoBpm: Double?
    let trackDuration: Double?
    let beatCount: Int?
    let sectionCount: Int?
    let segmentStart: Double?
    let segmentEnd: Double?
    let score: Double?
    let reasons: [String]?
    // lyrics (Phase 3)
    let lineCount: Int?
    let synced: Bool?
    // align (Phase 3)
    let matchedRatio: Double?
    let meanConfidence: Double?
    let uncertainLines: Int?
    let suspect: Bool?
    // subtitle preview (Phase 3)
    let outputPath: String?
    let qaFrames: [String]?
    let style: String?
    // scene plan (Phase 4)
    let sceneCount: Int?
    let lyricSceneCount: Int?
    let recommendedStyle: String?
    let recommendationReason: String?
    // media fetch (Phase 4)
    let fetchedCount: Int?
    let providerErrors: [String]?
    let sceneErrors: [String]?
    // publish (Phase 8)
    let videoUrl: String?
    // caption generation
    let title: String?
    let description: String?
    let hashtags: [String]?
}

/// Adaptation decision for one media asset (never stretch).
struct MediaAdaptation: Decodable, Equatable {
    let strategy: String
    let reason: String
}

/// The licensed asset chosen for a scene, with attribution.
struct SceneMediaPayload: Decodable, Equatable {
    let provider: String
    let providerRef: String?
    let kind: String?
    let width: Int?
    let height: Int?
    let pageUrl: String?
    let creator: String?
    let license: String?
    let filePath: String?
    let adaptation: MediaAdaptation?
}

/// One planned scene from the deterministic planner.
struct ScenePayload: Decodable, Equatable, Identifiable {
    let sceneIndex: Int
    let start: Double
    let end: Double
    let duration: Double
    let lyric: String?
    let translation: String?
    let emotion: String
    let energyBand: String
    let subjects: [String]
    let queries: [String]
    let mediaPreference: String
    let media: SceneMediaPayload?

    var id: Int { sceneIndex }
}

/// One rendered output recorded in history.
struct ProjectOutput: Decodable, Equatable {
    let filePath: String
    let style: String?
    let duration: Double?
    let createdAt: Double
}

/// One history entry from GET /projects (Phase 7).
struct ProjectPayload: Decodable, Equatable, Identifiable {
    let jobId: String
    let url: String?
    let videoId: String?
    let title: String?
    let uploader: String?
    let duration: Double?
    let audioPath: String?
    let style: String?
    let targetSeconds: Double?
    let segmentStart: Double?
    let createdAt: Double
    let updatedAt: Double
    let audioExists: Bool?
    let hasPlan: Bool?
    let outputs: [ProjectOutput]

    var id: String { jobId }
}

/// Stored scene plan from GET /plan/<job_id>.
struct PlanPayload: Decodable, Equatable {
    let style: String
    let recommendedStyle: String
    let recommendationConfidence: Double?
    let recommendationReason: String?
    let sceneCount: Int
    let lyricSceneCount: Int
    let scenes: [ScenePayload]
}

/// One word of a lyric line with aligned timing and confidence.
struct LyricWordPayload: Decodable, Equatable {
    let text: String
    let start: Double?
    let end: Double?
    let confidence: Double?
}

/// One canonical lyric line, including user corrections and translation.
struct LyricLinePayload: Decodable, Equatable, Identifiable {
    let lineIndex: Int
    let text: String
    let correctedText: String?
    let displayText: String
    let translation: String?
    let start: Double?
    let end: Double?
    let confidence: Double?
    let uncertain: Bool
    let words: [LyricWordPayload]

    var id: Int { lineIndex }
}

/// Full lyrics payload for a job from GET /lyrics/<job_id>.
struct LyricsPayload: Decodable, Equatable {
    let jobId: String
    let provider: String
    let artist: String?
    let title: String?
    let synced: Bool
    let aligned: Bool
    let matchedRatio: Double?
    let meanConfidence: Double?
    let suspect: Bool
    let lines: [LyricLinePayload]
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
    let result: JobResult?

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

    /// Start a lyrics search job for an ingested job's song.
    func createLyricsJob(sourceJobId: String, artist: String, title: String) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "lyrics",
                                                     "source_job_id": sourceJobId,
                                                     "artist": artist,
                                                     "title": title],
                                              timeout: 15)
        return created.jobId
    }

    /// Start a word-alignment job (local Whisper) for stored lyrics.
    func createAlignJob(sourceJobId: String) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "align",
                                                     "source_job_id": sourceJobId],
                                              timeout: 15)
        return created.jobId
    }

    /// On-demand Turkish translation of the stored lyrics (Claude, Argos
    /// fallback). `force` re-translates lines that already have a translation.
    func createTranslateJob(sourceJobId: String,
                            force: Bool = false) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "translate",
                                                     "source_job_id": sourceJobId,
                                                     "force": force],
                                              timeout: 15)
        return created.jobId
    }

    /// Generate a reach-optimized title/caption/hashtags for publishing.
    func createCaptionJob(sourceJobId: String,
                          theme: String = "") async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "caption",
                                                     "source_job_id": sourceJobId,
                                                     "theme": theme],
                                              timeout: 15)
        return created.jobId
    }

    /// Render a subtitle preview for a style over the selected segment.
    func createSubtitlePreviewJob(sourceJobId: String, style: String,
                                  segmentStart: Double, targetSeconds: Int) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "subtitle_preview",
                                                     "source_job_id": sourceJobId,
                                                     "style": style,
                                                     "segment_start": segmentStart,
                                                     "target_seconds": targetSeconds],
                                              timeout: 15)
        return created.jobId
    }

    /// Fetch stored lyrics (lines, timing, confidence) for an ingested job.
    func fetchLyrics(sourceJobId: String) async throws -> LyricsPayload {
        var request = URLRequest(url: baseURL.appendingPathComponent("lyrics/\(sourceJobId)"))
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        return try Self.decode(data: data, response: response)
    }

    /// Store manually pasted lyrics for a job (when providers find none).
    func setManualLyrics(sourceJobId: String, text: String, artist: String,
                         title: String) async throws -> LyricsPayload {
        try await post(path: "lyrics/\(sourceJobId)/manual",
                       body: ["text": text, "artist": artist, "title": title],
                       timeout: 15)
    }

    /// Paste-in-order Turkish translations: i-th line -> i-th lyric line.
    func setManualTranslations(sourceJobId: String, text: String) async throws -> Int {
        struct Response: Decodable { let applied: Int; let lineCount: Int }
        let response: Response = try await post(
            path: "lyrics/\(sourceJobId)/translations",
            body: ["text": text], timeout: 15)
        return response.applied
    }

    /// Persist a user correction and/or Turkish translation for one line.
    /// Pass an empty string to clear; nil leaves the field unchanged.
    func updateLyricLine(sourceJobId: String, lineIndex: Int,
                         correctedText: String?, translation: String?) async throws -> LyricLinePayload {
        var body: [String: Any] = ["line_index": lineIndex]
        if let correctedText { body["corrected_text"] = correctedText }
        if let translation { body["translation"] = translation }
        return try await post(path: "lyrics/\(sourceJobId)/line", body: body, timeout: 10)
    }

    /// Build a scene plan from aligned lyrics + audio analysis.
    func createPlanJob(sourceJobId: String, style: String,
                       segmentStart: Double, targetSeconds: Int,
                       theme: String = "",
                       artStyle: String = "storybook",
                       instrumental: Bool = false) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "plan",
                                                     "source_job_id": sourceJobId,
                                                     "style": style,
                                                     "segment_start": segmentStart,
                                                     "target_seconds": targetSeconds,
                                                     "theme": theme,
                                                     "art_style": artStyle,
                                                     "instrumental": instrumental],
                                              timeout: 15)
        return created.jobId
    }

    /// Fetch licensed stock media for a stored plan. Keys go over loopback
    /// only and are never persisted by the engine. `regenerate` refetches
    /// every scene; `exclude` bans specific assets for this project.
    func createMediaJob(sourceJobId: String, apiKeys: [String: String],
                        regenerate: Bool = false,
                        artStyle: String? = nil,
                        aiImages: Bool = false,
                        exclude: [(provider: String, ref: String)] = []) async throws -> String {
        struct Created: Decodable { let jobId: String }
        var body: [String: Any] = ["kind": "media",
                                   "source_job_id": sourceJobId,
                                   "api_keys": apiKeys,
                                   "ai_images": aiImages]
        if let artStyle { body["art_style"] = artStyle }
        if regenerate { body["regenerate"] = true }
        if !exclude.isEmpty {
            body["exclude"] = exclude.map {
                ["provider": $0.provider, "provider_ref": $0.ref]
            }
        }
        let created: Created = try await post(path: "jobs", body: body,
                                              timeout: 15)
        return created.jobId
    }

    /// History of all projects (survives relaunch).
    func listProjects() async throws -> [ProjectPayload] {
        struct Response: Decodable { let projects: [ProjectPayload] }
        var request = URLRequest(url: baseURL.appendingPathComponent("projects"))
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        let decoded: Response = try Self.decode(data: data, response: response)
        return decoded.projects
    }

    /// Remove a project from history (optionally with its cached files;
    /// rendered videos in Output/videos are never deleted).
    func deleteProject(jobId: String, deleteFiles: Bool) async throws {
        struct Deleted: Decodable { let deleted: Bool }
        let _: Deleted = try await post(path: "projects/\(jobId)/delete",
                                        body: ["delete_files": deleteFiles],
                                        timeout: 15)
    }

    /// Safe cache cleanup: orphaned job/media dirs + old subtitle previews.
    func runCleanup() async throws -> (removed: Int, freedBytes: Int) {
        struct Result: Decodable { let removed: Int; let freedBytes: Int }
        let result: Result = try await post(path: "cleanup", body: [:],
                                            timeout: 60)
        return (result.removed, result.freedBytes)
    }

    /// Render the final styled video from the media-annotated plan.
    func createRenderJob(sourceJobId: String, style: String,
                         motionEffects: Bool = false,
                         syncOffset: Double = 0.0) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "render",
                                                     "source_job_id": sourceJobId,
                                                     "style": style,
                                                     "motion_effects": motionEffects,
                                                     "sync_offset": syncOffset],
                                              timeout: 15)
        return created.jobId
    }

    /// Fetch the stored scene plan (with media annotations when fetched).
    func fetchPlan(sourceJobId: String) async throws -> PlanPayload {
        var request = URLRequest(url: baseURL.appendingPathComponent("plan/\(sourceJobId)"))
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        return try Self.decode(data: data, response: response)
    }

    /// Begin the official YouTube OAuth flow; returns the URL to open in
    /// the browser and a state token for polling.
    func youtubeConnect(clientId: String, clientSecret: String) async throws -> (authURL: String, state: String) {
        struct Response: Decodable { let authUrl: String; let state: String }
        let response: Response = try await post(path: "youtube/connect",
                                                body: ["client_id": clientId,
                                                       "client_secret": clientSecret],
                                                timeout: 15)
        return (response.authUrl, response.state)
    }

    struct YouTubeStatus: Decodable {
        struct Flow: Decodable { let status: String; let message: String }
        let connected: Bool
        let flow: Flow?
    }

    func youtubeStatus(state: String? = nil) async throws -> YouTubeStatus {
        var components = URLComponents(url: baseURL.appendingPathComponent("youtube/status"),
                                       resolvingAgainstBaseURL: false)!
        if let state { components.queryItems = [.init(name: "state", value: state)] }
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        return try Self.decode(data: data, response: response)
    }

    func youtubeDisconnect() async throws {
        struct Response: Decodable { let connected: Bool }
        let _: Response = try await post(path: "youtube/disconnect", body: [:],
                                         timeout: 10)
    }

    /// Publish a rendered output to YouTube (official Data API).
    func createPublishJob(sourceJobId: String, outputPath: String,
                          title: String, description: String,
                          privacy: String, tags: [String] = []) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "publish_youtube",
                                                     "source_job_id": sourceJobId,
                                                     "output_path": outputPath,
                                                     "title": title,
                                                     "description": description,
                                                     "privacy": privacy,
                                                     "tags": tags],
                                              timeout: 15)
        return created.jobId
    }

    /// Connect Instagram: token + professional account id + temp storage.
    func instagramConnect(accessToken: String, igUserId: String,
                          s3: [String: String]) async throws -> String {
        struct Response: Decodable { let connected: Bool; let username: String }
        let response: Response = try await post(path: "instagram/connect",
                                                body: ["access_token": accessToken,
                                                       "ig_user_id": igUserId,
                                                       "s3": s3],
                                                timeout: 30)
        return response.username
    }

    func instagramStatus() async throws -> Bool {
        struct Response: Decodable { let connected: Bool }
        var request = URLRequest(url: baseURL.appendingPathComponent("instagram/status"))
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        let decoded: Response = try Self.decode(data: data, response: response)
        return decoded.connected
    }

    func instagramDisconnect() async throws {
        struct Response: Decodable { let connected: Bool }
        let _: Response = try await post(path: "instagram/disconnect",
                                         body: [:], timeout: 10)
    }

    func createInstagramPublishJob(sourceJobId: String, outputPath: String,
                                   caption: String) async throws -> String {
        struct Created: Decodable { let jobId: String }
        let created: Created = try await post(path: "jobs",
                                              body: ["kind": "publish_instagram",
                                                     "source_job_id": sourceJobId,
                                                     "output_path": outputPath,
                                                     "caption": caption],
                                              timeout: 15)
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
