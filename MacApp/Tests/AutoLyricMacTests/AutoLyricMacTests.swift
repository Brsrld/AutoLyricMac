import XCTest
@testable import AutoLyricMac

final class YouTubeURLValidatorTests: XCTestCase {
    func testWatchURL() {
        XCTAssertEqual(YouTubeURLValidator.videoID(from: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                       "dQw4w9WgXcQ")
    }

    func testShortLink() {
        XCTAssertEqual(YouTubeURLValidator.videoID(from: "https://youtu.be/dQw4w9WgXcQ"),
                       "dQw4w9WgXcQ")
    }

    func testShorts() {
        XCTAssertEqual(YouTubeURLValidator.videoID(from: "https://www.youtube.com/shorts/dQw4w9WgXcQ"),
                       "dQw4w9WgXcQ")
    }

    func testMusicDomain() {
        XCTAssertEqual(YouTubeURLValidator.videoID(from: "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=x"),
                       "dQw4w9WgXcQ")
    }

    func testWhitespaceTrimmed() {
        XCTAssertEqual(YouTubeURLValidator.videoID(from: "  https://youtu.be/dQw4w9WgXcQ \n"),
                       "dQw4w9WgXcQ")
    }

    func testInvalidInputs() {
        let bad = [
            "",
            "not a url",
            "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://example.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch",
            "https://youtu.be/",
            "https://evilyoutube.com/watch?v=dQw4w9WgXcQ",
        ]
        for input in bad {
            XCTAssertNil(YouTubeURLValidator.videoID(from: input), "should reject: \(input)")
        }
    }
}

final class MetadataParsingTests: XCTestCase {
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    func testFullMetadata() throws {
        let json = """
        {"valid": true, "video_id": "dQw4w9WgXcQ", "title": "Song",
         "uploader": "Artist", "duration": 212,
         "thumbnail_url": "https://i.ytimg.com/x.jpg",
         "original_url": "https://youtu.be/dQw4w9WgXcQ"}
        """
        let meta = try decoder.decode(SourceMetadata.self, from: Data(json.utf8))
        XCTAssertTrue(meta.valid)
        XCTAssertEqual(meta.videoId, "dQw4w9WgXcQ")
        XCTAssertEqual(meta.title, "Song")
        XCTAssertEqual(meta.uploader, "Artist")
        XCTAssertEqual(meta.duration, 212)
        XCTAssertEqual(meta.thumbnailUrl, "https://i.ytimg.com/x.jpg")
    }

    func testMissingOptionalFields() throws {
        let json = """
        {"valid": true, "video_id": null, "title": null, "uploader": null,
         "duration": null, "thumbnail_url": null, "original_url": null}
        """
        let meta = try decoder.decode(SourceMetadata.self, from: Data(json.utf8))
        XCTAssertTrue(meta.valid)
        XCTAssertNil(meta.title)
        XCTAssertNil(meta.duration)
    }

    func testJobStatusParsing() throws {
        let json = """
        {"job_id": "abc", "state": "done", "progress": 1.0,
         "message": "Audio ready (aac, 212.0s).", "error_code": null,
         "audio_path": "/tmp/audio.m4a", "audio_duration": 212.0,
         "audio_format": "aac"}
        """
        let status = try decoder.decode(JobStatus.self, from: Data(json.utf8))
        XCTAssertEqual(status.state, "done")
        XCTAssertTrue(status.isTerminal)
        XCTAssertEqual(status.audioDuration, 212.0)
    }

    func testAnalysisJobParsing() throws {
        let json = """
        {"job_id": "abc", "kind": "analyze", "state": "done", "progress": 1.0,
         "message": "Segment ready", "error_code": null,
         "audio_path": "/tmp/segment_45s.m4a", "audio_duration": 45.0,
         "audio_format": "aac",
         "result": {"tempo_bpm": 136.0, "track_duration": 634.6,
                    "beat_count": 1378, "section_count": 12,
                    "segment_start": 484.3, "segment_end": 529.3,
                    "score": 0.67, "reasons": ["r1", "r2"]}}
        """
        let status = try decoder.decode(JobStatus.self, from: Data(json.utf8))
        XCTAssertEqual(status.kind, "analyze")
        XCTAssertEqual(status.result?.tempoBpm, 136.0)
        XCTAssertEqual(status.result?.reasons.count, 2)
        XCTAssertEqual(status.result?.segmentStart, 484.3)
    }

    func testDownloadJobParsesWithoutResult() throws {
        let json = """
        {"job_id": "abc", "state": "downloading", "progress": 0.4,
         "message": "Downloading", "error_code": null, "audio_path": null,
         "audio_duration": null, "audio_format": null}
        """
        let status = try decoder.decode(JobStatus.self, from: Data(json.utf8))
        XCTAssertNil(status.result)
        XCTAssertNil(status.kind)
        XCTAssertFalse(status.isTerminal)
    }

    func testErrorPayloadParsing() throws {
        let json = """
        {"error_code": "restricted", "message": "This video is age-restricted."}
        """
        let error = try decoder.decode(EngineAPIError.self, from: Data(json.utf8))
        XCTAssertEqual(error.errorCode, "restricted")
        XCTAssertEqual(error.errorDescription, "This video is age-restricted.")
    }
}

final class EngineStartPolicyTests: XCTestCase {
    func testAllowsExactlyTwoAttempts() {
        var policy = EngineStartPolicy(maxAttempts: 2)
        XCTAssertTrue(policy.beginAttempt(), "first launch attempt allowed")
        XCTAssertTrue(policy.beginAttempt(), "one restart allowed")
        XCTAssertFalse(policy.beginAttempt(), "no third attempt")
    }

    func testResetRestoresAttempts() {
        var policy = EngineStartPolicy(maxAttempts: 2)
        _ = policy.beginAttempt()
        _ = policy.beginAttempt()
        policy.reset()
        XCTAssertTrue(policy.beginAttempt())
    }
}
