from app.utils.text_splitter import SemanticTextSplitter, SentenceTextSplitter


def test_sentence_splitter_keeps_trailing_text_without_terminal_punctuation():
    chunks = SentenceTextSplitter.split('第一句。第二句没有句号')

    assert [chunk['text'] for chunk in chunks] == ['第一句。', '第二句没有句号']


def test_semantic_splitter_produces_semantic_chunks_instead_of_recursive_fallback():
    text = (
        'Apple fruit nutrition helps health. '
        'Apple vitamin benefits support diet. '
        'Database index speeds queries. '
        'Database storage keeps records.'
    )

    chunks = SemanticTextSplitter.split(
        text=text,
        chunk_size=120,
        chunk_overlap=0,
        similarity_threshold=0.1,
    )

    assert len(chunks) == 2
    assert all(chunk['metadata']['method'] == 'semantic' for chunk in chunks)
    assert chunks[0]['text'].startswith('Apple')
    assert chunks[1]['text'].startswith('Database')



def test_semantic_splitter_falls_back_for_oversized_single_sentence():
    text = 'A' * 260

    chunks = SemanticTextSplitter.split(
        text=text,
        chunk_size=100,
        chunk_overlap=10,
        similarity_threshold=0.1,
    )

    assert len(chunks) >= 3
    assert all(len(chunk['text']) <= 100 for chunk in chunks)
    assert all(chunk['metadata']['method'] == 'semantic' for chunk in chunks)
