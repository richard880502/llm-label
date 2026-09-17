from unittest.mock import Mock, patch

from backend.assistant.openclaw import _output_text, send_to_openclaw


def test_output_text_collects_assistant_message_parts():
    payload = {
        "output": [
            {"type": "reasoning", "content": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "第一段"},
                    {"type": "output_text", "text": "第二段"},
                ],
            },
        ]
    }
    assert _output_text(payload) == "第一段\n第二段"


@patch("backend.assistant.openclaw.httpx.post")
def test_send_to_openclaw_uses_stable_user_and_previous_response(mock_post):
    response = Mock()
    response.json.return_value = {
        "id": "resp_2",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "完成"}]}],
    }
    response.raise_for_status.return_value = None
    mock_post.return_value = response

    text, response_id = send_to_openclaw(
        conversation_key="llm-label:3:alice",
        message="目前進度？",
        instructions="project context",
        previous_response_id="resp_1",
    )

    assert (text, response_id) == ("完成", "resp_2")
    body = mock_post.call_args.kwargs["json"]
    assert body["user"] == "llm-label:3:alice"
    assert body["previous_response_id"] == "resp_1"
    assert body["instructions"] == "project context"
