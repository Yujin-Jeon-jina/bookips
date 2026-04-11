"""ISBN 캐시 (SQLite) 테스트"""
import pytest
from bookips.isbn.cache import ISBNCache


@pytest.fixture
def cache(tmp_path):
    return ISBNCache(db_path=tmp_path / "test.db")


class TestMappingCache:
    def test_save_and_get(self, cache):
        cache.save_mapping("9780000000001", "9780000000002", "manual", 1.0)
        result = cache.get_mapping("9780000000001")
        assert result is not None
        assert result["contract_isbn"] == "9780000000002"
        assert result["match_method"] == "manual"
        assert result["confidence"] == 1.0

    def test_get_nonexistent(self, cache):
        result = cache.get_mapping("9780000000099")
        assert result is None

    def test_upsert(self, cache):
        cache.save_mapping("9780000000001", "9780000000002", "fuzzy", 0.8)
        cache.save_mapping("9780000000001", "9780000000003", "manual", 1.0)
        result = cache.get_mapping("9780000000001")
        assert result["contract_isbn"] == "9780000000003"
        assert result["match_method"] == "manual"

    def test_delete(self, cache):
        cache.save_mapping("9780000000001", "9780000000002", "manual", 1.0)
        assert cache.delete_mapping("9780000000001") is True
        assert cache.get_mapping("9780000000001") is None

    def test_delete_nonexistent(self, cache):
        assert cache.delete_mapping("9780000000099") is False

    def test_list_mappings(self, cache):
        cache.save_mapping("9780000000001", "9780000000010", "direct", 1.0)
        cache.save_mapping("9780000000002", "9780000000020", "fuzzy", 0.85)
        mappings = cache.list_mappings()
        assert len(mappings) == 2
        # updated_at 내림차순
        assert mappings[0]["usage_isbn"] == "9780000000002"


class TestMetadataCache:
    def test_save_and_get_metadata(self, cache):
        cache.save_metadata(
            isbn="9780000000001",
            title="테스트 도서",
            author="홍길동",
            publisher="테스트출판사",
            set_isbn="9780000000100",
            edition="개정판",
        )
        result = cache.get_metadata("9780000000001")
        assert result is not None
        assert result["title"] == "테스트 도서"
        assert result["author"] == "홍길동"
        assert result["set_isbn"] == "9780000000100"

    def test_get_nonexistent_metadata(self, cache):
        assert cache.get_metadata("9780000000099") is None

    def test_metadata_upsert(self, cache):
        cache.save_metadata("9780000000001", "초판", "저자A", "출판A")
        cache.save_metadata("9780000000001", "개정판", "저자A", "출판A")
        result = cache.get_metadata("9780000000001")
        assert result["title"] == "개정판"
