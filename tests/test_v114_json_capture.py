from zeroreels import v114_json_capture as capture


def test_extract_json_from_unstructured_visible_page_text():
    body = '''
    ChatGPT\nNew chat\nYou said:\nwrite something\n
    {"title":"What's Behind Area 51?","scenes":[{"narration":"Spy planes, not aliens."},{"narration":"The base stayed secret."}]}
    Copy\nGood response\n
    '''
    values = capture._extract_json_dicts(body)
    assert any(value.get("title") == "What's Behind Area 51?" for value in values)


def test_json_first_capture_works_when_no_message_turns_are_detected():
    # Mirrors the v0.11.3 field failure: ChatGPT visibly rendered JSON but the app's
    # conversation-turn selector returned zero messages.
    prompt = '''Write a reel. Return ONLY valid JSON in this shape:
    {"title":"...","scenes":[{"narration":"..."}]}
    Return exactly 2 scene objects.'''
    response = {
        "title": "What's Behind Area 51?",
        "scenes": [
            {"narration": "Area 51 was built for secrets.", "image_prompt": "desert base"},
            {"narration": "Its proven history is secret aviation.", "image_prompt": "runway"},
        ],
    }
    body = prompt + "\nChatGPT\n" + __import__("json").dumps(response) + "\nCopy"
    selected = capture._select_new_json(body, set(), prompt)
    assert selected == response


def test_prompt_schema_example_cannot_be_mistaken_for_answer():
    prompt = '''Return ONLY valid JSON: {"scenes":[{"narration":"..."}]} with exactly 3 scene objects.'''
    body = "You said: " + prompt
    assert capture._select_new_json(body, set(), prompt) is None


def test_expected_scene_count_rejects_partial_streamed_json():
    prompt = "Return exactly 3 scene objects in JSON with a \"scenes\" array."
    partial_but_valid = '{"scenes":[{"narration":"one"},{"narration":"two"}]}'
    assert capture._select_new_json(partial_but_valid, set(), prompt) is None


def test_conversation_mapping_extracts_latest_assistant_text():
    data = {
        "mapping": {
            "u": {
                "message": {
                    "author": {"role": "user"},
                    "create_time": 1,
                    "content": {"parts": ["prompt"]},
                }
            },
            "a1": {
                "message": {
                    "author": {"role": "assistant"},
                    "create_time": 2,
                    "content": {"parts": ['{"scenes":[{"narration":"first"}]}']},
                }
            },
            "a2": {
                "message": {
                    "author": {"role": "assistant"},
                    "create_time": 3,
                    "content": {"parts": ['{"scenes":[{"narration":"second"}]}']},
                }
            },
        }
    }
    texts = capture._assistant_texts_from_conversation(data)
    assert texts == [
        '{"scenes":[{"narration":"first"}]}',
        '{"scenes":[{"narration":"second"}]}',
    ]


def test_body_json_baseline_is_ignored():
    old = {"scenes": [{"narration": "old"}]}
    new = {"scenes": [{"narration": "new"}]}
    import json

    baseline = {capture._fingerprint(old)}
    body = json.dumps(old) + "\n" + json.dumps(new)
    selected = capture._select_new_json(body, baseline, 'Return JSON with a "scenes" array.')
    assert selected == new
