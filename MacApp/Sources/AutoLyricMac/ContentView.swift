import AVFoundation
import SwiftUI

struct ContentView: View {
    @ObservedObject var engineManager: EngineManager
    @StateObject private var engine = EngineClient()
    @ObservedObject private var log = AppLog.shared

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

    // Audio preview of the ingested file
    @State private var previewPlayer: AVAudioPlayer?
    @State private var isPreviewPlaying = false

    // Segment analysis (Phase 2)
    @State private var analysisJob: JobStatus?
    @State private var analysisTask: Task<Void, Never>?
    @State private var analysisError: String?
    @State private var startOverrideText: String = ""

    // Lyrics & synchronization (Phase 3)
    @State private var lyricArtist: String = ""
    @State private var lyricTitle: String = ""
    @State private var lyricsJob: JobStatus?
    @State private var lyricsTask: Task<Void, Never>?
    @State private var lyricsError: String?
    @State private var lyrics: LyricsPayload?
    @State private var editingLine: Int?
    @State private var correctionDraft: String = ""
    @State private var translationDraft: String = ""
    @State private var previewStyle: String = "archiveCollage"
    @State private var showManualLyrics = false
    @State private var manualLyricsDraft: String = ""
    @State private var showManualTranslations = false
    @State private var manualTranslationsDraft: String = ""

    // Scene plan & media (Phase 4)
    @State private var planTheme: String = ""
    @State private var planStyle: String = "automatic"
    @State private var artStyle: String = "storybook"
    @State private var aiImages: Bool = false
    @State private var instrumentalMode: Bool = false
    @State private var motionEffects: Bool = false
    @State private var syncOffset: Double = 0.0
    @State private var planJob: JobStatus?
    @State private var planTask: Task<Void, Never>?
    @State private var planError: String?
    @State private var plan: PlanPayload?
    @State private var pexelsKey: String = ""
    @State private var pixabayKey: String = ""
    @State private var unsplashKey: String = ""
    @State private var keysLoaded = false

    // History (Phase 7)
    @State private var projects: [ProjectPayload] = []
    @State private var historyLoaded = false
    @State private var cleanupMessage: String?

    // One-click Create Video pipeline
    @State private var createTask: Task<Void, Never>?
    @State private var createStage: String?
    @State private var createError: String?
    @State private var createJobId: String?

    // YouTube publishing (Phase 8)
    @State private var youtubeConnected = false
    @State private var youtubeClientId: String = ""
    @State private var youtubeClientSecret: String = ""
    @State private var youtubeFlowMessage: String?
    @State private var publishTitle: String = ""
    @State private var publishDescription: String = ""
    @State private var publishTags: String = ""
    @State private var captionBusy = false
    @State private var captionError: String?
    @State private var publishPrivacy: String = "private"
    @State private var publishedURL: String?

    // Instagram publishing (Phase 9)
    @State private var instagramConnected = false
    @State private var igToken: String = ""
    @State private var igUserId: String = ""
    @State private var igS3Endpoint: String = ""
    @State private var igS3Bucket: String = ""
    @State private var igS3AccessKey: String = ""
    @State private var igS3SecretKey: String = ""
    @State private var igS3PublicBase: String = ""
    @State private var igMessage: String?

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
                historySection
                urlSection
                metadataSection
                durationSection

                createVideoSection

                Divider()

                downloadTestSection

                if activeJob?.state == "done" {
                    Divider()
                    segmentSection
                    Divider()
                    lyricsSection
                    Divider()
                    planSection
                }

                Divider()

                logSection

                Spacer(minLength: 0)
            }
            .padding(24)
        }
        .frame(minWidth: 520, minHeight: 720)
        .onAppear { engine.startPolling() }
        .onChange(of: youtubeURL) { _, _ in scheduleInspection() }
        .onChange(of: engine.status) { _, status in
            if status == .connected && !historyLoaded {
                historyLoaded = true
                refreshHistory()
            }
        }
        .onChange(of: activeJob?.state) { _, state in
            if state == "done" { refreshHistory() }
        }
        .onChange(of: planJob?.state) { _, state in
            if state == "done" { refreshHistory() }
        }
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
            Text("Authorization & Manual Steps")
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
                VStack(alignment: .leading, spacing: 6) {
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
                    HStack(spacing: 12) {
                        Button {
                            togglePreview(path: path)
                        } label: {
                            Label(isPreviewPlaying ? "Pause Preview" : "Play Preview",
                                  systemImage: isPreviewPlaying ? "pause.fill" : "play.fill")
                        }
                        .controlSize(.small)
                        if let duration = job.audioDuration {
                            Text("Duration: \(Self.formatDuration(duration))  •  Format: \(job.audioFormat ?? "?")")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
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

    private var analysisIsRunning: Bool {
        if let job = analysisJob { return !job.isTerminal }
        return analysisTask != nil && analysisJob == nil
    }

    private var segmentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Segment Selection")
                .font(.headline)
            HStack(spacing: 12) {
                Button("Analyze & Select \(durationSeconds)s Segment") { startAnalysis() }
                    .disabled(engine.status != .connected || analysisIsRunning)
                if analysisIsRunning {
                    Button("Cancel", role: .cancel) { cancelAnalysis() }
                }
                TextField("Start override (s, optional)", text: $startOverrideText)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 190)
            }

            if let job = analysisJob {
                if !job.isTerminal {
                    ProgressView(value: job.progress)
                }
                Label(job.message, systemImage: iconForJobState(job.state))
                    .font(.callout)
                    .foregroundStyle(job.state == "error" ? .red : .primary)

                if job.state == "done", let result = job.result, let path = job.audioPath {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 12) {
                            Button {
                                togglePreview(path: path)
                            } label: {
                                Label(isPreviewPlaying ? "Pause Segment" : "Play Segment",
                                      systemImage: isPreviewPlaying ? "pause.fill" : "play.fill")
                            }
                            .controlSize(.small)
                            Text("\(Int(result.tempoBpm ?? 0)) BPM  •  \(Self.formatDuration(result.segmentStart ?? 0))–\(Self.formatDuration(result.segmentEnd ?? 0)) of \(Self.formatDuration(result.trackDuration ?? 0))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        ForEach(result.reasons ?? [], id: \.self) { reason in
                            Text("• \(reason)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(10)
                    .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
                }
            }
            if let error = analysisError {
                Label(error, systemImage: "xmark.octagon")
                    .font(.callout)
                    .foregroundStyle(.red)
            }
        }
    }

    // MARK: - One-click Create Video

    private var createRunning: Bool { createTask != nil }

    private var createVideoSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Picker("Style", selection: $planStyle) {
                    Text("Automatic").tag("automatic")
                    Text("Archive Collage").tag("archiveCollage")
                    Text("Doodle Memory").tag("doodleMemory")
                    Text("Polaroid Wall").tag("polaroidWall")
                    Text("Minimal Dark").tag("minimalDark")
                    Text("Cinematic Still").tag("cinemaStill")
                    Text("Comic / Pop-Art").tag("comicPop")
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .fixedSize()
                Button(createRunning ? "Creating…" : "Create Video") {
                    startCreateVideo()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!canCreateVideo || !authorizationConfirmed
                          || !anyProviderKey || createRunning)
                if createRunning {
                    Button("Cancel", role: .cancel) { cancelCreateVideo() }
                }
            }
            if !authorizationConfirmed {
                Text("Confirm the authorization checkbox below first.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if !anyProviderKey {
                Text("Add a stock media API key (Stock Media API Keys section) first.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let stage = createStage {
                Label(stage, systemImage: createRunning
                      ? "gearshape.2" : "checkmark.circle.fill")
                    .font(.callout)
            }
            if let error = createError {
                Label(error, systemImage: "xmark.octagon")
                    .font(.callout)
                    .foregroundStyle(.red)
            }
        }
    }

    /// Poll one engine job to its terminal state, mirroring it into `update`.
    private func awaitJob(_ jobId: String,
                          update: @escaping (JobStatus) -> Void) async throws -> JobStatus {
        createJobId = jobId
        while true {
            try Task.checkCancellation()
            let status = try await engine.jobStatus(id: jobId)
            update(status)
            if status.isTerminal { return status }
            try? await Task.sleep(for: .milliseconds(500))
        }
    }

    private func startCreateVideo() {
        let url = youtubeURL.trimmingCharacters(in: .whitespacesAndNewlines)
        createError = nil
        createStage = nil
        activeJob = nil
        analysisJob = nil
        lyricsJob = nil
        planJob = nil
        lyrics = nil
        plan = nil
        editingLine = nil
        stopPreview()
        let keys = providerKeys
        let style = planStyle
        let seconds = durationSeconds

        createTask = Task {
            defer { createTask = nil; createJobId = nil }
            @MainActor func stage(_ text: String) {
                createStage = text
                AppLog.shared.append("Create Video: \(text)")
            }
            do {
                stage("1/7 Downloading audio…")
                var status = try await awaitJob(
                    engine.createJob(url: url, authorized: authorizationConfirmed)
                ) { activeJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }
                let sourceId = status.jobId

                stage("2/7 Analyzing and selecting the best \(seconds)s…")
                status = try await awaitJob(
                    engine.createAnalyzeJob(sourceJobId: sourceId,
                                            targetSeconds: seconds,
                                            startOverride: nil)
                ) { analysisJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }
                let segmentStart = status.result?.segmentStart ?? 0

                stage("3/7 Searching lyrics…")
                status = try await awaitJob(
                    engine.createLyricsJob(sourceJobId: sourceId,
                                           artist: lyricArtist,
                                           title: lyricTitle)
                ) { lyricsJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }
                lyrics = try? await engine.fetchLyrics(sourceJobId: sourceId)

                stage("4/7 Aligning words (local Whisper)…")
                status = try await awaitJob(
                    engine.createAlignJob(sourceJobId: sourceId)
                ) { lyricsJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }
                lyrics = try? await engine.fetchLyrics(sourceJobId: sourceId)

                stage("5/7 Planning scenes…")
                status = try await awaitJob(
                    engine.createPlanJob(sourceJobId: sourceId, style: style,
                                         segmentStart: segmentStart,
                                         targetSeconds: seconds,
                                         theme: planTheme.trimmingCharacters(in: .whitespaces))
                ) { planJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }
                let resolvedStyle = status.result?.style ?? "archiveCollage"

                stage("6/7 Fetching licensed media…")
                status = try await awaitJob(
                    engine.createMediaJob(sourceJobId: sourceId, apiKeys: keys)
                ) { planJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }
                plan = try? await engine.fetchPlan(sourceJobId: sourceId)

                stage("7/7 Rendering \(resolvedStyle)…")
                status = try await awaitJob(
                    engine.createRenderJob(sourceJobId: sourceId,
                                           style: resolvedStyle,
                                           motionEffects: motionEffects,
                                           syncOffset: syncOffset)
                ) { planJob = $0 }
                guard status.state == "done" else { throw PipelineStop(status) }

                createStage = "Done — video ready. Scroll down to open it."
                refreshHistory()
                if let path = status.result?.outputPath {
                    NSWorkspace.shared.activateFileViewerSelecting(
                        [URL(fileURLWithPath: path)])
                }
            } catch let stop as PipelineStop {
                createStage = nil
                createError = stop.status.message
                AppLog.shared.append("Create Video stopped: \(stop.status.message)")
            } catch is CancellationError {
                createStage = nil
                createError = "Cancelled."
            } catch let error as EngineAPIError {
                createStage = nil
                createError = error.errorDescription
            } catch {
                createStage = nil
                createError = "Lost contact with the local engine: \(error.localizedDescription)"
            }
        }
    }

    private struct PipelineStop: Error {
        let status: JobStatus
        init(_ status: JobStatus) { self.status = status }
    }

    private func cancelCreateVideo() {
        if let jobId = createJobId {
            Task { try? await engine.cancelJob(id: jobId) }
        }
        createTask?.cancel()
    }

    // MARK: - History (Phase 7)

    @ViewBuilder
    private var historySection: some View {
        if !projects.isEmpty {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(projects) { project in
                        projectRow(project)
                    }
                    HStack(spacing: 12) {
                        Button("Clean Up Caches") { runCleanup() }
                            .controlSize(.small)
                        if let message = cleanupMessage {
                            Text(message)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.top, 4)
                }
                .padding(.top, 6)
            } label: {
                Text("History (\(projects.count))")
                    .font(.headline)
            }
        }
    }

    @ViewBuilder
    private func projectRow(_ project: ProjectPayload) -> some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(project.title ?? project.videoId ?? String(project.jobId.prefix(8)))
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                HStack(spacing: 8) {
                    if let uploader = project.uploader {
                        Text(uploader)
                    }
                    if let style = project.style {
                        Text(style)
                    }
                    Text("\(project.outputs.count) video(s)")
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
            Spacer()
            if project.audioExists == true {
                Button("Resume") { resumeProject(project) }
                    .controlSize(.small)
            }
            if let output = project.outputs.first {
                Button {
                    NSWorkspace.shared.open(URL(fileURLWithPath: output.filePath))
                } label: {
                    Image(systemName: "play.rectangle")
                }
                .buttonStyle(.plain)
                .help("Open the latest rendered video")
            }
            Button {
                revealProject(project)
            } label: {
                Image(systemName: "folder")
            }
            .buttonStyle(.plain)
            .help("Reveal project files in Finder")
            Button(role: .destructive) {
                deleteProject(project)
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.plain)
            .help("Remove from history and delete cached files (rendered videos are kept)")
        }
        .padding(.vertical, 2)
    }

    private func refreshHistory() {
        Task {
            projects = (try? await engine.listProjects()) ?? projects
        }
    }

    private func resumeProject(_ project: ProjectPayload) {
        stopPreview()
        jobError = nil
        analysisJob = nil
        analysisError = nil
        lyricsJob = nil
        lyricsError = nil
        planJob = nil
        planError = nil
        editingLine = nil
        activeJob = JobStatus(
            jobId: project.jobId, kind: "download", state: "done",
            progress: 1.0, message: "Restored from history.",
            errorCode: nil, audioPath: project.audioPath,
            audioDuration: project.duration, audioFormat: "aac", result: nil)
        if let target = project.targetSeconds,
           [30, 45, 60].contains(Int(target)) {
            durationSeconds = Int(target)
        }
        let guess = SongTitleParser.guess(title: project.title,
                                          uploader: project.uploader)
        lyricArtist = guess.artist
        lyricTitle = guess.title
        Task {
            lyrics = try? await engine.fetchLyrics(sourceJobId: project.jobId)
            plan = try? await engine.fetchPlan(sourceJobId: project.jobId)
            AppLog.shared.append("Project \(project.jobId.prefix(8)) restored from history.")
        }
    }

    private func revealProject(_ project: ProjectPayload) {
        if let path = project.audioPath {
            NSWorkspace.shared.activateFileViewerSelecting(
                [URL(fileURLWithPath: path).deletingLastPathComponent()])
        }
    }

    private func deleteProject(_ project: ProjectPayload) {
        Task {
            try? await engine.deleteProject(jobId: project.jobId,
                                            deleteFiles: true)
            if activeJob?.jobId == project.jobId {
                activeJob = nil
                lyrics = nil
                plan = nil
            }
            AppLog.shared.append("Project \(project.jobId.prefix(8)) removed from history.")
            refreshHistory()
        }
    }

    private func runCleanup() {
        Task {
            if let result = try? await engine.runCleanup() {
                let mb = Double(result.freedBytes) / 1_048_576
                cleanupMessage = "Removed \(result.removed) item(s), freed \(String(format: "%.1f", mb)) MB."
                AppLog.shared.append("Cache cleanup: \(cleanupMessage ?? "")")
            }
        }
    }

    // MARK: - Lyrics & sync (Phase 3)

    private var lyricsJobRunning: Bool {
        if let job = lyricsJob { return !job.isTerminal }
        return lyricsTask != nil && lyricsJob == nil
    }

    private var lyricsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Lyrics & Sync")
                .font(.headline)

            HStack(spacing: 8) {
                TextField("Artist", text: $lyricArtist)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 180)
                TextField("Song title", text: $lyricTitle)
                    .textFieldStyle(.roundedBorder)
            }

            HStack(spacing: 12) {
                Button("Fetch Lyrics") { startLyricsFetch() }
                    .disabled(engine.status != .connected || lyricsJobRunning
                              || lyricTitle.trimmingCharacters(in: .whitespaces).isEmpty)
                Button("Enter Lyrics Manually…") {
                    manualLyricsDraft = ""
                    showManualLyrics = true
                }
                .disabled(engine.status != .connected || lyricsJobRunning)
                Button("Align Words") { startAlign() }
                    .disabled(engine.status != .connected || lyricsJobRunning || lyrics == nil)
                Button("Türkçe'ye Çevir") { startTranslate() }
                    .disabled(engine.status != .connected || lyricsJobRunning || lyrics == nil)
                    .help("Her satırı Türkçe'ye çevirir (Claude; yoksa Argos), "
                          + "böylece çeviri satırla eşleşir. Türkçe şarkılar "
                          + "atlanır. Elle düzenlemek için “Türkçe Çeviriler…”.")
                Button("Türkçe Çeviriler…") {
                    manualTranslationsDraft = ""
                    showManualTranslations = true
                }
                .disabled(engine.status != .connected || lyrics == nil)
                if lyricsJobRunning {
                    Button("Cancel", role: .cancel) { cancelLyricsJob() }
                }
            }
            .sheet(isPresented: $showManualLyrics) { manualLyricsSheet }
            .sheet(isPresented: $showManualTranslations) { manualTranslationsSheet }

            if let job = lyricsJob {
                if !job.isTerminal {
                    ProgressView(value: job.progress)
                }
                Label(job.message, systemImage: iconForJobState(job.state))
                    .font(.callout)
                    .foregroundStyle(job.state == "error" ? .red : .primary)
            }
            if let error = lyricsError {
                Label(error, systemImage: "xmark.octagon")
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            if let lyrics {
                lyricsDetail(lyrics)
            }
        }
    }

    private var manualLyricsSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Enter Lyrics Manually")
                .font(.headline)
            Text("Paste the lyrics, one line per row (or .lrc content with timestamps). Word timing comes from Align Words afterwards. Use “Türkçe'ye Çevir” for a Turkish translation when you want one.")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextEditor(text: $manualLyricsDraft)
                .font(.callout.monospaced())
                .frame(minWidth: 460, minHeight: 280)
                .overlay(RoundedRectangle(cornerRadius: 6)
                    .stroke(.quaternary))
            HStack {
                Spacer()
                Button("Cancel") { showManualLyrics = false }
                Button("Save & Align") { saveManualLyrics() }
                    .buttonStyle(.borderedProminent)
                    .disabled(manualLyricsDraft.trimmingCharacters(in: .whitespacesAndNewlines).count < 10)
            }
        }
        .padding(20)
    }

    private func saveManualLyrics() {
        guard let source = activeJob, source.state == "done" else { return }
        let text = manualLyricsDraft
        showManualLyrics = false
        Task {
            do {
                lyrics = try await engine.setManualLyrics(
                    sourceJobId: source.jobId, text: text,
                    artist: lyricArtist, title: lyricTitle)
                lyricsError = nil
                AppLog.shared.append("Manual lyrics saved (\(lyrics?.lines.count ?? 0) lines); aligning…")
                startAlign()
            } catch let error as EngineAPIError {
                lyricsError = error.errorDescription
            } catch {
                lyricsError = "Could not save the lyrics: \(error.localizedDescription)"
            }
        }
    }

    private var manualTranslationsSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Türkçe Çevirileri Yapıştır")
                .font(.headline)
            Text("Her satır, sözlerin aynı sıradaki satırına eşlenir. Boş bırakılan satırın çevirisi olmaz. Soldaki orijinal sözler sıra referansıdır.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(alignment: .top, spacing: 10) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(lyrics?.lines ?? []) { line in
                            Text("\(line.lineIndex + 1). \(line.displayText)")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
                .frame(width: 300, height: 300)
                TextEditor(text: $manualTranslationsDraft)
                    .font(.callout.monospaced())
                    .frame(minWidth: 320, minHeight: 300)
                    .overlay(RoundedRectangle(cornerRadius: 6)
                        .stroke(.quaternary))
            }
            HStack {
                Spacer()
                Button("Vazgeç") { showManualTranslations = false }
                Button("Kaydet") { saveManualTranslations() }
                    .buttonStyle(.borderedProminent)
                    .disabled(manualTranslationsDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(20)
    }

    private func saveManualTranslations() {
        guard let source = activeJob, source.state == "done" else { return }
        let text = manualTranslationsDraft
        showManualTranslations = false
        Task {
            do {
                let applied = try await engine.setManualTranslations(
                    sourceJobId: source.jobId, text: text)
                await refreshLyrics()
                AppLog.shared.append("\(applied) satıra Türkçe çeviri eklendi.")
            } catch let error as EngineAPIError {
                lyricsError = error.errorDescription
            } catch {
                lyricsError = "Çeviriler kaydedilemedi: \(error.localizedDescription)"
            }
        }
    }

    @ViewBuilder
    private func lyricsDetail(_ payload: LyricsPayload) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if payload.suspect {
                Label("These lyrics may not match this recording. Review them or try a local .lrc/.txt file.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(.orange)
            }
            HStack(spacing: 12) {
                Text("\(payload.lines.count) lines  •  \(payload.provider)  •  \(payload.synced ? "synced" : "plain")")
                if payload.aligned, let ratio = payload.matchedRatio {
                    Text("aligned: \(Int(ratio * 100))% words matched")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                ForEach(payload.lines) { line in
                    lyricLineRow(line)
                }
            }
            .padding(8)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))

            subtitlePreviewControls
        }
    }

    private func confidenceColor(_ line: LyricLinePayload) -> Color {
        guard let confidence = line.confidence else { return .gray }
        if confidence >= 0.8 { return .green }
        if confidence >= 0.55 { return .yellow }
        return .red
    }

    @ViewBuilder
    private func lyricLineRow(_ line: LyricLinePayload) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Circle()
                    .fill(confidenceColor(line))
                    .frame(width: 8, height: 8)
                    .help(line.confidence.map { "Confidence \(Int($0 * 100))%" }
                          ?? "Not aligned yet")
                if let start = line.start, let end = line.end {
                    Text("\(Self.formatDuration(start))–\(Self.formatDuration(end))")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                } else {
                    Text("—")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                }
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text(line.displayText)
                            .font(.callout)
                        if line.uncertain {
                            Image(systemName: "questionmark.circle.fill")
                                .foregroundStyle(.orange)
                                .font(.caption)
                                .help("Low confidence — check this line")
                        }
                        if line.correctedText != nil {
                            Image(systemName: "pencil.circle.fill")
                                .foregroundStyle(.blue)
                                .font(.caption)
                                .help("Edited by you")
                        }
                    }
                    if let translation = line.translation, !translation.isEmpty {
                        Text(translation)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Button {
                    beginEditing(line)
                } label: {
                    Image(systemName: "pencil")
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .help("Edit text / Turkish translation")
            }
            if editingLine == line.lineIndex {
                VStack(alignment: .leading, spacing: 6) {
                    TextField("Corrected lyric (empty = original)", text: $correctionDraft)
                        .textFieldStyle(.roundedBorder)
                    TextField("Turkish translation (optional)", text: $translationDraft)
                        .textFieldStyle(.roundedBorder)
                    HStack {
                        Button("Save") { saveLineEdit(line.lineIndex) }
                            .controlSize(.small)
                        Button("Cancel") { editingLine = nil }
                            .controlSize(.small)
                    }
                }
                .padding(.leading, 24)
                .padding(.vertical, 4)
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var subtitlePreviewControls: some View {
        let aligned = lyrics?.aligned == true
        let haveSegment = analysisJob?.state == "done"
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Picker("Style", selection: $previewStyle) {
                    Text("Archive Collage").tag("archiveCollage")
                    Text("Doodle Memory").tag("doodleMemory")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 300)
                Button("Render Subtitle Preview") { startSubtitlePreview() }
                    .disabled(engine.status != .connected || lyricsJobRunning
                              || !aligned || !haveSegment)
            }
            if !aligned || !haveSegment {
                Text("Requires aligned lyrics and a selected segment.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if lyricsJob?.kind == "subtitle_preview", lyricsJob?.state == "done",
               let path = lyricsJob?.result?.outputPath {
                HStack(spacing: 12) {
                    Button {
                        NSWorkspace.shared.open(URL(fileURLWithPath: path))
                    } label: {
                        Label("Open Preview", systemImage: "play.rectangle")
                    }
                    .controlSize(.small)
                    Button("Reveal in Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting(
                            [URL(fileURLWithPath: path)])
                    }
                    .controlSize(.small)
                }
            }
        }
    }

    // MARK: - Scene plan & media (Phase 4)

    private var planJobRunning: Bool {
        if let job = planJob { return !job.isTerminal }
        return planTask != nil && planJob == nil
    }

    private var anyProviderKey: Bool {
        ![pexelsKey, pixabayKey, unsplashKey].allSatisfy {
            $0.trimmingCharacters(in: .whitespaces).isEmpty
        }
    }

    /// Newest rendered video for the active project: this session's render
    /// if present, else the latest output recorded in history.
    private var latestOutputPath: String? {
        if planJob?.kind == "render", planJob?.state == "done",
           let path = planJob?.result?.outputPath {
            return path
        }
        guard let source = activeJob else { return nil }
        return projects.first(where: { $0.jobId == source.jobId })?
            .outputs.first?.filePath
    }

    private var planHasMedia: Bool {
        plan?.scenes.contains(where: { $0.media != nil }) == true
    }

    private var planSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Scene Plan & Media")
                .font(.headline)

            TextField("Song theme / mood (optional — e.g. \"pişmanlık, geçen zaman, yalnızlık, karanlık şehir\")",
                      text: $planTheme)
                .textFieldStyle(.roundedBorder)
                .help("Guides image search for every scene; rebuild the plan after changing it")

            Toggle("Sadece melodi (enstrümantal) — temadan resim çizsin, altyazı yok",
                   isOn: $instrumentalMode)
                .toggleStyle(.checkbox)
                .help("Sözü olmayan parçalarda kullanılır. Yukarıdaki temayı "
                      + "girip stil seç; sözler yerine tema baştan sona AI ile "
                      + "sahne sahne çizilir. Fetch/Align gerekmez.")
            if instrumentalMode
                && planTheme.trimmingCharacters(in: .whitespaces).isEmpty {
                Text("Enstrümantal modda görseller için bir tema girmelisin.")
                    .font(.caption).foregroundStyle(.orange)
            } else if !instrumentalMode && lyrics?.aligned != true {
                Text("Önce sözleri getirip Align Words'ü çalıştır — ya da üstteki \"Sadece melodi\" kutusunu işaretle.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            HStack(spacing: 12) {
                Picker("Plan style", selection: $planStyle) {
                    Text("Automatic").tag("automatic")
                    Text("Archive Collage").tag("archiveCollage")
                    Text("Doodle Memory").tag("doodleMemory")
                    Text("Polaroid Wall").tag("polaroidWall")
                    Text("Minimal Dark").tag("minimalDark")
                    Text("Cinematic Still").tag("cinemaStill")
                    Text("Comic / Pop-Art").tag("comicPop")
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .fixedSize()
                Button("Build Scene Plan") { startPlan() }
                    .disabled(instrumentalMode
                              ? planTheme.trimmingCharacters(in: .whitespaces).isEmpty
                              : lyrics?.aligned != true)
                    .disabled(engine.status != .connected || planJobRunning
                              || analysisJob?.state != "done")
                Button("Fetch Licensed Media") { startMediaFetch() }
                    .disabled(engine.status != .connected || planJobRunning
                              || plan == nil
                              || !(anyProviderKey || instrumentalMode || aiImages))
                Button("Regenerate Media") { startMediaFetch(regenerate: true) }
                    .disabled(engine.status != .connected || planJobRunning
                              || !planHasMedia
                              || !(anyProviderKey || instrumentalMode || aiImages))
                    .help("Fetch fresh media for every scene (previous picks are avoided)")
                Button("Render Video") { startRender() }
                    .buttonStyle(.borderedProminent)
                    .disabled(engine.status != .connected || planJobRunning
                              || planHasMedia == false)
                if planJobRunning {
                    Button("Cancel", role: .cancel) { cancelPlanJob() }
                }
            }
            let isDoodle = planStyle == "doodleMemory" || planStyle == "automatic"
            if !isDoodle {
                Toggle("Arka plan resimlerini AI çiz (stok fotoğraf yerine)",
                       isOn: $aiImages)
                    .toggleStyle(.checkbox)
                    .help("Kolajda dönen görselleri fal.ai ile seçtiğin sanat "
                          + "stilinde çizer. Değiştirip Build/Regenerate Media.")
            }
            if isDoodle || aiImages {
                HStack(spacing: 8) {
                    Text("AI art style")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Picker("AI art style", selection: $artStyle) {
                        Text("Storybook Doodle").tag("storybook")
                        Text("Ghibli Anime").tag("ghibli")
                        Text("Realistic").tag("realistic")
                        Text("Watercolor").tag("watercolor")
                        Text("Modern Anime").tag("anime")
                        Text("Oil Painting").tag("oil")
                        Text("Caricature").tag("caricature")
                        Text("Pixel Art").tag("pixel")
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .fixedSize()
                    Text(isDoodle
                         ? "Doodle scenes drawn by fal.ai. Change then Build Media."
                         : "Background images drawn by fal.ai. Build/Regenerate Media.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            Toggle("Subtle motion effects (flicker & breathing)",
                   isOn: $motionEffects)
                .toggleStyle(.checkbox)
                .help("Off by default: no brightness flicker, no beat throb, "
                      + "no doodle breathing. Turn on for a livelier, filmic "
                      + "look. Applies to the next render.")
            HStack(spacing: 8) {
                Text("Söz–ses eşitleme")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Stepper(value: $syncOffset, in: -10...10, step: 0.25) {
                    Text(String(format: "%+.2f s", syncOffset))
                        .font(.caption.monospaced())
                        .frame(width: 64, alignment: .leading)
                }
                .fixedSize()
                if syncOffset != 0 {
                    Button("Sıfırla") { syncOffset = 0 }
                        .font(.caption2)
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                }
                Text("Sözler geç çıkıyorsa eksiye, erken çıkıyorsa artıya al. "
                     + "Render'a uygulanır.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            if analysisJob?.state != "done" {
                Text("Requires a selected segment (run Analyze first).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            keysSection

            if let job = planJob {
                if !job.isTerminal {
                    ProgressView(value: job.progress)
                }
                Label(job.message, systemImage: iconForJobState(job.state))
                    .font(.callout)
                    .foregroundStyle(job.state == "error" ? .red : .primary)
            }
            if let error = planError {
                Label(error, systemImage: "xmark.octagon")
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            if let path = latestOutputPath {
                HStack(spacing: 12) {
                    Button {
                        NSWorkspace.shared.open(URL(fileURLWithPath: path))
                    } label: {
                        Label("Open Video", systemImage: "play.rectangle.fill")
                    }
                    Button("Reveal in Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting(
                            [URL(fileURLWithPath: path)])
                    }
                    .controlSize(.small)
                }
                publishSection(outputPath: path)
            }

            if let plan {
                planDetail(plan)
            }
        }
        .onAppear { loadKeysOnce() }
    }

    private var keysSection: some View {
        DisclosureGroup("Stock Media API Keys (stored in Keychain)") {
            VStack(alignment: .leading, spacing: 6) {
                Text("Only official provider APIs are used. Keys stay in your macOS Keychain, travel only to the local engine, and are never written to disk or logs.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Text("Pexels").frame(width: 70, alignment: .leading)
                    SecureField("Pexels API key (free at pexels.com/api)", text: $pexelsKey)
                        .textFieldStyle(.roundedBorder)
                }
                HStack {
                    Text("Pixabay").frame(width: 70, alignment: .leading)
                    SecureField("Pixabay API key (optional)", text: $pixabayKey)
                        .textFieldStyle(.roundedBorder)
                }
                HStack {
                    Text("Unsplash").frame(width: 70, alignment: .leading)
                    SecureField("Unsplash access key (optional)", text: $unsplashKey)
                        .textFieldStyle(.roundedBorder)
                }
                Button("Save Keys to Keychain") {
                    KeychainStore.set(pexelsKey.trimmingCharacters(in: .whitespaces),
                                      account: "pexels_api_key")
                    KeychainStore.set(pixabayKey.trimmingCharacters(in: .whitespaces),
                                      account: "pixabay_api_key")
                    KeychainStore.set(unsplashKey.trimmingCharacters(in: .whitespaces),
                                      account: "unsplash_api_key")
                    AppLog.shared.append("Stock media keys saved to Keychain.")
                }
                .controlSize(.small)
            }
            .padding(.top, 4)
        }
        .font(.callout)
    }

    @ViewBuilder
    private func planDetail(_ plan: PlanPayload) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Text("\(plan.sceneCount) scenes (\(plan.lyricSceneCount) lyric)  •  style: \(plan.style)")
                if plan.style != plan.recommendedStyle {
                    Text("recommended: \(plan.recommendedStyle)")
                        .foregroundStyle(.orange)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            if let reason = plan.recommendationReason {
                Text("Automatic choice: \(reason)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 4) {
                ForEach(plan.scenes) { scene in
                    sceneRow(scene)
                }
            }
            .padding(8)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    @ViewBuilder
    private func sceneRow(_ scene: ScenePayload) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                Text("\(Self.formatDuration(scene.start))–\(Self.formatDuration(scene.end))")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .frame(width: 86, alignment: .leading)
                Text(scene.emotion)
                    .font(.caption2.weight(.semibold))
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1)
                    .background(.quaternary, in: Capsule())
                Text(scene.lyric ?? "(instrumental)")
                    .font(.callout)
                    .foregroundStyle(scene.lyric == nil ? .secondary : .primary)
                    .lineLimit(1)
                Spacer()
            }
            if let tr = scene.translation, !tr.isEmpty {
                Text(tr)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .padding(.leading, 94)
            }
            HStack(spacing: 8) {
                Text("search: \(scene.queries.first ?? "—")")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                if let media = scene.media {
                    Label("\(media.provider) · \(media.creator ?? "?") · \(media.license ?? "?")\(media.adaptation.map { " · \($0.strategy)" } ?? "")",
                          systemImage: "photo")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    if let ref = media.providerRef {
                        Button {
                            excludeAsset(provider: media.provider, ref: ref)
                        } label: {
                            Image(systemName: "xmark.circle")
                        }
                        .buttonStyle(.plain)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .help("Exclude this image and fetch a replacement")
                        .disabled(planJobRunning || !anyProviderKey)
                    }
                }
            }
            .padding(.leading, 94)
        }
        .padding(.vertical, 2)
    }

    // MARK: - YouTube publishing (Phase 8)

    @ViewBuilder
    private func publishSection(outputPath: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Button {
                    generateCaption()
                } label: {
                    Label(captionBusy ? "Üretiliyor…" : "✨ Başlık & Açıklama & Etiket Üret (AI)",
                          systemImage: "sparkles")
                }
                .disabled(engine.status != .connected || captionBusy
                          || activeJob?.state != "done")
                .help("Şarkıya göre keşfete düşürecek başlık, açıklama ve "
                      + "etiketleri Claude ile üretir ve alanları doldurur.")
                if captionBusy { ProgressView().controlSize(.small) }
            }
            if let e = captionError {
                Text(e).font(.caption2).foregroundStyle(.red)
            }
            TextField("Video başlığı", text: $publishTitle)
                .textFieldStyle(.roundedBorder)
            TextField("Açıklama (postun altındaki yazı)", text: $publishDescription,
                      axis: .vertical)
                .lineLimit(2...5)
                .textFieldStyle(.roundedBorder)
            TextField("Etiketler — #lyrics #nostalji #keşfet gibi", text: $publishTags)
                .textFieldStyle(.roundedBorder)

            Text("Publish to YouTube")
                .font(.subheadline.weight(.semibold))
            if !youtubeConnected {
                DisclosureGroup("Connect YouTube (official Google OAuth)") {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Create an OAuth client (Desktop app) in Google Cloud Console with the YouTube Data API enabled, then paste its credentials. Tokens are stored in your Keychain.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        TextField("OAuth client ID", text: $youtubeClientId)
                            .textFieldStyle(.roundedBorder)
                        SecureField("OAuth client secret", text: $youtubeClientSecret)
                            .textFieldStyle(.roundedBorder)
                        Button("Connect…") { startYouTubeConnect() }
                            .disabled(youtubeClientId.isEmpty
                                      || youtubeClientSecret.isEmpty)
                    }
                    .padding(.top, 4)
                }
                .font(.callout)
            } else {
                HStack(spacing: 12) {
                    Label("YouTube connected", systemImage: "checkmark.seal.fill")
                        .font(.callout)
                        .foregroundStyle(.green)
                    Button("Disconnect") {
                        Task {
                            try? await engine.youtubeDisconnect()
                            youtubeConnected = false
                            AppLog.shared.append("YouTube disconnected.")
                        }
                    }
                    .controlSize(.small)
                }
                HStack(spacing: 12) {
                    Picker("Privacy", selection: $publishPrivacy) {
                        Text("Private").tag("private")
                        Text("Unlisted").tag("unlisted")
                        Text("Public").tag("public")
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(maxWidth: 280)
                    Button("Publish") { startPublish(outputPath: outputPath) }
                        .buttonStyle(.borderedProminent)
                        .disabled(planJobRunning
                                  || publishTitle.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            if let message = youtubeFlowMessage {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let published = publishedURL, let url = URL(string: published) {
                HStack(spacing: 8) {
                    Link(published, destination: url)
                        .font(.callout)
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(published, forType: .string)
                    }
                    .controlSize(.small)
                }
            }

            Divider()
            instagramRow(outputPath: outputPath)
        }
        .padding(10)
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        .onAppear { refreshYouTubeStatus() }
    }

    @ViewBuilder
    private func instagramRow(outputPath: String) -> some View {
        Text("Publish to Instagram (Reels)")
            .font(.subheadline.weight(.semibold))
        if !instagramConnected {
            DisclosureGroup("Connect Instagram (official Meta Graph API)") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Needs an eligible professional account, a Meta app access token, and S3-compatible temporary storage (e.g. Cloudflare R2) because Instagram requires a public HTTPS video URL. The temp object is deleted right after publishing. Everything is stored in your Keychain.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    SecureField("Long-lived access token", text: $igToken)
                        .textFieldStyle(.roundedBorder)
                    TextField("Instagram professional account id", text: $igUserId)
                        .textFieldStyle(.roundedBorder)
                    TextField("S3 endpoint (https://…r2.cloudflarestorage.com)", text: $igS3Endpoint)
                        .textFieldStyle(.roundedBorder)
                    HStack {
                        TextField("Bucket", text: $igS3Bucket)
                            .textFieldStyle(.roundedBorder)
                        TextField("Public base URL", text: $igS3PublicBase)
                            .textFieldStyle(.roundedBorder)
                    }
                    HStack {
                        SecureField("Access key", text: $igS3AccessKey)
                            .textFieldStyle(.roundedBorder)
                        SecureField("Secret key", text: $igS3SecretKey)
                            .textFieldStyle(.roundedBorder)
                    }
                    Button("Connect Instagram") { connectInstagram() }
                        .disabled(igToken.isEmpty || igUserId.isEmpty)
                }
                .padding(.top, 4)
            }
            .font(.callout)
        } else {
            HStack(spacing: 12) {
                Label("Instagram connected", systemImage: "checkmark.seal.fill")
                    .font(.callout)
                    .foregroundStyle(.green)
                Button("Disconnect") {
                    Task {
                        try? await engine.instagramDisconnect()
                        instagramConnected = false
                    }
                }
                .controlSize(.small)
                Button("Publish Reel") { startInstagramPublish(outputPath: outputPath) }
                    .buttonStyle(.borderedProminent)
                    .disabled(planJobRunning)
            }
        }
        if let message = igMessage {
            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func connectInstagram() {
        let s3 = ["endpoint": igS3Endpoint, "bucket": igS3Bucket,
                  "region": "auto", "access_key": igS3AccessKey,
                  "secret_key": igS3SecretKey, "public_base": igS3PublicBase]
            .mapValues { $0.trimmingCharacters(in: .whitespaces) }
        Task {
            do {
                let username = try await engine.instagramConnect(
                    accessToken: igToken.trimmingCharacters(in: .whitespaces),
                    igUserId: igUserId.trimmingCharacters(in: .whitespaces),
                    s3: s3)
                instagramConnected = true
                igToken = ""
                igS3SecretKey = ""
                igMessage = "Connected as @\(username)."
                AppLog.shared.append("Instagram connected as @\(username).")
            } catch let error as EngineAPIError {
                igMessage = error.errorDescription
            } catch {
                igMessage = "Could not connect Instagram."
            }
        }
    }

    private func generateCaption() {
        guard let source = activeJob, source.state == "done" else { return }
        captionError = nil
        captionBusy = true
        let theme = planTheme.trimmingCharacters(in: .whitespaces)
        Task {
            defer { captionBusy = false }
            do {
                let status = try await awaitJob(
                    engine.createCaptionJob(sourceJobId: source.jobId,
                                            theme: theme)) { _ in }
                guard status.state == "done", let r = status.result else {
                    captionError = status.message
                    return
                }
                if let t = r.title, !t.isEmpty { publishTitle = t }
                if let d = r.description, !d.isEmpty { publishDescription = d }
                if let h = r.hashtags, !h.isEmpty {
                    publishTags = h.joined(separator: " ")
                }
            } catch {
                captionError = error.localizedDescription
            }
        }
    }

    private func startInstagramPublish(outputPath: String) {
        guard let source = activeJob, source.state == "done" else { return }
        publishedURL = nil
        // Instagram caption is the body itself (the song name already lives
        // inside it); the title is only used as the YouTube video title.
        let caption = [publishDescription, hashtagLine]
            .filter { !$0.isEmpty }.joined(separator: "\n\n")
        runPlanJob("Instagram publish") {
            try await engine.createInstagramPublishJob(
                sourceJobId: source.jobId, outputPath: outputPath,
                caption: caption)
        }
    }

    private func refreshYouTubeStatus() {
        Task {
            if let status = try? await engine.youtubeStatus() {
                youtubeConnected = status.connected
            }
            if let connected = try? await engine.instagramStatus() {
                instagramConnected = connected
            }
            if publishTitle.isEmpty {
                publishTitle = [lyricArtist, lyricTitle]
                    .filter { !$0.isEmpty }.joined(separator: " – ")
            }
        }
    }

    private func startYouTubeConnect() {
        let clientId = youtubeClientId.trimmingCharacters(in: .whitespaces)
        let secret = youtubeClientSecret.trimmingCharacters(in: .whitespaces)
        youtubeFlowMessage = "Opening Google sign-in in your browser…"
        Task {
            do {
                let flow = try await engine.youtubeConnect(clientId: clientId,
                                                           clientSecret: secret)
                if let url = URL(string: flow.authURL) {
                    NSWorkspace.shared.open(url)
                }
                for _ in 0..<150 {   // poll up to ~5 minutes
                    try? await Task.sleep(for: .seconds(2))
                    guard let status = try? await engine.youtubeStatus(state: flow.state) else { continue }
                    if let flowState = status.flow, flowState.status != "pending" {
                        youtubeConnected = status.connected
                        youtubeFlowMessage = flowState.message
                        if status.connected {
                            youtubeClientSecret = ""
                            AppLog.shared.append("YouTube connected via OAuth.")
                        }
                        return
                    }
                }
                youtubeFlowMessage = "Authorization timed out."
            } catch let error as EngineAPIError {
                youtubeFlowMessage = error.errorDescription
            } catch {
                youtubeFlowMessage = "Could not start the OAuth flow."
            }
        }
    }

    private var parsedTags: [String] {
        publishTags.split(whereSeparator: { " ,\n".contains($0) })
            .map { $0.hasPrefix("#") ? String($0.dropFirst()) : String($0) }
            .filter { !$0.isEmpty }
    }

    private var hashtagLine: String {
        parsedTags.map { "#\($0)" }.joined(separator: " ")
    }

    private func startPublish(outputPath: String) {
        guard let source = activeJob, source.state == "done" else { return }
        publishedURL = nil
        let title = publishTitle.trimmingCharacters(in: .whitespaces)
        let description = [publishDescription, hashtagLine]
            .filter { !$0.isEmpty }.joined(separator: "\n\n")
        let privacy = publishPrivacy
        let tags = parsedTags
        runPlanJob("YouTube publish") {
            try await engine.createPublishJob(sourceJobId: source.jobId,
                                              outputPath: outputPath,
                                              title: title,
                                              description: description,
                                              privacy: privacy,
                                              tags: tags)
        }
    }

    private var logSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Activity")
                .font(.headline)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(log.lines.enumerated()), id: \.offset) { i, line in
                            Text(line)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                                .id(i)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: 110)
                .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
                .onChange(of: log.lines.count) { _, count in
                    if count > 0 { proxy.scrollTo(count - 1, anchor: .bottom) }
                }
            }
        }
    }

    // MARK: - Actions

    private func togglePreview(path: String) {
        if let player = previewPlayer, isPreviewPlaying {
            player.pause()
            isPreviewPlaying = false
            return
        }
        if previewPlayer?.url?.path != path {
            previewPlayer = try? AVAudioPlayer(contentsOf: URL(fileURLWithPath: path))
        }
        guard let player = previewPlayer else {
            AppLog.shared.append("Could not open audio preview: \(path)")
            return
        }
        player.play()
        isPreviewPlaying = true
        AppLog.shared.append("Playing audio preview.")
    }

    private func stopPreview() {
        previewPlayer?.stop()
        previewPlayer = nil
        isPreviewPlaying = false
    }

    private func scheduleInspection() {
        inspectTask?.cancel()
        activeJob = nil
        jobError = nil
        analysisJob = nil
        analysisError = nil

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
                let guess = SongTitleParser.guess(title: meta.title, uploader: meta.uploader)
                lyricArtist = guess.artist
                lyricTitle = guess.title
                AppLog.shared.append("Metadata loaded: \(meta.title ?? "untitled") (\(meta.videoId ?? "?"))")
            } catch let error as EngineAPIError {
                guard !Task.isCancelled else { return }
                inspectState = .failed(error.errorDescription ?? "Inspection failed.")
                AppLog.shared.append("Inspection failed: \(error.errorDescription ?? "unknown error")")
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
        analysisJob = nil
        analysisError = nil
        lyricsJob = nil
        lyricsError = nil
        lyrics = nil
        editingLine = nil
        planJob = nil
        planError = nil
        plan = nil
        stopPreview()
        let url = youtubeURL.trimmingCharacters(in: .whitespacesAndNewlines)
        jobTask = Task {
            do {
                let jobId = try await engine.createJob(url: url, authorized: authorizationConfirmed)
                AppLog.shared.append("Ingestion job \(jobId.prefix(8)) started.")
                while !Task.isCancelled {
                    let status = try await engine.jobStatus(id: jobId)
                    activeJob = status
                    if status.isTerminal {
                        AppLog.shared.append("Job \(jobId.prefix(8)) \(status.state): \(status.message)")
                        break
                    }
                    try? await Task.sleep(for: .milliseconds(500))
                }
            } catch let error as EngineAPIError {
                jobError = error.errorDescription
                AppLog.shared.append("Job failed: \(error.errorDescription ?? "unknown error")")
            } catch {
                jobError = "Lost contact with the local engine: \(error.localizedDescription)"
                AppLog.shared.append("Job failed: lost contact with the engine.")
            }
            jobTask = nil
        }
    }

    private func startAnalysis() {
        guard let source = activeJob, source.state == "done" else { return }
        analysisError = nil
        analysisJob = nil
        stopPreview()
        let override = Double(startOverrideText.replacingOccurrences(of: ",", with: ".")
                                .trimmingCharacters(in: .whitespaces))
        if !startOverrideText.trimmingCharacters(in: .whitespaces).isEmpty && override == nil {
            analysisError = "Start override must be a number of seconds."
            return
        }
        analysisTask = Task {
            do {
                let jobId = try await engine.createAnalyzeJob(
                    sourceJobId: source.jobId,
                    targetSeconds: durationSeconds,
                    startOverride: override)
                AppLog.shared.append("Analysis job \(jobId.prefix(8)) started (\(durationSeconds)s).")
                while !Task.isCancelled {
                    let status = try await engine.jobStatus(id: jobId)
                    analysisJob = status
                    if status.isTerminal {
                        AppLog.shared.append("Analysis \(jobId.prefix(8)) \(status.state): \(status.message)")
                        break
                    }
                    try? await Task.sleep(for: .milliseconds(500))
                }
            } catch let error as EngineAPIError {
                analysisError = error.errorDescription
                AppLog.shared.append("Analysis failed: \(error.errorDescription ?? "unknown error")")
            } catch {
                analysisError = "Lost contact with the local engine: \(error.localizedDescription)"
            }
            analysisTask = nil
        }
    }

    private func cancelAnalysis() {
        guard let job = analysisJob, !job.isTerminal else {
            analysisTask?.cancel()
            analysisTask = nil
            return
        }
        Task {
            try? await engine.cancelJob(id: job.jobId)
        }
    }

    // MARK: - Lyrics actions

    private func runLyricsJob(_ description: String,
                              create: @escaping () async throws -> String,
                              onDone: @escaping (JobStatus) async -> Void) {
        lyricsError = nil
        lyricsJob = nil
        lyricsTask = Task {
            do {
                let jobId = try await create()
                AppLog.shared.append("\(description) job \(jobId.prefix(8)) started.")
                while !Task.isCancelled {
                    let status = try await engine.jobStatus(id: jobId)
                    lyricsJob = status
                    if status.isTerminal {
                        AppLog.shared.append("\(description) \(status.state): \(status.message)")
                        if status.state == "done" {
                            await onDone(status)
                        }
                        break
                    }
                    try? await Task.sleep(for: .milliseconds(500))
                }
            } catch let error as EngineAPIError {
                lyricsError = error.errorDescription
                AppLog.shared.append("\(description) failed: \(error.errorDescription ?? "unknown error")")
            } catch {
                lyricsError = "Lost contact with the local engine: \(error.localizedDescription)"
            }
            lyricsTask = nil
        }
    }

    private func refreshLyrics() async {
        guard let source = activeJob, source.state == "done" else { return }
        lyrics = try? await engine.fetchLyrics(sourceJobId: source.jobId)
    }

    private func startLyricsFetch() {
        guard let source = activeJob, source.state == "done" else { return }
        editingLine = nil
        runLyricsJob("Lyrics search",
                     create: {
                         try await engine.createLyricsJob(
                             sourceJobId: source.jobId,
                             artist: lyricArtist.trimmingCharacters(in: .whitespaces),
                             title: lyricTitle.trimmingCharacters(in: .whitespaces))
                     },
                     onDone: { _ in await refreshLyrics() })
    }

    private func startAlign() {
        guard let source = activeJob, source.state == "done" else { return }
        runLyricsJob("Alignment",
                     create: { try await engine.createAlignJob(sourceJobId: source.jobId) },
                     onDone: { _ in await refreshLyrics() })
    }

    private func startTranslate() {
        guard let source = activeJob, source.state == "done" else { return }
        // force: re-translate every line so each matches its own lyric
        // (repeated lines get identical, correct translations — fixes any
        // drift from imported/hand-pasted translations)
        runLyricsJob("Turkish translation",
                     create: { try await engine.createTranslateJob(
                         sourceJobId: source.jobId, force: true) },
                     onDone: { _ in await refreshLyrics() })
    }

    private func startSubtitlePreview() {
        guard let source = activeJob, source.state == "done" else { return }
        let segmentStart = analysisJob?.result?.segmentStart ?? 0
        runLyricsJob("Subtitle preview (\(previewStyle))",
                     create: {
                         try await engine.createSubtitlePreviewJob(
                             sourceJobId: source.jobId,
                             style: previewStyle,
                             segmentStart: segmentStart,
                             targetSeconds: durationSeconds)
                     },
                     onDone: { _ in })
    }

    private func cancelLyricsJob() {
        guard let job = lyricsJob, !job.isTerminal else {
            lyricsTask?.cancel()
            lyricsTask = nil
            return
        }
        Task {
            try? await engine.cancelJob(id: job.jobId)
        }
    }

    private func beginEditing(_ line: LyricLinePayload) {
        editingLine = line.lineIndex
        correctionDraft = line.correctedText ?? line.text
        translationDraft = line.translation ?? ""
    }

    private func saveLineEdit(_ lineIndex: Int) {
        guard let source = activeJob, source.state == "done" else { return }
        let original = lyrics?.lines.first(where: { $0.lineIndex == lineIndex })?.text
        let correction = correctionDraft.trimmingCharacters(in: .whitespaces)
        Task {
            do {
                _ = try await engine.updateLyricLine(
                    sourceJobId: source.jobId,
                    lineIndex: lineIndex,
                    correctedText: correction == original ? "" : correction,
                    translation: translationDraft.trimmingCharacters(in: .whitespaces))
                editingLine = nil
                await refreshLyrics()
                AppLog.shared.append("Lyric line \(lineIndex + 1) saved.")
            } catch {
                lyricsError = "Could not save the line: \(error.localizedDescription)"
            }
        }
    }

    // MARK: - Plan & media actions

    private func loadKeysOnce() {
        guard !keysLoaded else { return }
        keysLoaded = true
        pexelsKey = KeychainStore.get(account: "pexels_api_key") ?? ""
        pixabayKey = KeychainStore.get(account: "pixabay_api_key") ?? ""
        unsplashKey = KeychainStore.get(account: "unsplash_api_key") ?? ""
    }

    private func runPlanJob(_ description: String,
                            create: @escaping () async throws -> String) {
        planError = nil
        planJob = nil
        planTask = Task {
            do {
                let jobId = try await create()
                AppLog.shared.append("\(description) job \(jobId.prefix(8)) started.")
                while !Task.isCancelled {
                    let status = try await engine.jobStatus(id: jobId)
                    planJob = status
                    if status.isTerminal {
                        AppLog.shared.append("\(description) \(status.state): \(status.message)")
                        if status.state == "done", let source = activeJob {
                            plan = try? await engine.fetchPlan(sourceJobId: source.jobId)
                        }
                        if status.state == "done",
                           let url = status.result?.videoUrl {
                            publishedURL = url
                        }
                        break
                    }
                    try? await Task.sleep(for: .milliseconds(500))
                }
            } catch let error as EngineAPIError {
                planError = error.errorDescription
                AppLog.shared.append("\(description) failed: \(error.errorDescription ?? "unknown error")")
            } catch {
                planError = "Lost contact with the local engine: \(error.localizedDescription)"
            }
            planTask = nil
        }
    }

    private func startPlan() {
        guard let source = activeJob, source.state == "done" else { return }
        let segmentStart = analysisJob?.result?.segmentStart ?? 0
        let theme = planTheme.trimmingCharacters(in: .whitespaces)
        runPlanJob("Scene plan") {
            try await engine.createPlanJob(sourceJobId: source.jobId,
                                           style: planStyle,
                                           segmentStart: segmentStart,
                                           targetSeconds: durationSeconds,
                                           theme: theme,
                                           artStyle: artStyle,
                                           instrumental: instrumentalMode)
        }
    }

    private var providerKeys: [String: String] {
        var keys: [String: String] = [:]
        let pexels = pexelsKey.trimmingCharacters(in: .whitespaces)
        let pixabay = pixabayKey.trimmingCharacters(in: .whitespaces)
        let unsplash = unsplashKey.trimmingCharacters(in: .whitespaces)
        if !pexels.isEmpty { keys["pexels"] = pexels }
        if !pixabay.isEmpty { keys["pixabay"] = pixabay }
        if !unsplash.isEmpty { keys["unsplash"] = unsplash }
        return keys
    }

    private func startMediaFetch(regenerate: Bool = false) {
        guard let source = activeJob, source.state == "done" else { return }
        let keys = providerKeys
        runPlanJob(regenerate ? "Media regenerate" : "Media fetch") {
            try await engine.createMediaJob(sourceJobId: source.jobId,
                                            apiKeys: keys,
                                            regenerate: regenerate,
                                            artStyle: artStyle,
                                            aiImages: aiImages)
        }
    }

    private func excludeAsset(provider: String, ref: String) {
        guard let source = activeJob, source.state == "done" else { return }
        let keys = providerKeys
        runPlanJob("Replace excluded media") {
            try await engine.createMediaJob(sourceJobId: source.jobId,
                                            apiKeys: keys,
                                            artStyle: artStyle,
                                            aiImages: aiImages,
                                            exclude: [(provider, ref)])
        }
    }

    private func startRender() {
        guard let source = activeJob, source.state == "done" else { return }
        let style = plan?.style ?? "archiveCollage"
        runPlanJob("Render (\(style))") {
            try await engine.createRenderJob(sourceJobId: source.jobId,
                                             style: style,
                                             motionEffects: motionEffects,
                                             syncOffset: syncOffset)
        }
    }

    private func cancelPlanJob() {
        guard let job = planJob, !job.isTerminal else {
            planTask?.cancel()
            planTask = nil
            return
        }
        Task {
            try? await engine.cancelJob(id: job.jobId)
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
