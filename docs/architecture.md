# System Architecture

## High-level pipeline

```text
Recipe sources
    |
    +--> audio / captions / metadata
              |
              v
        transcription
              |
              v
      recipe extraction
              |
              v
     normalized recipe DB
              |
              +-----------------------+
                                      |
Ingredient photos                     |
      |                               |
      v                               |
vision classifier / detector          |
      |                               |
      v                               |
canonical ingredient IDs              |
      |                               |
      +-----------> retrieval --------+
                         |
                         v
                   recommendation
                         |
                         v
                    RAG assistant
```

## Design principle

The project separates three tasks:

1. **Perception** — identify ingredients from images.
2. **Retrieval/ranking** — find recipes supported by the available ingredients and user constraints.
3. **Generation** — explain retrieved recipes in natural Vietnamese.

This separation makes each component independently measurable.

## Baselines before advanced AI

The project should establish simple baselines first:

- exact ingredient matching before embedding retrieval;
- lexical recipe search before vector search;
- image classification before multi-object detection;
- deterministic ranking before learned ranking;
- grounded generation after retrieval rather than recipe generation from memory.

## Evaluation

### Ingredient recognition

Potential metrics:

- accuracy / macro F1 for classification;
- mAP50 and mAP50-95 after moving to object detection.

### Retrieval

Potential metrics:

- Precision@K
- Recall@K
- MRR
- human relevance labels

### Recommendation

Evaluate whether recommended recipes satisfy:

- ingredient availability;
- budget;
- cooking time;
- difficulty;
- number of missing ingredients.

### RAG

Measure:

- recipe retrieval relevance;
- factual consistency with retrieved recipe;
- unsupported ingredient/step hallucination rate;
- user usefulness ratings.

## MVP sequence

1. Manually curate 20 ingredient classes.
2. Create 100 structured recipes.
3. Implement deterministic ingredient matching.
4. Establish retrieval baseline.
5. Train ingredient classifier.
6. Connect recognition -> recommendation.
7. Add vector retrieval.
8. Add RAG response generation.
