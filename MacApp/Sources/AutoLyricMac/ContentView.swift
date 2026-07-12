import SwiftUI

struct ContentView: View {
    @ObservedObject var engineManager: EngineManager
    @StateObject private var engine = EngineClient()

    @State private var youtubeURL: String = ""
    @State private var durationSeconds: Int = 30

    // Source inspection
    enum InspectState: Equatable {
        case idle
        case inspecting
        case loaded(SourceMetadata)
        case failed(String)
    }
    @State private var inspectState: InspectState = .idle
    @State private var inspectTask: Task<Void, Never>?

    // Audio-download test
    @State private var authorizationConfirmed = false
    @State private var activeJob: JobStatus?
    @State private var jobTask: Task<Void, Never>?
    @State private var jobError: String?

    private let durations = [30, 45, 60]

    private var metadata: SourceMetadata? {
        if case .loaded(let meta) = inspectState { return meta }
        return nil
    }

    private var urlIsValid: Bool {
        YouTubeURLValidator.videoID(from: youtubeURL) != nil
    }

    private var canCreateVideo: Bool {
        engine.status == .connected && urlIsValid && metadata?.valid == true
    }

    private var jobIsRunning: Bool {
        if let job = activeJob { return !job.isTerminal }
        return jobTask != nil && activeJob == nil
    }

    private var canStartDownload: Bool {
        canCreateVideo && authorizationConfirmed && !jobIsRunning
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                urlSection
                metadataSection
                durationSection

                Button("Create Video") {
                    // Rendering arrives in a later step; the gate itself is the feature here.
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!canCreateVideo)

                Divider()

                downloadTestSection

                Spacer(minLength: 0)
            }
            .padding(24)
        }
        .frame(minWidth: 520, minHeight: 640)
        .onAppear { engine.startPolling() }
        .onChange(of: youtubeURL) { _, _ in scheduleInspection() }
    }

    // MARK: - Sections

    private var header: some View {
        HStack {
            Text("AutoLyricMac")
                .font(.largeTitle.bold())
            Spacer()
            engineStatusBadge
        }
    }

    private var urlSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("YouTube URL")
                .font(.headline)
            TextField("https://www.youtube.com/watch?v=…", text: $youtubeURL)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
            if !youtubeURL.isEmpty && !urlIsValid {
                Label("Not a valid YouTube URL", systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
    }

    @ViewBuilder
    private var metadataSection: some View {
        switch inspectState {
        case .idle:
            EmptyView()
        case .inspecting:
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Fetching video info…")
                    .foregroundStyle(.secondary)
            }
        case .failed(let message):
            Label(message, systemImage: "xmark.octagon")
                .font(.callout)
                .foregroundStyle(.red)
        case .loaded(let meta):
            metadataCard(meta)
        }
    }

    private func metadataCard(_ meta: SourceMetadata) -> some View {
        HStack(alignment: .top, spacing: 12) {
            AsyncImage(url: meta.thumbnailUrl.flatMap(URL.init(string:))) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                Rectangle().fill(.quaternary)
                    .overlay(Image(systemName: "music.note").foregroundStyle(.secondary))
            }
            .frame(width: 120, height: 68)
            .clipShape(RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 4) {
                Text(meta.title ?? "Untitled")
                    .font(.headline)
                    .lineLimit(2)
                if let uploader = meta.uploader {
                    Text(uploader)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                HStack(spacing: 12) {
                    if let duration = meta.duration {
                        Label(Self.formatDuration(duration), systemImage: "clock")
                    }
                    if let id = meta.videoId {
                        Label(id, systemImage: "number")
                            .font(.caption.monospaced())
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }

    private var durationSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Duration")
                .font(.headline)
            Picker("Duration", selection: $durationSeconds) {
                ForEach(durations, id: \.self) { seconds in
                    Text("\(seconds) s").tag(seconds)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(maxWidth: 260)
        }
    }

    private var downloadTestSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Audio Ingestion Test")
                .font(.headline)

            Toggle(isOn: $authorizationConfirmed) {
                Text("I confirm that I own, license, or am authorized to process and publish this media.")
                    .font(.callout)
            }
            .toggleStyle(.checkbox)

            HStack(spacing: 12) {
                Button("Test Audio Download") { startDownloadTest() }
                    .disabled(!canStartDownload)
                if jobIsRunning {
                    Button("Cancel", role: .cancel) { cancelDownloadTest() }
                }
            }

            if let job = activeJob {
                jobStatusView(job)
            }
            if let error = jobError {
                Label(error, systemImage: "xmark.octagon")
                    .font(.callout)
                    .foregroundStyle(.red)
            }
        }
    }

    @ViewBuilder
    private func jobStatusView(_ job: JobStatus) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if !job.isTerminal {
                ProgressView(value: job.progress)
            }
            Label(job.message, systemImage: iconForJobState(job.state))
                .font(.callout)
                .foregroundStyle(job.state == "error" ? .red : .primary)

            if job.state == "done", let path = job.audioPath {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text("Audio file:")
                            .font(.caption.weight(.semibold))
                        Text(path)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Button("Reveal in Finder") {
                            NSWorkspace.shared.activateFileViewerSelecting(
                                [URL(fileURLWithPath: path)])
                        }
                        .controlSize(.small)
                    }
                    if let duration = job.audioDuration {
                        Text("Duration: \(Self.formatDuration(duration))  •  Format: \(job.audioFormat ?? "?")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(10)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func iconForJobState(_ state: String) -> String {
        switch state {
        case "done": return "checkmark.circle.fill"
        case "error": return "xmark.octagon"
        case "cancelled": return "slash.circle"
        default: return "arrow.down.circle"
        }
    }

    // MARK: - Actions

    private func scheduleInspection() {
        inspectTask?.cancel()
        activeJob = nil
        jobError = nil

        guard urlIsValid else {
            inspectState = .idle
            return
        }
        let url = youtubeURL.trimmingCharacters(in: .whitespacesAndNewlines)
        inspectTask = Task {
            // Debounce while the user is typing/pasting.
            try? await Task.sleep(for: .milliseconds(700))
            guard !Task.isCancelled else { return }
            inspectState = .inspecting
            do {
                let meta = try await engine.inspect(url: url)
                guard !Task.isCancelled else { return }
                inspectState = .loaded(meta)
            } catch let error as EngineAPIError {
                guard !Task.isCancelled else { return }
                inspectState = .failed(error.errorDescription ?? "Inspection failed.")
            } catch is CancellationError {
                // superseded by newer input
            } catch {
                guard !Task.isCancelled else { return }
                inspectState = .failed("Cannot reach the local engine. Is it running?")
            }
        }
    }

    private func startDownloadTest() {
        jobError = nil
        activeJob = nil
        let url = youtubeURL.trimmingCharacters(in: .whitespacesAndNewlines)
        jobTask = Task {
            do {
                let jobId = try await engine.createJob(url: url, authorized: authorizationConfirmed)
                while !Task.isCancelled {
                    let status = try await engine.jobStatus(id: jobId)
                    activeJob = status
                    if status.isTerminal { break }
                    try? await Task.sleep(for: .milliseconds(500))
                }
            } catch let error as EngineAPIError {
                jobError = error.errorDescription
            } catch {
                jobError = "Lost contact with the local engine: \(error.localizedDescription)"
            }
            jobTask = nil
        }
    }

    private func cancelDownloadTest() {
        guard let job = activeJob, !job.isTerminal else {
            jobTask?.cancel()
            jobTask = nil
            return
        }
        Task {
            try? await engine.cancelJob(id: job.jobId)
        }
    }

    // MARK: - Presentation helpers

    private var engineStatusBadge: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(statusColor)
                .frame(width: 10, height: 10)
            Text(statusText)
                .font(.callout.weight(.medium))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(.quaternary, in: Capsule())
        .help(engineStateDetail)
    }

    private var statusText: String {
        switch engineManager.state {
        case .starting: return "Starting Engine…"
        case .failed: return "Engine Failed"
        case .stopped, .running:
            switch engine.status {
            case .unknown: return "Checking Engine…"
            case .connected: return "Engine Connected"
            case .offline: return "Engine Offline"
            }
        }
    }

    private var statusColor: Color {
        switch engineManager.state {
        case .starting: return .yellow
        case .failed: return .red
        case .stopped, .running:
            switch engine.status {
            case .unknown: return .gray
            case .connected: return .green
            case .offline: return .red
            }
        }
    }

    private var engineStateDetail: String {
        if case .failed(let message) = engineManager.state { return message }
        return "Local engine on 127.0.0.1:8765"
    }

    static func formatDuration(_ seconds: Double) -> String {
        let total = Int(seconds.rounded())
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }
}

#Preview {
    ContentView(engineManager: EngineManager.shared)
}
