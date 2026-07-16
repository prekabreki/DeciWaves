from deciwaves.games.hzd.binding import build_buckets, structural_binds, relevant_buckets

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

def test_ambiguous_bucket_is_relevant():
    relevant = relevant_buckets(build_buckets(LINES, CLIPS))
    assert len(relevant) == 1                    # only the (200,1060) bucket is ambiguous
    grp = relevant[0]
    assert {c["clip_row"] for c in grp["clips"]} == {1, 2}
    assert {l["line_id"] for l in grp["lines"]} == {"L2", "L3"}


def test_relevant_buckets_story_filter_excludes_nonstory_buckets():
    """With a keep_line predicate, only buckets containing a kept (story) line are
    returned; collision buckets made purely of non-story lines are skipped."""
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
    relevant = relevant_buckets(build_buckets(lines, clips), keep_line=lambda lid: lid in story)
    assert len(relevant) == 1        # only the story (200,1060) bucket; (300,1590) skipped
    assert {c["clip_row"] for c in relevant[0]["clips"]} == {0, 1}
