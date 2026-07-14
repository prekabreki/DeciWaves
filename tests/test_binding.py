from deciwaves.games.hzd.binding import build_buckets, structural_binds, asr_worklist

LINES = [{"line_id": "L1", "a_bytes": 100, "b_samples": 530, "subtitle_en": "Hi"},
         {"line_id": "L2", "a_bytes": 200, "b_samples": 1060, "subtitle_en": "A"},
         {"line_id": "L3", "a_bytes": 200, "b_samples": 1060, "subtitle_en": "B"}]
CLIPS = [{"clip_row": 0, "a_bytes": 100, "b_samples": 530},
         {"clip_row": 1, "a_bytes": 200, "b_samples": 1060},
         {"clip_row": 2, "a_bytes": 200, "b_samples": 1060}]

def test_unique_bucket_binds_structurally():
    binds = structural_binds(build_buckets(LINES, CLIPS))
    assert ("L1", 0, "S") in binds
    assert len(binds) == 1                      # only the (100,530) bucket is 1:1

def test_ambiguous_bucket_goes_to_asr():
    work = asr_worklist(build_buckets(LINES, CLIPS))
    rows = {clip_row for clip_row, _ in work}
    assert rows == {1, 2}                        # both (200,1060) clips need ASR
    _, cands = work[0]
    assert {c["line_id"] for c in cands} == {"L2", "L3"}


def test_asr_worklist_story_filter_excludes_nonstory_buckets():
    """With a keep_line predicate, only buckets containing a kept (story) line are
    transcribed; collision buckets made purely of non-story lines are skipped."""
    lines = [
        {"line_id": "S1", "a_bytes": 200, "b_samples": 1060, "subtitle_en": "story"},
        {"line_id": "S2", "a_bytes": 200, "b_samples": 1060, "subtitle_en": "story2"},
        {"line_id": "N1", "a_bytes": 300, "b_samples": 1590, "subtitle_en": ""},
        {"line_id": "N2", "a_bytes": 300, "b_samples": 1590, "subtitle_en": ""},
    ]
    clips = [
        {"clip_row": 0, "a_bytes": 200, "b_samples": 1060},
        {"clip_row": 1, "a_bytes": 200, "b_samples": 1060},
        {"clip_row": 2, "a_bytes": 300, "b_samples": 1590},
        {"clip_row": 3, "a_bytes": 300, "b_samples": 1590},
    ]
    story = {"S1", "S2"}
    work = asr_worklist(build_buckets(lines, clips), keep_line=lambda lid: lid in story)
    rows = {cr for cr, _ in work}
    assert rows == {0, 1}        # only the story (200,1060) bucket; (300,1590) skipped
