"""
Meaning-based matching with a local embedding model (Microsoft E5 by default; see config).

Each passage becomes a vector of numbers representing its meaning; passages (or a query) with
similar meanings have vectors pointing the same way, so their dot product is high. The model is
loaded from the local models folder and runs on this machine only. It is downloaded once, pinned to
an exact revision, the first time it's needed (or ahead of time by the install scripts).

E5 expects a prefix on every text: "passage: " for text being searched, "query: " for searches and
for comparing two texts with each other.
"""
import os
import re
import threading
from typing import Callable, List, Optional, Sequence

import numpy as np

from src import config

# The tokenizer's own worker threads can deadlock when the process forks, which OCR does (it starts
# Tesseract); the library then disables them itself with a warning. Decide it up front instead: nearly
# all the time is spent in the model, not in splitting text into tokens.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_load_lock = threading.Lock()
_encode_lock = threading.Lock()  # One encoding at a time: the indexer and a search can share the model
_model = None

ProgressCallback = Callable[[int, int], None]


def model_files_present() -> bool:
    """Whether the pinned model has already been downloaded (checked without loading it)."""
    folder = config.MODEL_DIR / ("models--" + config.EMBEDDING_MODEL.replace("/", "--")) / "snapshots"
    return (folder / config.EMBEDDING_REVISION / "model.safetensors").exists()


def get_model():
    """The embedding model, loaded once. Downloads it (pinned revision) if it isn't present yet."""
    global _model
    with _load_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer  # Heavy import: only when needed
            config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            _model = SentenceTransformer(
                config.EMBEDDING_MODEL,
                revision=config.EMBEDDING_REVISION,
                cache_folder=str(config.MODEL_DIR),
                device=config.EMBEDDING_DEVICE,
                local_files_only=model_files_present(),  # Never contact the internet once downloaded
            )
        return _model


def _encode(texts: Sequence[str]) -> np.ndarray:
    with _encode_lock:
        vectors = get_model().encode(list(texts), batch_size=config.EMBEDDING_BATCH,
                                     normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    return vectors.astype(np.float32)


def embed_passages(texts: Sequence[str], on_progress: Optional[ProgressCallback] = None) -> np.ndarray:
    """Vectors for passages to be searched, in batches so progress can be reported and searches interleave."""
    if not texts:
        return np.zeros((0, config.EMBEDDING_DIMENSIONS), dtype=np.float32)
    parts: List[np.ndarray] = []
    step = config.EMBEDDING_BATCH * 4
    for start in range(0, len(texts), step):
        parts.append(_encode(["passage: " + t for t in texts[start:start + step]]))
        if on_progress:
            on_progress(min(start + step, len(texts)), len(texts))
    return np.vstack(parts)


def embed_query(text: str) -> np.ndarray:
    return _encode(["query: " + text])[0]


def embed_for_comparison(texts: Sequence[str]) -> np.ndarray:
    """Vectors for comparing texts with each other (symmetric), e.g. sentence against sentence."""
    if not texts:
        return np.zeros((0, config.EMBEDDING_DIMENSIONS), dtype=np.float32)
    return _encode(["query: " + t for t in texts])


def passage_text(clause_title: str, text: str) -> str:
    """What gets embedded for a passage: its clause title gives short passages their context."""
    return f"{clause_title}. {text}" if clause_title and not text.startswith(clause_title) else text


_sentence_cache: dict = {}
_SENTENCE_CACHE_LIMIT = 20000
# A full stop, semicolon or colon followed by a space and a capital; dots inside identifiers ("K3.5") don't split
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\"“])")


def sentences(text: str) -> List[str]:
    """
    A passage's substantive sentences, for pairing with another passage's. Very short ones (a run-in
    clause title, "RQ-0003 applies.") are left out: they look alike without saying much.
    """
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text)]
    substantive = [p for p in parts if len(p.split()) >= config.MIN_SENTENCE_WORDS]
    return substantive or [text]


def sentence_vectors(texts: Sequence[str]) -> np.ndarray:
    """Vectors for sentences, cached: the same passages are compared again on every page view."""
    missing = [t for t in dict.fromkeys(texts) if t not in _sentence_cache]
    if missing:
        for text, vector in zip(missing, embed_for_comparison(missing)):
            if len(_sentence_cache) >= _SENTENCE_CACHE_LIMIT:
                _sentence_cache.clear()
            _sentence_cache[text] = vector
    return np.vstack([_sentence_cache[t] for t in texts]) if texts else np.zeros((0, config.EMBEDDING_DIMENSIONS), np.float32)


def aligned_sentences(focus_text: str, other_texts: Sequence[str]) -> List[List[tuple]]:
    """
    For each other passage: every focus sentence paired with its closest sentence there, as
    (focus sentence, other sentence, similarity), best pair first.
    """
    ours = sentences(focus_text)
    theirs = [sentences(t) for t in other_texts]
    vectors = sentence_vectors(ours + [s for group in theirs for s in group])
    mine, start, aligned = vectors[:len(ours)], len(ours), []
    for group in theirs:
        scores = mine @ vectors[start:start + len(group)].T
        pairs = [(ours[i], group[int(np.argmax(scores[i]))], float(scores[i].max())) for i in range(len(ours))]
        aligned.append(sorted(pairs, key=lambda p: -p[2]))
        start += len(group)
    return aligned


if __name__ == "__main__":
    # `python -m src.search.semantic`: download the model ahead of time (the install scripts do this).
    # Quick when it's already there: the files are checked, not loaded.
    if model_files_present():
        print(f"Meaning model present: {config.EMBEDDING_MODEL} ({config.MODEL_DIR})")
    else:
        print(f"Downloading the meaning model {config.EMBEDDING_MODEL} (about 440 MB, once) to {config.MODEL_DIR}…")
        get_model()
        print("Meaning model ready.")
