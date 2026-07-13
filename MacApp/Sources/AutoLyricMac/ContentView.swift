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

    // Scene plan & media (Phase 4)
    @State private var planStyle: String = "automatic"
    @State private var planJob: JobStatus?
    @State private var planTask: Task<Void, Never>?
    @State private var planError: String?
    @State private var plan: PlanPayload?
    @State private var pexelsKey: String = ""
    @State private var pixabayKey: String = ""
    @State private var unsplashKey: String = ""
    @State private var keysLoaded = false

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

                if activeJob?.state == "done" {
                    Divider()
                    segmentSection
                    Divider()
                    lyricsSection
                    if lyrics?.aligned == true {
                        Divider()
                        planSection
                    }
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
                Button("Align Words") { startAlign() }
                    .disabled(engine.status != .connected || lyricsJobRunning || lyrics == nil)
                if lyricsJobRunning {
                    Button("Cancel", role: .cancel) { cancelLyricsJob() }
                }
            }

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

    private var planHasMedia: Bool {
        plan?.scenes.contains(where: { $0.media != nil }) == true
    }

    private var planSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Scene Plan & Media")
                .font(.headline)

            HStack(spacing: 12) {
                Picker("Plan style", selection: $planStyle) {
                    Text("Automatic").tag("automatic")
                    Text("Archive Collage").tag("archiveCollage")
                    Text("Doodle Memory").tag("doodleMemory")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 380)
                Button("Build Scene Plan") { startPlan() }
                    .disabled(engine.status != .connected || planJobRunning
                              || analysisJob?.state != "done")
                Button("Fetch Licensed Media") { startMediaFetch() }
                    .disabled(engine.status != .connected || planJobRunning
                              || plan == nil || !anyProviderKey)
                Button("Render Video") { startRender() }
                    .buttonStyle(.borderedProminent)
                    .disabled(engine.status != .connected || planJobRunning
                              || planHasMedia == false)
                if planJobRunning {
                    Button("Cancel", role: .cancel) { cancelPlanJob() }
                }
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

            if planJob?.kind == "render", planJob?.state == "done",
               let path = planJob?.result?.outputPath {
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
            HStack(spacing: 8) {
                Text("search: \(scene.queries.first ?? "—")")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                if let media = scene.media {
                    Label("\(media.provider) · \(media.creator ?? "?") · \(media.license ?? "?")\(media.adaptation.map { " · \($0.strategy)" } ?? "")",
                          systemImage: "photo")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.leading, 94)
        }
        .padding(.vertical, 2)
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
        runPlanJob("Scene plan") {
            try await engine.createPlanJob(sourceJobId: source.jobId,
                                           style: planStyle,
                                           segmentStart: segmentStart,
                                           targetSeconds: durationSeconds)
        }
    }

    private func startMediaFetch() {
        guard let source = activeJob, source.state == "done" else { return }
        var keys: [String: String] = [:]
        let pexels = pexelsKey.trimmingCharacters(in: .whitespaces)
        let pixabay = pixabayKey.trimmingCharacters(in: .whitespaces)
        let unsplash = unsplashKey.trimmingCharacters(in: .whitespaces)
        if !pexels.isEmpty { keys["pexels"] = pexels }
        if !pixabay.isEmpty { keys["pixabay"] = pixabay }
        if !unsplash.isEmpty { keys["unsplash"] = unsplash }
        runPlanJob("Media fetch") {
            try await engine.createMediaJob(sourceJobId: source.jobId,
                                            apiKeys: keys)
        }
    }

    private func startRender() {
        guard let source = activeJob, source.state == "done" else { return }
        runPlanJob("Render") {
            try await engine.createRenderJob(sourceJobId: source.jobId,
                                             style: "archiveCollage")
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
