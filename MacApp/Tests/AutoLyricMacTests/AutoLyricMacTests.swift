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

    func testLyricsJobResultParsing() throws {
        let json = """
        {"job_id": "abc", "kind": "align", "state": "done", "progress": 1.0,
         "message": "Alignment done", "error_code": null, "audio_path": null,
         "audio_duration": null, "audio_format": null,
         "result": {"matched_ratio": 0.83, "mean_confidence": 0.81,
                    "uncertain_lines": 1, "suspect": false,
                    "asr_word_count": 25}}
        """
        let status = try decoder.decode(JobStatus.self, from: Data(json.utf8))
        XCTAssertEqual(status.result?.matchedRatio, 0.83)
        XCTAssertEqual(status.result?.uncertainLines, 1)
        XCTAssertEqual(status.result?.suspect, false)
        XCTAssertNil(status.result?.tempoBpm)
    }

    func testLyricsPayloadParsing() throws {
        let json = """
        {"job_id": "deadbeef", "provider": "lrclib", "artist": "A", "title": "T",
         "album": null, "synced": true, "score": 0.9, "aligned": true,
         "matched_ratio": 0.83, "mean_confidence": 0.81, "suspect": false,
         "lines": [
           {"line_index": 0, "text": "Hold me close", "corrected_text": null,
            "display_text": "Hold me close", "translation": "Beni tut",
            "start": 1.5, "end": 3.4, "confidence": 0.97, "uncertain": false,
            "words": [{"text": "Hold", "start": 1.5, "end": 1.8,
                       "confidence": 0.99}]},
           {"line_index": 1, "text": "Never sung", "corrected_text": "Fixed",
            "display_text": "Fixed", "translation": null, "start": null,
            "end": null, "confidence": 0.0, "uncertain": true, "words": []}
         ]}
        """
        let payload = try decoder.decode(LyricsPayload.self, from: Data(json.utf8))
        XCTAssertTrue(payload.aligned)
        XCTAssertFalse(payload.suspect)
        XCTAssertEqual(payload.lines.count, 2)
        XCTAssertEqual(payload.lines[0].words.first?.text, "Hold")
        XCTAssertEqual(payload.lines[1].displayText, "Fixed")
        XCTAssertTrue(payload.lines[1].uncertain)
        XCTAssertNil(payload.lines[1].start)
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
        XCTAssertEqual(status.result?.reasons?.count, 2)
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

final class PlanPayloadTests: XCTestCase {
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    func testPlanParsingWithAndWithoutMedia() throws {
        let json = """
        {"style": "doodleMemory", "recommended_style": "doodleMemory",
         "recommendation_confidence": 0.65,
         "recommendation_reason": "warm emotions dominate",
         "segment_start": 0.0, "segment_end": 18.0,
         "scene_count": 2, "lyric_scene_count": 1,
         "scenes": [
           {"scene_index": 0, "start": 0.0, "end": 6.0, "duration": 6.0,
            "target_duration": [3.0, 5.0], "lyric": "Hold me close",
            "translation": null, "uncertain": false,
            "meaning": "love moment", "emotion": "love", "energy": 0.5,
            "energy_band": "normal", "subjects": ["embrace"],
            "queries": ["tight embrace couple"], "media_preference": "photo",
            "motion": {"type": "breathe", "amount": 0.05, "pulse_beats": [0.5]},
            "transition": {"type": "cut", "duration": 0.0},
            "overlays": ["warm_grain"],
            "subtitle": {"band": "lower", "seed": 0},
            "media": {"provider": "pexels", "provider_ref": "9",
                      "kind": "photo", "width": 2000, "height": 3200,
                      "page_url": "https://example.com", "creator": "Ada",
                      "license": "Pexels License", "query": "embrace",
                      "file_path": "/tmp/x.jpg",
                      "adaptation": {"strategy": "portrait_crop",
                                     "reason": "portrait source"}}},
           {"scene_index": 1, "start": 6.0, "end": 12.0, "duration": 6.0,
            "target_duration": [3.0, 5.0], "lyric": null, "translation": null,
            "uncertain": false, "meaning": "neutral instrumental passage",
            "emotion": "neutral", "energy": 0.3, "energy_band": "calm",
            "subjects": [], "queries": ["soft abstract light texture"],
            "media_preference": "photo",
            "motion": {"type": "slide_in", "amount": 0.04, "pulse_beats": []},
            "transition": {"type": "paper_wipe", "duration": 0.3},
            "overlays": ["warm_grain"],
            "subtitle": {"band": "center", "seed": 1},
            "media": null}
         ]}
        """
        let plan = try decoder.decode(PlanPayload.self, from: Data(json.utf8))
        XCTAssertEqual(plan.sceneCount, 2)
        XCTAssertEqual(plan.scenes[0].media?.provider, "pexels")
        XCTAssertEqual(plan.scenes[0].media?.adaptation?.strategy, "portrait_crop")
        XCTAssertNil(plan.scenes[1].media)
        XCTAssertNil(plan.scenes[1].lyric)
        XCTAssertEqual(plan.scenes[1].emotion, "neutral")
    }

    func testMediaJobResultParsing() throws {
        let json = """
        {"job_id": "abc", "kind": "media", "state": "done", "progress": 1.0,
         "message": "Media ready", "error_code": null, "audio_path": null,
         "audio_duration": null, "audio_format": null,
         "result": {"fetched_count": 4, "scene_count": 5,
                    "provider_errors": ["pixabay: key rejected"],
                    "scene_errors": []}}
        """
        let status = try decoder.decode(JobStatus.self, from: Data(json.utf8))
        XCTAssertEqual(status.result?.fetchedCount, 4)
        XCTAssertEqual(status.result?.providerErrors?.count, 1)
    }
}

final class KeychainStoreTests: XCTestCase {
    private let account = "test_key_roundtrip"

    override func tearDown() {
        KeychainStore.set("", account: account)
        super.tearDown()
    }

    func testRoundtripUpdateAndClear() {
        XCTAssertTrue(KeychainStore.set("secret-1", account: account))
        XCTAssertEqual(KeychainStore.get(account: account), "secret-1")
        XCTAssertTrue(KeychainStore.set("secret-2", account: account))
        XCTAssertEqual(KeychainStore.get(account: account), "secret-2")
        XCTAssertTrue(KeychainStore.set("", account: account))
        XCTAssertNil(KeychainStore.get(account: account))
    }
}

final class SongTitleParserTests: XCTestCase {
    func testArtistDashTitle() {
        let g = SongTitleParser.guess(title: "Sezen Aksu - Gidiyorum (Official Video)",
                                      uploader: "SomeChannel")
        XCTAssertEqual(g.artist, "Sezen Aksu")
        XCTAssertEqual(g.title, "Gidiyorum (Official Video)")
    }

    func testFallsBackToUploader() {
        let g = SongTitleParser.guess(title: "Gidiyorum", uploader: "Sezen Aksu - Topic")
        XCTAssertEqual(g.artist, "Sezen Aksu")
        XCTAssertEqual(g.title, "Gidiyorum")
    }

    func testEnDashSeparator() {
        let g = SongTitleParser.guess(title: "Artist – Song", uploader: nil)
        XCTAssertEqual(g.artist, "Artist")
        XCTAssertEqual(g.title, "Song")
    }

    func testEmptyInputs() {
        let g = SongTitleParser.guess(title: nil, uploader: nil)
        XCTAssertEqual(g.artist, "")
        XCTAssertEqual(g.title, "")
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
