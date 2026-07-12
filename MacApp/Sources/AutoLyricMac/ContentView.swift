import SwiftUI

struct ContentView: View {
    @StateObject private var engine = EngineClient()
    @State private var youtubeURL: String = ""
    @State private var durationSeconds: Int = 30

    private let durations = [30, 45, 60]

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            // Title + engine status
            HStack {
                Text("AutoLyricMac")
                    .font(.largeTitle.bold())
                Spacer()
                engineStatusBadge
            }

            // YouTube URL input
            VStack(alignment: .leading, spacing: 6) {
                Text("YouTube URL")
                    .font(.headline)
                TextField("https://www.youtube.com/watch?v=…", text: $youtubeURL)
                    .textFieldStyle(.roundedBorder)
            }

            // Duration picker
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

            // Create button (disabled in step 1)
            Button("Create Video") {}
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(true)

            Divider()

            // Placeholder progress area
            VStack(alignment: .leading, spacing: 8) {
                Text("Progress")
                    .font(.headline)
                ProgressView(value: 0)
                Text("Waiting — video creation is not implemented yet.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Spacer()
        }
        .padding(24)
        .onAppear { engine.startPolling() }
    }

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
    }

    private var statusText: String {
        switch engine.status {
        case .unknown: return "Checking Engine…"
        case .connected: return "Engine Connected"
        case .offline: return "Engine Offline"
        }
    }

    private var statusColor: Color {
        switch engine.status {
        case .unknown: return .gray
        case .connected: return .green
        case .offline: return .red
        }
    }
}

#Preview {
    ContentView()
}
