from jarvis.thinking import ThinkSplitter


def run(chunks: list[str]) -> tuple[str, str]:
    splitter = ThinkSplitter()
    answer, thought = "", ""
    for chunk in chunks:
        a, t = splitter.feed(chunk)
        answer += a
        thought += t
    a, t = splitter.flush()
    return answer + a, thought + t


def test_plain_text_passes_through():
    assert run(["Hello ", "world"]) == ("Hello world", "")


def test_think_block_is_split_out():
    answer, thought = run(["<think>reasoning here</think>", "\n\nThe answer."])
    assert answer == "The answer."
    assert thought == "reasoning here"


def test_tag_split_across_chunks_is_never_leaked():
    answer, thought = run(["<th", "ink>hid", "den</thi", "nk>visible"])
    assert answer == "visible"
    assert thought == "hidden"
    assert "<" not in answer


def test_unterminated_think_block_is_all_reasoning():
    answer, thought = run(["<think>still thinking when the stream died"])
    assert answer == ""
    assert thought == "still thinking when the stream died"


def test_text_before_and_after_a_block():
    answer, thought = run(["before <think>mid</think> after"])
    assert answer == "before  after"
    assert thought == "mid"
