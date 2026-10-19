"""Pure helpers in voice_id (upgrade-list section on stale voiceprints).

These exercise the parts that previously raised on a backend change: comparing
embeddings of different lengths, and handing out unique unknown-voice ids.
Importing voice_id must stay cheap - it pulls in numpy only.
"""

import numpy as np

from voice_id import _best_match, _cosine_similarity, _next_unknown_id


# --- unique ids for unrecognised voices --------------------------------------

def test_first_unknown_id_is_one():
    assert _next_unknown_id({}) == "UNK-001"


def test_next_unknown_id_counts_up():
    assert _next_unknown_id({"UNK-001": {}, "UNK-002": {}}) == "UNK-003"


def test_next_unknown_id_fills_gaps_left_by_naming():
    # assign_name_to_unknown() frees an id; reusing it prevents overwrites.
    assert _next_unknown_id({"UNK-002": {}, "UNK-003": {}}) == "UNK-001"


def test_next_unknown_id_ignores_unrelated_keys():
    assert _next_unknown_id({"Mahesh": {}, "UNK-005": {}}) == "UNK-001"


# --- best match across (possibly stale) voiceprints ---------------------------

def test_best_match_picks_the_closest_voice():
    query = np.array([1.0, 0.0, 0.0])
    candidates = {
        "same":     {"embedding": [1.0, 0.0, 0.0]},
        "different": {"embedding": [0.0, 1.0, 0.0]},
    }
    name, score = _best_match(query, candidates)
    assert name == "same"
    assert score > 0.99


def test_best_match_skips_a_mismatched_embedding_instead_of_raising():
    query = np.zeros(256)                       # resemblyzer
    candidates = {"legacy": {"embedding": [0.1] * 192}}   # old speechbrain print
    assert _best_match(query, candidates) == (None, 0.0)


def test_best_match_ignores_empty_embeddings():
    assert _best_match(np.zeros(4), {"x": {"embedding": []}}) == (None, 0.0)


def test_best_match_with_no_candidates():
    assert _best_match(np.zeros(4), {}) == (None, 0.0)


def test_a_mismatched_print_does_not_mask_a_good_one():
    query = np.array([1.0, 0.0, 0.0])
    candidates = {
        "stale": {"embedding": [0.1] * 192},
        "good":  {"embedding": [1.0, 0.0, 0.0]},
    }
    name, score = _best_match(query, candidates)
    assert name == "good" and score > 0.99


# --- similarity ---------------------------------------------------------------

def test_cosine_of_identical_vectors_is_one():
    vec = np.array([0.3, 0.4, 0.5])
    assert _cosine_similarity(vec, vec) > 0.99


def test_cosine_of_orthogonal_vectors_is_zero():
    assert abs(_cosine_similarity(np.array([1.0, 0.0]), np.array([0.0, 1.0]))) < 1e-6
