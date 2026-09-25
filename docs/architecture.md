# System Architecture

## Objective

Given ingredients available to a student in Taiwan, recommend practical Vietnamese dishes and explain how to cook them.

## Main Pipeline

```text
A. Recipe knowledge pipeline

TikTok keyword discovery
        |
        v
source URL + metadata
        |
        v
Saveto transcript generation
        |
        v
raw transcript (.txt)
        |
        v
parallel quality gate
        |
        v
structured recipe extraction
        |
        v
normalized recipe knowledge base


B. Ingredient vision pipeline

Taiwan ingredient images
        |
        v
image classification / detection
        |
        v
canonical ingredient IDs


C. Recommendation pipeline

recognized ingredients
        +
recipe knowledge base
        |
        v
candidate retrieval
        |
        v
ranking
        |
        v
RAG cooking assistant
```

## Transcription Boundary

Saveto is an external transcription provider, not a component implemented by this repository.

The repository begins automated processing after a transcript has been copied/downloaded locally.

This boundary keeps the codebase independent from TikTok media decoding, FFmpeg and GPU speech recognition.

## Parallel Processing

Transcript post-processing is embarrassingly parallel because each source is independent.

For the first batch:

```text
SRC0001.txt --+
SRC0002.txt --+
SRC0003.txt --+
...            +--> ThreadPoolExecutor --> quality results
SRC0010.txt --+
```

The default test uses 10 workers for 10 transcripts. Missing or malformed samples are skipped rather than blocking the batch.

Later, structured recipe extraction can use the same per-source parallel architecture.

## Failure Policy

Individual failures are not treated as pipeline failures.

Examples:

- video unavailable
- transcript unavailable
- no useful speech
- music-only content
- repeated/hallucinated transcript
- non-recipe video

These samples are logged and skipped.

The pipeline should only be debugged when failures become systematic across a large fraction of sources.

## Research Focus

The project should spend effort on:

- recipe representation,
- ingredient normalization,
- ingredient recognition,
- retrieval,
- recommendation,
- evaluation.

Transcription is treated as upstream data acquisition.
