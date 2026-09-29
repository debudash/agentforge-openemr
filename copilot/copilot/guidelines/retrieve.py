"""Hybrid retrieval over the guideline corpus (Week 2 stage 6).

Sparse (BM25) and dense (sentence-transformers, in process) candidates are fused by reciprocal
rank, boosted when a chunk's conditions overlap the chart's problem list, reranked by a local
cross-encoder, and cut to top_k. Each hit is a citable chunk: `guideline:<doc>#<section>`.

Two modes, chosen by settings:

- full: BM25 + dense + cross-encoder. Needs two small models (downloaded once from the Hugging
  Face hub, about 90 MB each). This is what the service runs.
- offline (embed_model "none"): BM25 only, no rerank. No network, no models. This is what the
  unit tests and the eval gate run, so a missing model can never fail a push.

The corpus is 20 chunks. That is deliberate: a chunk is one recommendation or one section, so a
citation points at a statement, never at a page of prose. Query rewriting was left out on
purpose (W2_ARCHITECTURE.md §7a).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings
from ..telemetry import emit

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?")


@dataclass(frozen=True)
class Chunk:
    source_id: str          # guideline:<doc>#<section>
    doc_id: str
    title: str
    section: str
    text: str
    url: str
    publisher: str
    published: str
    conditions: frozenset[str]

    def record(self) -> dict[str, Any]:
        """What the verifier and the citation panel see. Numbers in `text` are what a claim may cite."""
        return {"kind": "guideline", "title": self.title, "section": self.section, "text": self.text, "url": self.url,
                "publisher": self.publisher, "published": self.published,
                "page_or_section": self.section, "field_or_chunk_id": self.source_id, "quote_or_value": self.text[:240]}


@dataclass
class Hit:
    chunk: Chunk
    score: float
    bm25_rank: int | None = None
    dense_rank: int | None = None
    rerank_score: float | None = None
    condition_match: bool = False

    def summary(self) -> dict[str, Any]:
        return {"source_id": self.chunk.source_id, "score": round(self.score, 4), "bm25_rank": self.bm25_rank,
                "dense_rank": self.dense_rank, "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
                "condition_match": self.condition_match}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _front_matter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    _, meta, body = raw.split("---", 2)
    out: dict[str, Any] = {}
    for line in meta.strip().splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            out[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            out[key.strip()] = value
    return out, body


def load_corpus(directory: Path = CORPUS_DIR) -> list[Chunk]:
    """One chunk per `## ` section of each markdown file. Sections are the unit of citation."""
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        meta, body = _front_matter(path.read_text(encoding="utf-8"))
        doc_id = str(meta.get("id") or path.stem)
        conditions = frozenset(str(c).lower() for c in meta.get("conditions", []))
        for part in re.split(r"^## ", body, flags=re.M)[1:]:
            heading, _, text = part.partition("\n")
            text = " ".join(text.split())
            if not text:
                continue
            chunks.append(Chunk(source_id=f"guideline:{doc_id}#{_slug(heading)}", doc_id=doc_id, title=str(meta.get("title", doc_id)),
                                section=heading.strip(), text=text, url=str(meta.get("url", "")), publisher=str(meta.get("publisher", "")),
                                published=str(meta.get("published", "")), conditions=conditions))
    return chunks


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class GuidelineIndex:
    """Built once per process. Models load lazily on the first search in full mode."""

    def __init__(self, settings: Settings, chunks: list[Chunk] | None = None) -> None:
        self.settings = settings
        self.chunks = chunks if chunks is not None else load_corpus(Path(settings.guidelines_dir) if settings.guidelines_dir else CORPUS_DIR)
        from rank_bm25 import BM25Okapi

        self._bm25 = BM25Okapi([tokenize(f"{c.title} {c.section} {c.text}") for c in self.chunks])
        self._embedder: Any = None
        self._embeddings: Any = None
        self._reranker: Any = None

    @property
    def offline(self) -> bool:
        return self.settings.embed_model.lower() == "none"

    # -- dense ------------------------------------------------------------------------
    def _ensure_dense(self) -> None:
        if self._embeddings is not None:
            return
        from sentence_transformers import SentenceTransformer

        self._embedder = SentenceTransformer(self.settings.embed_model)
        self._embeddings = self._embedder.encode([f"{c.title}. {c.section}. {c.text}" for c in self.chunks],
                                                 normalize_embeddings=True, convert_to_numpy=True)

    def _dense_ranks(self, query: str) -> dict[int, int]:
        self._ensure_dense()
        q = self._embedder.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
        scores = self._embeddings @ q
        order = sorted(range(len(self.chunks)), key=lambda i: -float(scores[i]))
        return {i: rank for rank, i in enumerate(order[: self.settings.retrieval_candidates], start=1)}

    def _bm25_ranks(self, query: str) -> dict[int, int]:
        scores = self._bm25.get_scores(tokenize(query))
        order = [i for i in sorted(range(len(self.chunks)), key=lambda i: -float(scores[i])) if scores[i] > 0]
        return {i: rank for rank, i in enumerate(order[: self.settings.retrieval_candidates], start=1)}

    # -- rerank -----------------------------------------------------------------------
    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        mode = self.settings.rerank.lower()
        if mode == "none" or self.offline or not hits:
            return hits
        if mode == "cohere":
            return self._rerank_cohere(query, hits)
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(self.settings.rerank_model)
        scores = self._reranker.predict([(query, h.chunk.text) for h in hits])
        for h, s in zip(hits, scores):
            h.rerank_score = float(s)
        return sorted(hits, key=lambda h: -(h.rerank_score or 0.0))

    def _rerank_cohere(self, query: str, hits: list[Hit]) -> list[Hit]:
        """Cohere Rerank behind COPILOT_RERANK=cohere. A second business associate: demo data only."""
        import httpx

        if not self.settings.cohere_api_key:
            return hits
        response = httpx.post("https://api.cohere.com/v2/rerank", timeout=20,
                              headers={"Authorization": f"Bearer {self.settings.cohere_api_key}"},
                              json={"model": self.settings.cohere_rerank_model, "query": query,
                                    "documents": [h.chunk.text for h in hits], "top_n": len(hits)})
        response.raise_for_status()
        for row in response.json().get("results", []):
            hits[row["index"]].rerank_score = float(row["relevance_score"])
        return sorted(hits, key=lambda h: -(h.rerank_score or 0.0))

    # -- search -------------------------------------------------------------------------
    def search(self, query: str, conditions: set[str] | None = None, top_k: int | None = None,
               correlation_id: str | None = None) -> list[Hit]:
        top_k = top_k or self.settings.retrieval_top_k
        bm25 = self._bm25_ranks(query)
        dense = {} if self.offline else self._dense_ranks(query)
        wanted = {c.lower() for c in (conditions or set())}
        fused: dict[int, Hit] = {}
        for i in set(bm25) | set(dense):
            chunk = self.chunks[i]
            score = sum(1.0 / (60 + r) for r in (bm25.get(i), dense.get(i)) if r is not None)   # reciprocal rank fusion
            match = bool(wanted & chunk.conditions)
            if match:
                score += 1.0 / 60   # one extra "vote" for a chunk about a condition on the chart; never a hard filter
            fused[i] = Hit(chunk=chunk, score=score, bm25_rank=bm25.get(i), dense_rank=dense.get(i), condition_match=match)
        candidates = sorted(fused.values(), key=lambda h: -h.score)[: max(top_k * 2, 6)]
        hits = self._rerank(query, candidates)[:top_k]
        emit("guideline_search", correlation_id, query_tokens=len(tokenize(query)), candidates=len(fused), returned=len(hits),
             offline=self.offline, rerank=self.settings.rerank, hits=[h.summary() for h in hits])
        return hits


_index: GuidelineIndex | None = None


def guideline_index(settings: Settings) -> GuidelineIndex:
    global _index
    if _index is None or _index.settings is not settings:
        _index = GuidelineIndex(settings)
    return _index


def index_entries(hits: list[Hit]) -> dict[str, dict[str, Any]]:
    """Retrieved chunks as verifier index entries, keyed by their citable id."""
    return {h.chunk.source_id: h.chunk.record() for h in hits}


def conditions_from_problems(titles: list[str]) -> set[str]:
    """Condition tags a chart implies, from its problem titles, by simple keyword match."""
    text = " ".join(titles).lower()
    tags = {"hypertension": ("hypertension", "high blood pressure"), "diabetes": ("diabetes", "diabetic"),
            "prediabetes": ("prediabetes",), "cholesterol": ("cholesterol", "hyperlipid", "dyslipid"),
            "cardiovascular": ("coronary", "cardiovascular", "heart disease", "myocardial"),
            "kidney": ("kidney", "renal", "ckd"), "potassium": ("hyperkal", "potassium")}
    return {tag for tag, needles in tags.items() if any(n in text for n in needles)}


def rrf_weight(rank: int) -> float:   # exposed for tests
    return 1.0 / (60 + rank)


def cosine(a: list[float], b: list[float]) -> float:   # exposed for tests
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)
