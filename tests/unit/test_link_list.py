from vidgrab.core.downloader import parse_link_list


def test_one_link_per_line_in_order_without_repeats():
    text = "https://youtu.be/a\nhttps://youtu.be/b\nhttps://youtu.be/a\n"
    assert parse_link_list(text) == ["https://youtu.be/a", "https://youtu.be/b"]


def test_comments_blank_lines_and_punctuation():
    text = ("# my list\n\n  https://youtu.be/a,\n(see https://youtu.be/b)\n"
            "# https://youtu.be/hidden\nnot a link\n")
    assert parse_link_list(text) == ["https://youtu.be/a", "https://youtu.be/b"]


def test_several_links_on_one_line_and_csv():
    assert parse_link_list("a,https://x.com/1;https://x.com/2 title") == ["https://x.com/1", "https://x.com/2"]
    assert parse_link_list('"https://x.com/1","https://x.com/2"') == ["https://x.com/1", "https://x.com/2"]
    assert parse_link_list("") == []
