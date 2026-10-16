from __future__ import annotations

from zeroreels import browser_ai
from zeroreels import v113_chatgpt_response as response


AREA51_JSON = '''{"title":"What’s Behind Area 51?","scenes":[{"narration":"Area 51 was built for secrets—but the real story starts with spy planes, not aliens.","image_prompt":"Cinematic aerial view of a remote desert airbase beside a dry lakebed","broll_query":"Area 51 desert aerial","shot_role":"Hook"}]}'''


def _baseline(*turns):
    return {
        "turns": list(turns),
        "keys": {turn["key"] for turn in turns},
        "texts": {response._norm(turn["text"]) for turn in turns},
    }


def test_generic_modern_conversation_turn_detects_json_reply():
    prompt = "Write the complete narration and visual plan for a high-retention short-form video. TOPIC: What's Behind Area 51?"
    baseline = _baseline()
    turns = [
        {"key": "conversation-turn-0", "role": "", "text": prompt},
        {"key": "conversation-turn-1", "role": "", "text": AREA51_JSON},
    ]
    chosen = response._select_reply_candidate(turns, baseline, prompt)
    assert chosen is not None
    assert chosen["key"] == "conversation-turn-1"
    parsed = browser_ai._extract_json_object(chosen["text"])
    assert parsed["title"] == "What’s Behind Area 51?"
    assert parsed["scenes"][0]["shot_role"] == "Hook"


def test_user_prompt_turn_is_not_mistaken_for_assistant_reply():
    prompt = "Write a 60 second story about Area 51 with twelve visual beats and return only JSON."
    turns = [{"key": "turn-user", "role": "", "text": prompt}]
    assert response._select_reply_candidate(turns, _baseline(), prompt) is None


def test_collapsed_user_prompt_prefix_is_recognized():
    prompt = (
        "Write the complete narration and visual plan for a high-retention short-form video. "
        "TOPIC: Area 51. Return exactly twelve scene objects with narration and image prompts."
    )
    collapsed = "Write the complete narration and visual plan for a high-retention short-form video. TOPIC: Area 51."
    assert response._looks_like_prompt(collapsed, prompt)


def test_explicit_assistant_role_wins_over_generic_new_turn():
    prompt = "Return JSON about Area 51."
    turns = [
        {"key": "generic", "role": "", "text": "Some unrelated shell text that appeared after send."},
        {"key": "assistant", "role": "assistant", "text": AREA51_JSON},
    ]
    chosen = response._select_reply_candidate(turns, _baseline(), prompt)
    assert chosen is not None
    assert chosen["key"] == "assistant"


def test_existing_turn_is_not_reported_as_new_reply():
    old = {"key": "conversation-turn-7", "role": "assistant", "text": AREA51_JSON}
    assert response._select_reply_candidate([old], _baseline(old), "another prompt") is None
