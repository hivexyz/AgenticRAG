from app.config import Settings


def test_postgres_auto_create_schema_defaults_to_environment():
    assert Settings(ENVIRONMENT="development").should_auto_create_postgres_schema is True
    assert Settings(ENVIRONMENT="production").should_auto_create_postgres_schema is False


def test_postgres_auto_create_schema_accepts_blank_and_explicit_override():
    assert Settings(ENVIRONMENT="production", POSTGRES_AUTO_CREATE_SCHEMA="").should_auto_create_postgres_schema is False
    assert Settings(ENVIRONMENT="production", POSTGRES_AUTO_CREATE_SCHEMA="true").should_auto_create_postgres_schema is True
    assert Settings(ENVIRONMENT="development", POSTGRES_AUTO_CREATE_SCHEMA="false").should_auto_create_postgres_schema is False


def test_wiki_inline_submit_defaults_to_environment():
    assert Settings(ENVIRONMENT="development").should_submit_wiki_jobs_inline is True
    assert Settings(ENVIRONMENT="production").should_submit_wiki_jobs_inline is False


def test_wiki_inline_submit_accepts_blank_and_explicit_override():
    assert Settings(ENVIRONMENT="production", WIKI_COMPILE_INLINE_SUBMIT="").should_submit_wiki_jobs_inline is False
    assert Settings(ENVIRONMENT="production", WIKI_COMPILE_INLINE_SUBMIT="true").should_submit_wiki_jobs_inline is True
    assert Settings(ENVIRONMENT="development", WIKI_COMPILE_INLINE_SUBMIT="false").should_submit_wiki_jobs_inline is False


def test_upload_size_bytes_uses_megabyte_setting():
    assert Settings(MAX_UPLOAD_SIZE_MB=2).max_upload_size_bytes == 2 * 1024 * 1024
