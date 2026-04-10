"""국립중앙도서관 API 클라이언트 테스트 (모킹)"""
import pytest
import responses as resp_lib
from bookips.isbn.nl_api import NLApiClient, _first


class TestFirstHelper:
    def test_returns_first_existing_key(self):
        doc = {"EA_ISBN": "9781234567890", "isbn": "other"}
        assert _first(doc, "EA_ISBN", "isbn") == "9781234567890"

    def test_falls_back_to_second_key(self):
        doc = {"isbn": "9781234567890"}
        assert _first(doc, "EA_ISBN", "isbn") == "9781234567890"

    def test_returns_default_when_no_key(self):
        doc = {}
        assert _first(doc, "EA_ISBN", "isbn", default="N/A") == "N/A"

    def test_strips_whitespace(self):
        doc = {"TITLE": "  파이썬 입문  "}
        assert _first(doc, "TITLE") == "파이썬 입문"


class TestNLApiClientParsing:
    def test_parse_doc_standard_fields(self):
        doc = {
            "EA_ISBN": "9788961334839",
            "TITLE": "개념원리 고등 공통수학1",
            "AUTHOR": "홍성대 저",
            "PUBLISHER": "개념원리",
            "PUBLISH_PREDATE": "20240101",
            "SET_ISBN": "",
            "EDITION_STMT": "개정판",
            "SUBJECT": "410",
        }
        client = NLApiClient(api_key="test-key")
        meta = client._parse_doc(doc)
        assert meta.ea_isbn == "9788961334839"
        assert meta.title == "개념원리 고등 공통수학1"
        assert meta.author == "홍성대 저"
        assert meta.publisher == "개념원리"
        assert meta.edition == "개정판"

    def test_parse_doc_missing_fields(self):
        """일부 필드가 없어도 빈 문자열로 처리"""
        doc = {"EA_ISBN": "9788961334839"}
        client = NLApiClient(api_key="test-key")
        meta = client._parse_doc(doc)
        assert meta.ea_isbn == "9788961334839"
        assert meta.title == ""
        assert meta.author == ""


@resp_lib.activate
def test_lookup_isbn_success():
    """API 응답 모킹: ISBN 조회 성공"""
    mock_response = {
        "TOTAL_COUNT": "1",
        "docs": [
            {
                "EA_ISBN": "9788961334839",
                "TITLE": "개념원리 고등 공통수학1",
                "AUTHOR": "홍성대",
                "PUBLISHER": "개념원리",
                "PUBLISH_PREDATE": "20240101",
                "SET_ISBN": "",
                "EDITION_STMT": "",
                "SUBJECT": "410",
            }
        ],
    }
    resp_lib.add(
        resp_lib.GET,
        "https://www.nl.go.kr/seoji/SearchApi.do",
        json=mock_response,
        status=200,
    )

    client = NLApiClient(api_key="test-key")
    result = client.lookup_isbn("9788961334839")

    assert result is not None
    assert result.ea_isbn == "9788961334839"
    assert result.title == "개념원리 고등 공통수학1"


@resp_lib.activate
def test_lookup_isbn_empty_result():
    """API 응답: 결과 없음"""
    resp_lib.add(
        resp_lib.GET,
        "https://www.nl.go.kr/seoji/SearchApi.do",
        json={"TOTAL_COUNT": "0", "docs": []},
        status=200,
    )

    client = NLApiClient(api_key="test-key")
    result = client.lookup_isbn("0000000000000")
    assert result is None


@resp_lib.activate
def test_lookup_isbn_network_error():
    """API 네트워크 오류 시 None 반환 (크래시 없음)"""
    resp_lib.add(
        resp_lib.GET,
        "https://www.nl.go.kr/seoji/SearchApi.do",
        body=ConnectionError("connection refused"),
    )

    client = NLApiClient(api_key="test-key")
    # 3번 재시도 후 None 반환해야 함 (예외 전파 없음)
    result = client.lookup_isbn("9788961334839")
    assert result is None
